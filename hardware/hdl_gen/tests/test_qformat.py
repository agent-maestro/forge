"""Tests for `hardware.hdl_gen.qformat`."""

from __future__ import annotations

import math

import pytest

from hardware.hdl_gen.qformat import (
    DEFAULT_Q_FORMATS,
    QFormat,
    decode_to_float,
    default_q,
    encode_float,
    encode_int,
    format_verilog_literal,
)


# ── QFormat dataclass ───────────────────────────────────────────────


def test_qformat_validates_width():
    with pytest.raises(ValueError):
        QFormat(width=1, frac=0)


def test_qformat_validates_frac():
    with pytest.raises(ValueError):
        QFormat(width=16, frac=-1)
    with pytest.raises(ValueError):
        QFormat(width=16, frac=16)   # frac must be < width


def test_default_q_known_widths():
    assert default_q(16) == DEFAULT_Q_FORMATS[16]
    assert default_q(32) == DEFAULT_Q_FORMATS[32]
    assert default_q(64) == DEFAULT_Q_FORMATS[64]


def test_default_q_unknown_width_falls_back_to_half_split():
    q = default_q(20)
    assert q.width == 20
    assert q.frac == 10


def test_qformat_resolution_and_range():
    q = QFormat(width=32, frac=16)
    assert q.resolution == pytest.approx(1.0 / 65536)
    assert q.max_value > 32767.0
    assert q.min_value == -32768.0


# ── Float encoding ─────────────────────────────────────────────────


def test_encode_one_at_q16_16_is_2pow16():
    q = QFormat(width=32, frac=16)
    assert encode_float(1.0, q) == 1 << 16


def test_encode_negative_value():
    q = QFormat(width=32, frac=16)
    assert encode_float(-1.0, q) == -(1 << 16)


def test_encode_zero():
    assert encode_float(0.0, QFormat(width=32, frac=16)) == 0


def test_encode_round_trip_within_resolution():
    q = QFormat(width=32, frac=16)
    for v in (0.5, -0.5, 1.5, 3.14159, -2.71828, 100.0, -100.0):
        encoded = encode_float(v, q)
        decoded = decode_to_float(encoded, q)
        assert abs(decoded - v) <= q.resolution, (
            f"round-trip lost more than resolution for {v}"
        )


def test_encode_saturates_on_overflow():
    q = QFormat(width=16, frac=8)   # range +/- 128
    huge = encode_float(1e6, q)
    # Saturated to max_int = 2**15 - 1 = 32767
    assert huge == 32767
    tiny = encode_float(-1e6, q)
    # Saturated to min_int = -32768
    assert tiny == -32768


def test_encode_nan_is_zero():
    q = QFormat(width=32, frac=16)
    assert encode_float(float("nan"), q) == 0


def test_encode_int_shifts_left_by_frac():
    q = QFormat(width=32, frac=16)
    assert encode_int(5, q) == 5 << 16
    assert encode_int(-3, q) == -3 << 16


# ── Verilog literal formatting ─────────────────────────────────────


def test_format_one_at_q16_16():
    q = QFormat(width=32, frac=16)
    assert format_verilog_literal(1.0, q) == "32'sd65536"


def test_format_negative_with_minus_prefix():
    q = QFormat(width=32, frac=16)
    assert format_verilog_literal(-1.0, q) == "-32'sd65536"


def test_format_zero_no_minus():
    q = QFormat(width=32, frac=16)
    assert format_verilog_literal(0.0, q) == "32'sd0"


def test_format_int_uses_int_path():
    q = QFormat(width=32, frac=16)
    assert format_verilog_literal(5, q) == "32'sd327680"     # 5 << 16


def test_format_bool_special_case():
    q = QFormat(width=32, frac=16)
    assert format_verilog_literal(True, q) == "32'sd1"
    assert format_verilog_literal(False, q) == "32'sd0"


def test_format_at_64_bit():
    q = default_q(64)   # Q32.32
    assert q.frac == 32
    assert format_verilog_literal(1.0, q) == f"64'sd{1 << 32}"


def test_format_at_16_bit():
    q = default_q(16)   # Q8.8
    assert q.frac == 8
    assert format_verilog_literal(1.0, q) == "16'sd256"     # 1 * 2^8
