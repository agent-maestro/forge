"""Tests for the `eml-compile --explain` diagnostic flag."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lang.parser.parser import parse_source
from tools.cli.explain import _format_module


REPO_ROOT = Path(__file__).resolve().parents[3]


# ── _format_module: in-process unit tests ────────────────────


def test_explain_reports_module_name() -> None:
    src = "fn t(x: f64) -> f64 { x }\n"
    out = _format_module(parse_source(src))
    assert "module" in out


def test_explain_reports_inlined_call_count() -> None:
    src = (
        "fn helper(x: f64) -> f64 { x * 2.0 }\n"
        "fn caller(p: f64) -> f64 { helper(p) + 1.0 }\n"
    )
    out = _format_module(parse_source(src))
    # helper's CALL inside caller is inlined -> 1 CALL site replaced
    assert "1 CALL site(s) replaced" in out or \
           "1 CALL" in out


def test_explain_reports_superbest_family_when_fired() -> None:
    """sigmoid_tanh_form rewrite is the canonical SuperBEST demo."""
    src = (
        "fn sig(x: f64) -> f64 { tanh(x / 2.0) / 2.0 + 0.5 }\n"
    )
    from lang.profiler.profiler import Profiler
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = _format_module(mod)
    assert "sigmoid" in out
    assert "1.08" in out  # digits saved formatted to 2 decimals


def test_explain_reports_node_delta() -> None:
    """A function with `1.0 * x + 0.0` should fold to `x`,
    showing a negative node delta."""
    src = "fn t(x: f64) -> f64 { 1.0 * x + 0.0 }\n"
    out = _format_module(parse_source(src))
    # The output mentions node count delta on a line for `t`.
    lines = out.splitlines()
    t_block = [
        l for l in lines if "->" in l and "nodes:" in l
    ]
    assert any("(-" in l for l in t_block), (
        "expected a negative node delta after constant folding\n"
        + out
    )


def test_explain_emits_no_backend_code() -> None:
    """--explain produces only the diagnostic; no `#include`,
    no `pub fn`, no Verilog `module ... pipeline`."""
    src = (
        "@target(fpga, clock_mhz = 100)\n"
        "fn t(x: f64) -> f64 { x * x }\n"
    )
    from lang.profiler.profiler import Profiler
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = _format_module(mod)
    for forbidden in (
        "#include",
        "pub fn",
        "_pipeline",
        "always @(posedge",
    ):
        assert forbidden not in out, (
            f"--explain should not emit backend code "
            f"({forbidden!r} found)"
        )


# ── End-to-end CLI test ──────────────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    # Subprocess timeout bumped to 240s -- Windows Defender's
    # real-time scanning can add ~90s to Python subprocess
    # startup on this codebase. The actual `--explain` work
    # is sub-second.
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "cli" / "main.py"),
         *args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=240,
    )


def test_cli_explain_runs_on_ml_classifier() -> None:
    """End-to-end: --explain on the ML vertical prints the
    SuperBEST sigmoid hit + per-function diff."""
    target = REPO_ROOT / "industries/ml/inference/binary_classifier.eml"
    r = _run_cli(str(target), "--explain")
    assert r.returncode == 0, (
        f"--explain failed:\nSTDOUT={r.stdout!r}\nSTDERR={r.stderr!r}"
    )
    # SuperBEST hit on sigmoid_tanh_form
    assert "sigmoid_tanh_form" in r.stdout
    assert "sigmoid canonical form" in r.stdout
    assert "1.08" in r.stdout
    # Inliner fired (score / sigmoid_tanh_form get inlined into classify)
    assert "CALL site" in r.stdout


def test_cli_explain_emits_no_backend_code_on_real_file() -> None:
    target = REPO_ROOT / "industries/ml/inference/binary_classifier.eml"
    r = _run_cli(str(target), "--explain")
    assert r.returncode == 0
    assert "#include" not in r.stdout
    assert "pub fn" not in r.stdout
    assert "always @(" not in r.stdout


# ── --backend-stats: per-target footprint reporting ──────────


def test_format_module_with_backend_stats_includes_footprints() -> None:
    """In-process: --backend-stats adds the codegen footprint
    section listing C / Rust LOC."""
    from tools.cli.explain import _format_backend_stats
    from lang.profiler.profiler import Profiler
    src = (
        "@target(fpga, clock_mhz = 100)\n"
        "fn t(x: f64) -> f64 { x * x + 1.0 }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = _format_backend_stats(mod)
    assert "backend codegen footprints" in out
    assert "c (gcc)" in out
    assert "rust (cargo)" in out
    # Verilog appears because we have an @target(fpga) function.
    assert "verilog" in out
    # LOC and chars columns are present for at least one backend.
    assert "LOC" in out and "chars" in out


def test_backend_stats_skips_lean_when_no_verify_block() -> None:
    """Lean line says `skipped` when no @verify(lean) block exists."""
    from tools.cli.explain import _format_backend_stats
    from lang.profiler.profiler import Profiler
    src = "fn t(x: f64) -> f64 { x }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = _format_backend_stats(mod)
    assert "lean" in out
    assert "skipped" in out


def test_backend_stats_skips_verilog_when_no_fpga_block() -> None:
    """Verilog line says `skipped` when no @target(fpga) block."""
    from tools.cli.explain import _format_backend_stats
    from lang.profiler.profiler import Profiler
    src = "fn t(x: f64) -> f64 { x * x }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = _format_backend_stats(mod)
    assert "verilog" in out and "skipped" in out


def test_backend_stats_off_by_default() -> None:
    """Without --backend-stats, footprint section is absent."""
    from tools.cli.explain import _format_module
    from lang.profiler.profiler import Profiler
    src = "fn t(x: f64) -> f64 { x }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = _format_module(mod)
    assert "backend codegen footprints" not in out


# ── --json: machine-readable shape ───────────────────────────


def test_build_explain_report_json_shape() -> None:
    """The JSON shape includes module / source / module_passes /
    functions sections, with per-function fields populated."""
    from tools.cli.explain import build_explain_report
    from lang.profiler.profiler import Profiler
    src = (
        "fn helper(x: f64) -> f64 { x * 2.0 }\n"
        "fn caller(p: f64) -> f64 { helper(p) + 1.0 }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    report = build_explain_report(mod)
    # Top-level keys
    for k in ("module", "source", "module_passes", "functions"):
        assert k in report, f"missing top-level key {k!r}"
    # module_passes shape
    mp = report["module_passes"]
    for k in ("imports_in", "imports_kept", "imports_dropped",
              "calls_inlined", "superbest_hits",
              "superbest_total_digits_saved",
              "cse_bindings_total"):
        assert k in mp, f"missing module_passes key {k!r}"
    # caller -> helper(p) inlines exactly 1 call.
    assert mp["calls_inlined"] == 1
    # functions list shape
    assert isinstance(report["functions"], list)
    assert len(report["functions"]) == 2
    for fn in report["functions"]:
        for k in ("name", "dropped", "node_count_before",
                  "node_count_after", "cse_bindings",
                  "superbest_family", "superbest_digits_saved"):
            assert k in fn, f"missing function key {k!r} in {fn['name']}"


def test_build_explain_report_includes_superbest() -> None:
    from tools.cli.explain import build_explain_report
    from lang.profiler.profiler import Profiler
    src = "fn s(x: f64) -> f64 { tanh(x / 2.0) / 2.0 + 0.5 }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    r = build_explain_report(mod)
    assert r["module_passes"]["superbest_hits"] == 1
    assert r["module_passes"]["superbest_total_digits_saved"] > 1.0
    s_fn = r["functions"][0]
    assert s_fn["superbest_family"] == "sigmoid"
    assert s_fn["superbest_digits_saved"] > 1.0


def test_build_explain_report_with_backend_stats() -> None:
    """When include_backend_stats=True, the report has a
    `backend_stats` section with per-backend dicts."""
    from tools.cli.explain import build_explain_report
    from lang.profiler.profiler import Profiler
    src = (
        "@target(fpga, clock_mhz = 100)\n"
        "fn t(x: f64) -> f64 { x * x }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    r = build_explain_report(mod, include_backend_stats=True)
    assert "backend_stats" in r
    bs = r["backend_stats"]
    for tgt in ("c", "rust", "lean", "verilog"):
        assert tgt in bs, f"missing backend {tgt!r}"
    # Lean has no @verify(lean) -> "skipped" key.
    assert "skipped" in bs["lean"]
    # Verilog has @target(fpga) -> loc/chars/modules.
    assert "loc" in bs["verilog"]
    assert "modules" in bs["verilog"]


def test_print_explain_report_emits_valid_json(capsys) -> None:
    """as_json=True emits parseable JSON to stdout."""
    import json
    from tools.cli.explain import print_explain_report
    from lang.profiler.profiler import Profiler
    src = "fn t(x: f64) -> f64 { x * x }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    print_explain_report(mod, as_json=True)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["module"] == ""
    assert isinstance(parsed["functions"], list)


def test_json_excludes_backend_stats_when_flag_off(capsys) -> None:
    import json
    from tools.cli.explain import print_explain_report
    from lang.profiler.profiler import Profiler
    src = "fn t(x: f64) -> f64 { x }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    print_explain_report(mod, as_json=True, include_backend_stats=False)
    parsed = json.loads(capsys.readouterr().out)
    assert "backend_stats" not in parsed
