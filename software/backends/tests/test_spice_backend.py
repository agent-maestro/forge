"""SPICE backend tests -- Phase E1 of math-to-manufactured-PCB.

Covers:
  * Both shipped examples compile to non-empty netlists.
  * Component emission preserves source order.
  * Net validation rejects malformed names.
  * Component-name prefix is enforced (R1 is OK, X1 in @spice_resistor is not).
  * Multi-decoration analysis stacking works.
  * Modules with NO spice decoration raise CompileError, not silent ''.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser.parser import parse_file, parse_source
from lang.profiler.profiler import Profiler
from software.backends.spice_backend import (
    CompileError,
    SpiceBackend,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"


# ── Examples round-trip ──────────────────────────────────────────


def _compile(path: Path) -> str:
    mod = parse_file(str(path))
    Profiler().profile_module(mod)
    return SpiceBackend().compile(mod)


def test_rc_filter_example_compiles():
    netlist = _compile(EXAMPLES / "rc_filter.eml")
    assert netlist.startswith("rc_filter\n"), \
        "first line must be the title card (module name)"
    assert "R1 in out 1000" in netlist
    assert "C1 out 0 1e-06" in netlist
    assert "Vin in 0 5" in netlist
    assert ".tran 1u 10m" in netlist
    assert netlist.rstrip().endswith(".end")


def test_voltage_divider_example_compiles():
    netlist = _compile(EXAMPLES / "voltage_divider.eml")
    assert "R1 in mid 10000" in netlist
    assert "R2 mid 0 10000" in netlist
    assert "Vin in 0 5" in netlist
    assert ".op" in netlist


def test_component_emission_preserves_source_order():
    """Decorator order on the host fn must equal netlist order --
    SPICE-deck readability depends on it."""
    netlist = _compile(EXAMPLES / "rc_filter.eml")
    body = netlist[netlist.index("R1"):]
    pos_r1  = body.index("R1 in out")
    pos_c1  = body.index("C1 out 0")
    pos_vin = body.index("Vin in 0")
    assert pos_r1 < pos_c1 < pos_vin, (
        "components must appear in source-decoration order; "
        "got Vin before C1 or similar"
    )


# ── Inline-source corner cases ───────────────────────────────────


def _compile_src(src: str) -> str:
    mod = parse_source(src, source_file="<inline>")
    Profiler().profile_module(mod)
    return SpiceBackend().compile(mod)


def test_module_with_no_spice_decoration_raises():
    with pytest.raises(CompileError, match="no SPICE-decorated function"):
        _compile_src(
            "module no_circuit;\n"
            "fn pure_math(x: Real) -> Real { x * x }\n"
        )


def test_misnamed_component_rejected():
    """A @spice_resistor whose name doesn't start with 'R' must
    fail at compile time, not produce a malformed netlist."""
    with pytest.raises(CompileError, match=r"must start with 'R'"):
        _compile_src(
            'module bad_name;\n'
            '@spice_resistor(name = "Q1", a = "in", b = "out", value = 1.0)\n'
            'fn circuit() -> Real { 0.0 }\n'
        )


def test_invalid_net_name_rejected():
    with pytest.raises(CompileError, match="not a valid SPICE net name"):
        _compile_src(
            'module bad_net;\n'
            '@spice_resistor(name = "R1", a = "1bad", b = "out", value = 1.0)\n'
            'fn circuit() -> Real { 0.0 }\n'
        )


def test_missing_required_kw_rejected():
    with pytest.raises(CompileError, match="missing required keyword"):
        _compile_src(
            'module incomplete;\n'
            '@spice_resistor(name = "R1", a = "in", value = 1.0)\n'
            'fn circuit() -> Real { 0.0 }\n'
        )


def test_multiple_analysis_directives_stack():
    """Two @spice_analysis decorators on one fn -> two .* lines
    in source order."""
    netlist = _compile_src(
        'module multi_an;\n'
        '@spice_resistor(name = "R1", a = "in", b = "0", value = 1.0)\n'
        '@spice_analysis(tran = "1u 10m")\n'
        '@spice_analysis(ac = "dec 100 1 1meg")\n'
        'fn circuit() -> Real { 0.0 }\n'
    )
    pos_tran = netlist.index(".tran")
    pos_ac   = netlist.index(".ac")
    assert pos_tran < pos_ac, \
        "analysis directives must stay in source order"


def test_ground_net_zero_accepted():
    """SPICE's literal '0' net (ground) is the only digit-leading
    name accepted."""
    netlist = _compile_src(
        'module ground;\n'
        '@spice_resistor(name = "R1", a = "in", b = "0", value = 100.0)\n'
        'fn circuit() -> Real { 0.0 }\n'
    )
    assert "R1 in 0 100" in netlist


def test_scientific_notation_value_passes_through():
    """value = 1.0e-9 must serialise back as scientific, not
    1e-09 + lossy precision."""
    netlist = _compile_src(
        'module scifmt;\n'
        '@spice_capacitor(name = "C1", a = "n1", b = "0", value = 1.0e-9)\n'
        'fn circuit() -> Real { 0.0 }\n'
    )
    assert "C1 n1 0 1e-09" in netlist


def test_netlist_always_terminates_with_end():
    """ngspice -b stops cleanly only when '.end' is the last
    non-blank line. Regression-guard so future header changes
    don't move it."""
    netlist = _compile_src(
        'module end_check;\n'
        '@spice_voltage(name = "V1", a = "n1", b = "0", value = 1.0)\n'
        'fn circuit() -> Real { 0.0 }\n'
    )
    final_line = netlist.rstrip().splitlines()[-1]
    assert final_line == ".end"


# ── License + audit wiring smoke ─────────────────────────────────


def test_spice_in_pro_targets():
    """E1 ships SPICE under the Pro tier alongside hardware."""
    from tools.license.verifier import PRO_TARGETS, FREE_TARGETS
    assert "spice" in PRO_TARGETS
    assert "spice" not in FREE_TARGETS


def test_spice_registered_in_audit_invokers():
    from tools.cli.audit import _BACKEND_INVOKERS
    names = {n for n, _, _ in _BACKEND_INVOKERS}
    assert "spice" in names, \
        "spice must appear in audit.py's _BACKEND_INVOKERS so " \
        "`eml-compile <file> --target all` covers it"


def test_backend_alias_exposed():
    """audit.py imports `Backend` from each module; spice_backend
    must keep that symbol or `--target all` quietly drops it."""
    from software.backends import spice_backend
    assert spice_backend.Backend is spice_backend.SpiceBackend
