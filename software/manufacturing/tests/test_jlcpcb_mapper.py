"""JLCPCB mapper tests -- Phase E3.

Covers:
  * Both shipped examples (rc_filter, voltage_divider) match
    cleanly against the registry.
  * BOM CSV format conforms to JLC's web uploader (header row,
    same-part deduplication, comma-separated designators).
  * CPL stub carries the warning row -- emitting placement data
    without a real layout would silently misassemble the board.
  * Manifest JSON has the required spec key + matches/unmatched
    + warnings + next_steps fields.
  * Tolerance match accepts a 5% deviation (E12 spacing).
  * Unmatched values surface in `unmatched` (not silently dropped)
    AND a warning bubbles up; the BOM does NOT include them.
  * Custom registry override works (extension hatch).
  * License gating + CLI smoke test.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from lang.parser.parser import parse_file, parse_source
from lang.profiler.profiler import Profiler
from software.manufacturing import (
    CompileError,
    JLCPCBMapper,
    PartRegistryEntry,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"


def _bundle(path: Path):
    mod = parse_file(str(path))
    Profiler().profile_module(mod)
    return JLCPCBMapper().bundle(mod), mod


def _bundle_src(src: str, **kw):
    mod = parse_source(src, source_file="<inline>")
    Profiler().profile_module(mod)
    return JLCPCBMapper(**kw).bundle(mod), mod


# ── Examples round-trip ──────────────────────────────────────────


def test_rc_filter_bundles_cleanly():
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    assert bundle.matched == 3
    assert bundle.unmatched == 0


def test_voltage_divider_bundles_cleanly():
    bundle, _ = _bundle(EXAMPLES / "voltage_divider.eml")
    assert bundle.matched == 3
    assert bundle.unmatched == 0


# ── BOM CSV format ───────────────────────────────────────────────


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_bom_header_matches_jlc_uploader():
    """JLC's web uploader expects this exact header in this order:
    Comment, Designator, Footprint, LCSC Part #."""
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    rows = _parse_csv(bundle.bom_csv)
    assert rows[0] == ["Comment", "Designator", "Footprint", "LCSC Part #"]


def test_bom_includes_all_matched_designators():
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    rows = _parse_csv(bundle.bom_csv)[1:]   # skip header
    designators = set()
    for row in rows:
        designators.update(row[1].split(","))
    assert designators == {"R1", "C1", "Vin"}


def test_bom_dedup_groups_identical_parts():
    """voltage_divider has two 10k resistors. JLC expects them
    on a single row with the designators comma-joined."""
    bundle, _ = _bundle(EXAMPLES / "voltage_divider.eml")
    rows = _parse_csv(bundle.bom_csv)[1:]
    r_rows = [r for r in rows if "R" in r[1]]
    assert len(r_rows) == 1, \
        f"R1 + R2 (same value, same footprint, same LCSC#) must " \
        f"merge to one BOM row; got {len(r_rows)} R-rows"
    assert r_rows[0][1] == "R1,R2", \
        f"merged designator field should be 'R1,R2', got {r_rows[0][1]!r}"


def test_bom_lcsc_id_is_in_part_number_column():
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    rows = _parse_csv(bundle.bom_csv)[1:]
    lcsc_ids = {r[3] for r in rows}
    # LCSC IDs always start with 'C' followed by digits.
    for lid in lcsc_ids:
        assert lid.startswith("C") and lid[1:].isdigit(), \
            f"LCSC# column must hold a real part number (CnnnnN); got {lid!r}"


def test_bom_excludes_unmatched():
    """A 12.345 ohm resistor doesn't match anything in the registry.
    The BOM must not include it (else JLC will refuse the upload)."""
    bundle, _ = _bundle_src(
        'module unmatched;\n'
        '@spice_resistor(name = "R1", a = "in", b = "out", value = 12.345)\n'
        'fn circuit() -> Real { 0.0 }\n'
    )
    rows = _parse_csv(bundle.bom_csv)[1:]
    assert len(rows) == 0
    assert bundle.unmatched == 1


# ── CPL stub ─────────────────────────────────────────────────────


def test_cpl_emits_header_only():
    """v1 CPL must NOT include placement data. KiCad's PCB editor
    is the only honest source for component XY+rotation."""
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    lines = bundle.cpl_csv.splitlines()
    assert lines[0] == "Designator,Mid X,Mid Y,Layer,Rotation"
    # Subsequent lines should be comments (start with '#') or
    # absent -- never real placement data.
    for line in lines[1:]:
        assert line.strip() == "" or line.lstrip().startswith("#"), \
            f"CPL stub leaked placement data on line {line!r}"


def test_cpl_stub_points_user_to_kicad():
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    assert "KiCad" in bundle.cpl_csv
    assert "Component Placement" in bundle.cpl_csv


# ── Manifest JSON ────────────────────────────────────────────────


def test_manifest_carries_spec_key():
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    payload = json.loads(bundle.manifest)
    assert payload["spec"] == "monogate-jlcpcb-bundle/v1"


def test_manifest_lists_matches_unmatched_warnings_next_steps():
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    payload = json.loads(bundle.manifest)
    for required in ("matches", "unmatched", "warnings", "next_steps"):
        assert required in payload, f"manifest missing {required}"
    assert isinstance(payload["next_steps"], list)
    assert len(payload["next_steps"]) >= 1


def test_manifest_match_records_have_full_metadata():
    bundle, _ = _bundle(EXAMPLES / "rc_filter.eml")
    payload = json.loads(bundle.manifest)
    for m in payload["matches"]:
        for required in (
            "designator", "value", "lcsc_id",
            "description", "footprint", "package",
        ):
            assert required in m, \
                f"manifest match record missing {required}: {m}"


# ── Tolerance ────────────────────────────────────────────────────


def test_tolerance_accepts_e12_neighbours():
    """A 1050-ohm declared value should match the 1k registry
    entry (5% rtol). Confirms the lookup isn't exact-equality."""
    bundle, _ = _bundle_src(
        'module tol;\n'
        '@spice_resistor(name = "R1", a = "in", b = "out", value = 1050.0)\n'
        'fn circuit() -> Real { 0.0 }\n'
    )
    rows = _parse_csv(bundle.bom_csv)[1:]
    assert len(rows) == 1
    assert rows[0][3] == "C21190", "1050 should still resolve to the 1k entry C21190"
    payload = json.loads(bundle.manifest)
    # And surface the deviation as a warning so the user can review.
    assert any("differs from declared value" in w for w in payload["warnings"]), \
        "loose match must produce a tolerance warning"


def test_tolerance_rejects_far_values():
    """A 1.5k resistor (50% off the nearest E12 neighbours we
    carry) should fail to match -- catches a typo before it
    gets manufactured."""
    bundle, _ = _bundle_src(
        'module reject;\n'
        '@spice_resistor(name = "R1", a = "in", b = "out", value = 1500.0)\n'
        'fn circuit() -> Real { 0.0 }\n'
    )
    # 1500 is 50% off 1000 (closest neighbour) -- well outside 5% rtol.
    assert bundle.matched == 0
    assert bundle.unmatched == 1


# ── Custom registry hatch ────────────────────────────────────────


def test_custom_registry_overrides_default():
    """Users can pass their own registry for parts the default
    set doesn't carry."""
    custom = (
        PartRegistryEntry(
            kind="spice_resistor", value=1500.0, package="0805",
            lcsc_id="C99999", description="1.5k 1% 0805 (custom)",
            footprint="Resistor_SMD:R_0805_2012Metric",
        ),
    )
    bundle, _ = _bundle_src(
        'module custom;\n'
        '@spice_resistor(name = "R1", a = "in", b = "out", value = 1500.0)\n'
        'fn circuit() -> Real { 0.0 }\n',
        custom_registry=custom,
    )
    assert bundle.matched == 1
    assert "C99999" in bundle.bom_csv


# ── Error cases ──────────────────────────────────────────────────


def test_no_circuit_module_raises():
    with pytest.raises(CompileError, match="no SPICE-decorated"):
        _bundle_src(
            "module pure_math;\n"
            "fn f(x: Real) -> Real { x * x }\n"
        )


# ── License + audit wiring ───────────────────────────────────────


def test_jlcpcb_in_pro_targets():
    from tools.license.verifier import PRO_TARGETS, FREE_TARGETS
    assert "jlcpcb" in PRO_TARGETS
    assert "jlcpcb" not in FREE_TARGETS
