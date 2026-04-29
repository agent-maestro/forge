"""Q-format fixed-point encoding for Verilog literals.

Verilog has no native floating-point representation -- numeric
literals get encoded as Q-format fixed-point integers parameterized
by `WIDTH` (total bits, sign included) and `FRAC` (fractional bits).
A Q16.16 representation packs into 32 bits: 1 sign + 15 integer
+ 16 fractional, giving range [-32768, +32767.99998] with
resolution 1/65536.

This module is the CPU-side encoder. The Verilog backend
(`hardware.hdl_gen.verilog_backend`) emits `assign w = <literal>;`
where `<literal>` is the integer returned here.

References:
  - Wikipedia: Q (number format)
  - Xilinx UG901 Vivado synthesis guide on fixed-point literals
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class QFormat:
    """A Q-format spec: total `width` bits with `frac` fractional bits."""
    width: int
    frac: int

    def __post_init__(self):
        if self.width < 2:
            raise ValueError(f"width must be >= 2, got {self.width}")
        if self.frac < 0 or self.frac >= self.width:
            raise ValueError(
                f"frac must be in [0, width-1], got {self.frac} "
                f"(width={self.width})"
            )

    @property
    def integer_bits(self) -> int:
        """Bits available for the integer part (including sign)."""
        return self.width - self.frac

    @property
    def max_value(self) -> float:
        """Largest representable value."""
        return (2 ** (self.integer_bits - 1)) - (1 / (2 ** self.frac))

    @property
    def min_value(self) -> float:
        """Smallest (most negative) representable value."""
        return -(2 ** (self.integer_bits - 1))

    @property
    def resolution(self) -> float:
        """Smallest positive distinguishable step."""
        return 1.0 / (2 ** self.frac)


# Standard Q-formats keyed by total width. The integer/fractional
# split is the conventional balanced choice.
DEFAULT_Q_FORMATS: dict[int, QFormat] = {
    16: QFormat(width=16, frac=8),    # Q8.8  -- range +/-128, res 1/256
    32: QFormat(width=32, frac=16),   # Q16.16 -- range +/-32K, res 1/65K
    64: QFormat(width=64, frac=32),   # Q32.32 -- range +/-2G, res 1/4G
}


def default_q(width: int) -> QFormat:
    """Return the conventional Q-format for the given width."""
    if width in DEFAULT_Q_FORMATS:
        return DEFAULT_Q_FORMATS[width]
    # Fall back to half/half split.
    frac = width // 2
    return QFormat(width=width, frac=frac)


def encode_float(value: float, q: QFormat) -> int:
    """Encode a Python float as a signed Q-format integer.

    Out-of-range values get clamped to the format's min/max with no
    error -- the user's Q-format choice is treated as authoritative.

    Returns a Python int in the half-open range
    [-(2**(width-1)), +(2**(width-1)) - 1].
    """
    if math.isnan(value):
        return 0
    # Saturate to representable range.
    v = max(min(value, q.max_value), q.min_value)
    # Round-half-to-nearest-even via Python's built-in round on float.
    scaled = v * (2 ** q.frac)
    encoded = int(round(scaled))
    # Clamp again post-rounding (overflow at the boundary).
    max_int = (2 ** (q.width - 1)) - 1
    min_int = -(2 ** (q.width - 1))
    return max(min(encoded, max_int), min_int)


def encode_int(value: int, q: QFormat) -> int:
    """Encode a Python int as a signed Q-format integer (shifts left
    by frac to put the int in the integer portion of the fixed-point
    word). Saturates on overflow."""
    encoded = value << q.frac
    max_int = (2 ** (q.width - 1)) - 1
    min_int = -(2 ** (q.width - 1))
    return max(min(encoded, max_int), min_int)


def format_verilog_literal(value: float | int, q: QFormat) -> str:
    """Return the Verilog literal text for a numeric value at the
    given Q-format. Output uses sized signed decimal notation:
    `<width>'sd<int>` (or `-<width>'sd<int>` for negatives).
    """
    if isinstance(value, bool):
        # bool happens to be int subclass in Python; treat literally.
        encoded = 1 if value else 0
    elif isinstance(value, int):
        encoded = encode_int(value, q)
    else:
        encoded = encode_float(float(value), q)
    if encoded < 0:
        return f"-{q.width}'sd{abs(encoded)}"
    return f"{q.width}'sd{encoded}"


def decode_to_float(encoded: int, q: QFormat) -> float:
    """Inverse of `encode_float` -- recover the float value from a
    Q-format integer. Useful for testing round-trip identity."""
    return encoded / (2 ** q.frac)
