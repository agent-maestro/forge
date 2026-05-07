"""KiCad backend tests -- Phase E2 of math-to-manufactured-PCB.

Covers:
  * Both shipped examples compile to non-empty schematics.
  * Output parses as well-formed S-expressions.
  * Required top-level structure (kicad_sch / version / generator
    / generator_version / uuid / paper / lib_symbols / sheet_instances).
  * Component instances reference KiCad symbols correctly.
  * Net labels appear at the right positions to connect pins.
  * lib_symbols block contains stubs for every used component type
    (and ONLY those types -- unused stubs would bloat the file).
  * Same input -> byte-identical output (deterministic UUIDs).
  * Modules without spice decorations raise CompileError, not silent.
  * License + audit wiring smoke tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser.parser import parse_file, parse_source
from lang.profiler.profiler import Profiler
from software.backends.kicad_backend import (
    CompileError,
    KiCadBackend,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"


# ── Mini S-expression parser (test-local) ────────────────────────


def _parse_sexpr(text: str):
    """Tiny S-expression parser. Returns nested lists of strings.
    Comments aren't handled (KiCad files don't use them)."""
    pos = 0
    n = len(text)

    def skip_ws() -> int:
        nonlocal pos
        while pos < n and text[pos] in " \t\n\r":
            pos += 1
        return pos

    def parse_atom() -> str:
        nonlocal pos
        if text[pos] == '"':
            # quoted string
            pos += 1
            start = pos
            out = []
            while pos < n and text[pos] != '"':
                if text[pos] == "\\" and pos + 1 < n:
                    out.append(text[pos + 1])
                    pos += 2
                else:
                    out.append(text[pos])
                    pos += 1
            assert pos < n, "unterminated string"
            pos += 1  # closing quote
            return "".join(out)
        start = pos
        while pos < n and text[pos] not in " \t\n\r()":
            pos += 1
        return text[start:pos]

    def parse_list() -> list:
        nonlocal pos
        assert text[pos] == "("
        pos += 1
        out: list = []
        while True:
            skip_ws()
            if pos >= n:
                raise AssertionError("unterminated list")
            if text[pos] == ")":
                pos += 1
                return out
            if text[pos] == "(":
                out.append(parse_list())
            else:
                out.append(parse_atom())

    skip_ws()
    return parse_list()


def _find_all(node, tag: str) -> list:
    """All children whose first element is `tag`. Non-recursive."""
    return [n for n in node if isinstance(n, list) and n and n[0] == tag]


def _find_first(node, tag: str):
    matches = _find_all(node, tag)
    return matches[0] if matches else None


# ── Helpers ──────────────────────────────────────────────────────


def _compile(path: Path) -> str:
    mod = parse_file(str(path))
    Profiler().profile_module(mod)
    return KiCadBackend().compile(mod)


def _compile_src(src: str) -> str:
    mod = parse_source(src, source_file="<inline>")
    Profiler().profile_module(mod)
    return KiCadBackend().compile(mod)


# ── Examples round-trip ──────────────────────────────────────────


def test_rc_filter_example_compiles():
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    assert tree[0] == "kicad_sch", "top-level must be (kicad_sch ...)"


def test_voltage_divider_example_compiles():
    sch = _compile(EXAMPLES / "voltage_divider.eml")
    tree = _parse_sexpr(sch)
    assert tree[0] == "kicad_sch"


# ── Required top-level structure ─────────────────────────────────


def test_required_top_level_keys_present():
    """KiCad 8 expects version, generator, generator_version,
    uuid, paper, lib_symbols, sheet_instances. Missing any of
    these makes KiCad refuse to open the file."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    for required in (
        "version", "generator", "generator_version",
        "uuid", "paper", "lib_symbols", "sheet_instances",
    ):
        assert _find_first(tree, required) is not None, \
            f"missing required top-level: ({required} ...)"


def test_version_is_kicad_8():
    """Version 20231120 is KiCad 8.0's schematic file format."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    version = _find_first(tree, "version")
    assert version[1] == "20231120", \
        f"KiCad 8 expects version 20231120, got {version[1]}"


def test_generator_advertises_eml_forge():
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    gen = _find_first(tree, "generator")
    assert gen[1] == "eml-forge", \
        f"generator should be 'eml-forge', got {gen[1]!r}"


# ── lib_symbols correctness ──────────────────────────────────────


def test_lib_symbols_contains_only_used_types():
    """rc_filter uses R, C, V -> lib_symbols must have stubs for
    Device:R, Device:C, Simulation_SPICE:VDC and NOTHING else."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    lib_symbols = _find_first(tree, "lib_symbols")
    inner = _find_all(lib_symbols, "symbol")
    lib_ids = sorted(s[1] for s in inner)
    assert lib_ids == ["Device:C", "Device:R", "Simulation_SPICE:VDC"], \
        f"expected {{Device:C, Device:R, Simulation_SPICE:VDC}}, got {lib_ids}"


def test_voltage_divider_lib_symbols_excludes_unused():
    """voltage_divider uses ONLY R + V -> no Device:C in lib_symbols."""
    sch = _compile(EXAMPLES / "voltage_divider.eml")
    tree = _parse_sexpr(sch)
    lib_symbols = _find_first(tree, "lib_symbols")
    lib_ids = {s[1] for s in _find_all(lib_symbols, "symbol")}
    assert "Device:C" not in lib_ids, \
        "Device:C must NOT appear when no @spice_capacitor is declared"


# ── Component instances ──────────────────────────────────────────


def test_component_count_matches_input():
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    # Top-level (symbol ...) entries are instances; the lib_symbols
    # block contains its OWN (symbol ...) but those are nested.
    instances = _find_all(tree, "symbol")
    assert len(instances) == 3, \
        f"rc_filter has 3 components (R1, C1, Vin); got {len(instances)} instances"


def test_component_references_match_eml_names():
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    instances = _find_all(tree, "symbol")
    refs: set[str] = set()
    for inst in instances:
        for prop in _find_all(inst, "property"):
            if prop[1] == "Reference":
                refs.add(prop[2])
    assert refs == {"R1", "C1", "Vin"}, \
        f"reference designators should match EML names: got {refs}"


def test_component_lib_ids_match_decorator_kind():
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    instances = _find_all(tree, "symbol")
    by_ref: dict[str, str] = {}
    for inst in instances:
        ref = next(p[2] for p in _find_all(inst, "property")
                   if p[1] == "Reference")
        lib_id = _find_first(inst, "lib_id")[1]
        by_ref[ref] = lib_id
    assert by_ref == {
        "R1":  "Device:R",
        "C1":  "Device:C",
        "Vin": "Simulation_SPICE:VDC",
    }, f"component -> lib_id mapping wrong: {by_ref}"


# ── Connectivity (labels at pin endpoints) ───────────────────────


def test_label_count_equals_2x_components():
    """Every 2-pin component contributes 2 labels (one per pin),
    regardless of net sharing -- multiple labels with the same
    name across components is exactly how KiCad expresses
    connectivity."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    labels = _find_all(tree, "label")
    instances = _find_all(tree, "symbol")
    assert len(labels) == 2 * len(instances), \
        f"expected {2 * len(instances)} labels, got {len(labels)}"


def test_net_in_appears_at_two_pins():
    """rc_filter: 'in' is shared by R1.pin1 (top) and Vin.pin1 (top).
    Both should generate a label named 'in'."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    label_names = [lbl[1] for lbl in _find_all(tree, "label")]
    assert label_names.count("in") == 2, \
        f"net 'in' must label R1.pin1 and Vin.pin1; got count={label_names.count('in')}"


def test_net_out_appears_at_two_pins():
    """rc_filter: 'out' is shared by R1.pin2 (bottom) and C1.pin1 (top)."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    label_names = [lbl[1] for lbl in _find_all(tree, "label")]
    assert label_names.count("out") == 2


def test_ground_net_zero_appears():
    """rc_filter: '0' (ground) is at C1.pin2 and Vin.pin2."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    label_names = [lbl[1] for lbl in _find_all(tree, "label")]
    assert label_names.count("0") == 2


# ── Determinism ──────────────────────────────────────────────────


def test_same_input_yields_byte_identical_output():
    """Critical for diff-friendly review and fingerprint binding:
    two compiles of the same source must agree byte-for-byte."""
    a = _compile(EXAMPLES / "rc_filter.eml")
    b = _compile(EXAMPLES / "rc_filter.eml")
    assert a == b, \
        "non-deterministic UUIDs: same EML input produced different .kicad_sch"


def test_value_text_uses_si_prefix():
    """1000.0 ohms -> '1kOhm' in the schematic Value field, not '1000'."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    assert "1kOhm" in sch
    assert "1uF" in sch


def test_no_float_precision_artifacts_in_coordinates():
    """Float arithmetic noise like '111.75999999999999' must not
    leak into coordinates. _mm() formatter rounds to 2 decimals."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    assert "999999" not in sch
    assert "0000001" not in sch


# ── Error cases ──────────────────────────────────────────────────


def test_module_with_no_spice_decoration_raises():
    with pytest.raises(CompileError, match="no SPICE-decorated"):
        _compile_src(
            "module no_circuit;\n"
            "fn pure_math(x: Real) -> Real { x * x }\n"
        )


def test_misnamed_component_rejected():
    with pytest.raises(CompileError, match=r"must start with 'R'"):
        _compile_src(
            'module bad;\n'
            '@spice_resistor(name = "X1", a = "in", b = "out", value = 1.0)\n'
            'fn circuit() -> Real { 0.0 }\n'
        )


# ── Schematic terminator ─────────────────────────────────────────


def test_sheet_instances_present():
    """KiCad refuses to open a schematic without (sheet_instances ...)."""
    sch = _compile(EXAMPLES / "rc_filter.eml")
    tree = _parse_sexpr(sch)
    sheet = _find_first(tree, "sheet_instances")
    assert sheet is not None
    path = _find_first(sheet, "path")
    assert path[1] == "/", "root path must be '/'"


# ── License + audit wiring smoke ─────────────────────────────────


def test_kicad_in_pro_targets():
    from tools.license.verifier import PRO_TARGETS, FREE_TARGETS
    assert "kicad" in PRO_TARGETS
    assert "kicad" not in FREE_TARGETS


def test_kicad_registered_in_audit_invokers():
    from tools.cli.audit import _BACKEND_INVOKERS
    names = {n for n, _, _ in _BACKEND_INVOKERS}
    assert "kicad" in names


def test_backend_alias_exposed():
    from software.backends import kicad_backend
    assert kicad_backend.Backend is kicad_backend.KiCadBackend
