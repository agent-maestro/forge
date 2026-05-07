"""JLCPCB part mapper -- Phase E3 of math-to-manufactured-PCB.

Takes the same ``@spice_<component>`` decorations the SPICE +
KiCad backends consume, matches each one against a curated
LCSC-part registry, and emits a JLCPCB-ready BOM + CPL + manifest
bundle.

What v1 ships
-------------
1. **Curated registry** (this file, ``_REGISTRY``) of common
   JLCPCB *Basic Parts* — the cheap, no-extra-tooling-fee tier
   most prototypes use. Resistors and capacitors in the E12
   series, common inductor decades, and a handful of
   pin-header / connector entries for voltage-source nets.
2. **Tolerance-aware lookup** so ``1000.0`` ohms matches
   ``1k``-rated entries without exact float equality.
3. **BOM CSV** in the format JLC's web uploader accepts:
   ``Comment,Designator,Footprint,LCSC Part #``.
4. **CPL CSV** — header-only stub. We deliberately do NOT
   generate placement data because we do not have a PCB layout;
   the user must regenerate the CPL from KiCad's
   *Generate Position File* after PCB layout. Emitting fake X/Y
   coordinates would produce a working-looking file that
   silently misassembles the board, so the stub instead carries
   a comment line telling the user where the real data must
   come from.
5. **Manifest JSON** -- summary, list of matches, unmatched
   parts, warnings, suggested follow-up commands.

What v1 deliberately defers
---------------------------
  * Auto-fetching footprints via JLC2KiCad_lib. The manifest
    points the user at that tool; we do not invoke it (CI must
    not require network access).
  * Extended/non-basic parts. The registry is intentionally
    small. A user can extend the registry by passing a
    ``custom_registry=<dict>`` to :class:`JLCPCBMapper`.
  * Tolerance bands (1%, 5%) and voltage ratings on capacitors.
    v1 matches on canonical value only and uses the cheapest
    matching rating from the registry.
  * Multi-pin devices (op-amps etc.) — out of scope until E2.5
    teaches the SPICE/KiCad layer about them.

Standing rule
-------------
A board ordered from a malformed BOM costs real money. The
manifest's ``warnings`` field lists every component that fell
back to a less-specific match or failed to match entirely; the
caller should surface those to the user before submitting.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
from typing import Optional

from lang.parser.ast_nodes import EMLModule
from software.backends.spice_backend import (
    CompileError as _SpiceCompileError,
    _COMPONENT_DECORATORS,
    _REF_PREFIX,
    _coerce_float,
    _coerce_name,
    _coerce_net,
    _has_any_spice_decoration,
)


# Single shared exception with the SPICE / KiCad backends.
CompileError = _SpiceCompileError


# ─── Part registry (curated subset of JLCPCB Basic) ──────────────


@dataclasses.dataclass(frozen=True)
class PartRegistryEntry:
    """One row of the LCSC part registry.

    ``value`` is the canonical numeric value in base SI units
    (ohms / farads / henries / volts / amps); the lookup compares
    against this with a tolerance band, NOT a string.

    ``footprint`` is the KiCad-library footprint name. JLC's
    SMT assembly accepts any standard package; the v1 registry
    is biased to 0603 because it is the modal hand-rework size
    and it is what JLC's free Basic-part inventory carries the
    most of.
    """
    kind:        str       # "spice_resistor", ...
    value:       float     # canonical value (ohms / farads / henries / volts / amps)
    package:     str       # human-readable, e.g. "0603"
    lcsc_id:     str       # JLCPCB / LCSC SKU, e.g. "C21190"
    description: str       # short, used in BOM Comment column
    footprint:   str       # KiCad footprint, e.g. "Resistor_SMD:R_0603_1608Metric"


# Most common JLCPCB Basic parts. Curated for prototyping;
# extend via JLCPCBMapper(custom_registry=...) for production.
_REGISTRY: tuple[PartRegistryEntry, ...] = (
    # ── Resistors, 0603, 1% — JLC Basic ─────────────────────
    PartRegistryEntry("spice_resistor", 1.0,        "0603", "C22843", "1R 1% 0603",        "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 10.0,       "0603", "C25543", "10R 1% 0603",       "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 100.0,      "0603", "C22775", "100R 1% 0603",      "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 220.0,      "0603", "C22962", "220R 1% 0603",      "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 470.0,      "0603", "C23179", "470R 1% 0603",      "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 1000.0,     "0603", "C21190", "1k 1% 0603",        "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 2200.0,     "0603", "C22962", "2.2k 1% 0603",      "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 4700.0,     "0603", "C23162", "4.7k 1% 0603",      "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 10000.0,    "0603", "C25804", "10k 1% 0603",       "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 22000.0,    "0603", "C31850", "22k 1% 0603",       "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 47000.0,    "0603", "C25819", "47k 1% 0603",       "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 100000.0,   "0603", "C25741", "100k 1% 0603",      "Resistor_SMD:R_0603_1608Metric"),
    PartRegistryEntry("spice_resistor", 1000000.0,  "0603", "C22935", "1M 1% 0603",        "Resistor_SMD:R_0603_1608Metric"),

    # ── Capacitors, 0603, 50V X7R / X5R — JLC Basic ────────
    PartRegistryEntry("spice_capacitor", 1.0e-12,   "0603", "C1685",  "1pF C0G 0603 50V",  "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 10.0e-12,  "0603", "C1633",  "10pF C0G 0603 50V", "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 22.0e-12,  "0603", "C1653",  "22pF C0G 0603 50V", "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 100.0e-12, "0603", "C1622",  "100pF C0G 0603",    "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 1.0e-9,    "0603", "C1588",  "1nF X7R 0603 50V",  "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 10.0e-9,   "0603", "C1546",  "10nF X7R 0603 50V", "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 100.0e-9,  "0603", "C14663", "100nF X7R 0603 50V","Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 1.0e-6,    "0603", "C15849", "1uF X5R 0603 25V",  "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 10.0e-6,   "0603", "C19702", "10uF X5R 0603 16V", "Capacitor_SMD:C_0603_1608Metric"),
    PartRegistryEntry("spice_capacitor", 100.0e-6,  "0805", "C96446", "100uF X5R 0805 6.3V","Capacitor_SMD:C_0805_2012Metric"),

    # ── Inductors, 0603/0805 — JLC Basic ───────────────────
    PartRegistryEntry("spice_inductor", 1.0e-6,   "0603", "C32368", "1uH 0603",   "Inductor_SMD:L_0603_1608Metric"),
    PartRegistryEntry("spice_inductor", 10.0e-6,  "0805", "C84601", "10uH 0805",  "Inductor_SMD:L_0805_2012Metric"),
    PartRegistryEntry("spice_inductor", 100.0e-6, "0805", "C8323",  "100uH 0805", "Inductor_SMD:L_0805_2012Metric"),

    # ── Voltage / current sources are NOT physical parts. ──
    # In the BOM they map to 2-pin headers so the user can wire
    # in a bench supply. The exact LCSC SKU below is the
    # standard 2.54mm pin header. Bypass with custom_registry
    # if your board uses a barrel jack, USB connector, etc.
    PartRegistryEntry("spice_voltage", 0.0, "PinHeader",  "C40541",
                      "2-pin header (DC input, user wires bench supply)",
                      "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"),
    PartRegistryEntry("spice_current", 0.0, "PinHeader",  "C40541",
                      "2-pin header (current source input)",
                      "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"),
)


# ─── Match results ───────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class _Component:
    """Internal mirror of the SPICE / KiCad component record.
    We can't reuse ``software.backends.kicad_backend._Component``
    directly without making the manufacturing module import the
    KiCad backend — circular dependency risk if KiCad ever
    starts depending on manufacturing."""
    kind:    str
    name:    str
    net_a:   str
    net_b:   str
    value:   float


@dataclasses.dataclass(frozen=True)
class PartMatch:
    """One component successfully matched to a registry entry."""
    designator: str           # "R1", "C2", ...
    value:      float         # raw numeric value from EML
    entry:      PartRegistryEntry


@dataclasses.dataclass(frozen=True)
class UnmatchedComponent:
    """One component the registry has no entry for."""
    designator: str
    kind:       str
    value:      float
    reason:     str           # human-readable; goes into the manifest


@dataclasses.dataclass(frozen=True)
class MapResult:
    """Outcome of running the mapper over a module."""
    matches:    tuple[PartMatch,           ...]
    unmatched:  tuple[UnmatchedComponent,  ...]
    warnings:   tuple[str,                 ...]


@dataclasses.dataclass(frozen=True)
class BundleArtifacts:
    """File contents for the JLCPCB-upload bundle."""
    bom_csv:      str         # <stem>.bom.csv
    cpl_csv:      str         # <stem>.cpl.csv (header-only stub)
    manifest:     str         # <stem>.jlc.json
    matched:      int
    unmatched:    int


# ─── Tolerance-aware match ───────────────────────────────────────


_DEFAULT_RTOL = 0.05  # 5% — a hair wider than E12 spacing so a
# user-supplied 9.5k still matches the 10k registry entry.


def _match_one(
    c: _Component,
    registry: tuple[PartRegistryEntry, ...],
    rtol: float = _DEFAULT_RTOL,
) -> Optional[PartRegistryEntry]:
    """Return the closest registry entry for this component, or
    None when nothing in the registry has the right kind OR none
    of the same-kind entries are within ``rtol`` of the value."""
    same_kind = [e for e in registry if e.kind == c.kind]
    if not same_kind:
        return None
    # Voltage / current sources are matched by kind only — value
    # matters for the spec but not for the BOM (it's a pin header).
    if c.kind in ("spice_voltage", "spice_current"):
        return same_kind[0]
    # Pick the closest in log-space (the way component values are
    # spaced on the E12 series).
    target = c.value
    if target <= 0:
        return None
    best:    Optional[PartRegistryEntry] = None
    best_err = float("inf")
    for entry in same_kind:
        if entry.value <= 0:
            continue
        # Relative error -- |reg - target| / target.
        err = abs(entry.value - target) / target
        if err < best_err:
            best     = entry
            best_err = err
    if best is None or best_err > rtol:
        return None
    return best


def _harvest(mod: EMLModule) -> list[_Component]:
    """Pull components from a module the same way the SPICE +
    KiCad backends do, but copy into the manufacturing-local
    record so the dependency arrow only points inward."""
    out: list[_Component] = []
    for fn in mod.functions:
        if not _has_any_spice_decoration(fn):
            continue
        for ann in fn.annotations:
            if ann.kind not in _COMPONENT_DECORATORS:
                continue
            where = f"@{ann.kind}(...)"
            for required in ("name", "a", "b", "value"):
                if required not in ann.args:
                    raise CompileError(
                        f"{where}: missing required keyword "
                        f"{required!r} (needed: name, a, b, value)"
                    )
            # Reuse the SPICE backend's coercers so a malformed
            # decoration fails identically across all three
            # downstream uses.
            prefix = _REF_PREFIX[ann.kind]
            name   = _coerce_name(ann.args["name"], where=where, prefix=prefix)
            net_a  = _coerce_net(ann.args["a"], where=where)
            net_b  = _coerce_net(ann.args["b"], where=where)
            value  = _coerce_float(ann.args["value"], where=where)
            out.append(_Component(
                kind=ann.kind, name=name, net_a=net_a, net_b=net_b,
                value=value,
            ))
    return out


# ─── BOM / CPL emitters ──────────────────────────────────────────


def _bom_row_pretty_value(c: _Component, entry: PartRegistryEntry) -> str:
    """The Comment column in JLC's BOM template displays the
    component value to the assembly operator. We use the
    registry's curated description string (e.g. ``1k 1% 0603``)
    rather than recomputing it — that text is already the row
    JLC's catalog uses, so it round-trips cleanly through their
    web uploader."""
    return entry.description


def _emit_bom_csv(matches: tuple[PartMatch, ...]) -> str:
    """JLC's web-uploader BOM format. Header row is exactly:

        Comment,Designator,Footprint,LCSC Part #

    Components with the same Comment+Footprint+LCSC# get merged
    onto one line with comma-separated Designators (JLC's
    deduplication step).
    """
    # Group by (description, footprint, lcsc_id)
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for m in matches:
        key = (m.entry.description, m.entry.footprint, m.entry.lcsc_id)
        grouped.setdefault(key, []).append(m.designator)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    # Stable order: by first designator alphabetically.
    for (desc, fp, lcsc), refs in sorted(
        grouped.items(), key=lambda item: item[1][0]
    ):
        writer.writerow([desc, ",".join(sorted(refs)), fp, lcsc])
    return buf.getvalue()


def _emit_cpl_csv() -> str:
    """JLC's CPL (component placement list) format.

    Real CPL data requires PCB layout (KiCad's *Generate Position
    File*). Emitting placeholder coordinates would produce a
    working-looking file that silently misassembles the board,
    so the v1 stub is HEADER + a single comment row pointing the
    user at the real source.
    """
    return (
        "Designator,Mid X,Mid Y,Layer,Rotation\n"
        "# CPL data requires PCB layout. Generate from KiCad: "
        "File > Fabrication Outputs > Component Placement (.csv) > Save.\n"
    )


def _emit_manifest(
    project_name: str,
    matches:   tuple[PartMatch,           ...],
    unmatched: tuple[UnmatchedComponent,  ...],
    warnings:  tuple[str,                 ...],
) -> str:
    """A small JSON manifest with just enough for a human or a CI
    job to decide whether the bundle is shippable."""
    payload = {
        "spec":         "monogate-jlcpcb-bundle/v1",
        "project":      project_name,
        "matched":      len(matches),
        "unmatched":    len(unmatched),
        "warnings":     list(warnings),
        "matches": [
            {
                "designator":  m.designator,
                "value":       m.value,
                "lcsc_id":     m.entry.lcsc_id,
                "description": m.entry.description,
                "footprint":   m.entry.footprint,
                "package":     m.entry.package,
            }
            for m in matches
        ],
        "unmatched": [
            {
                "designator":  u.designator,
                "kind":        u.kind,
                "value":       u.value,
                "reason":      u.reason,
            }
            for u in unmatched
        ],
        "next_steps": [
            "Open the .kicad_sch in KiCad, lay out the PCB, "
            "then File > Fabrication Outputs > Component Placement "
            "(.csv) to generate the real CPL.",
            "If any LCSC parts are missing footprints in your "
            "KiCad library, install JLC2KiCad_lib "
            "(pip install JLC2KiCad_lib) and run "
            "`JLC2KiCadLib <part_number>` per missing part.",
            "Resolve any unmatched components above by either "
            "extending the registry (custom_registry kwarg on "
            "JLCPCBMapper) or substituting an in-registry value.",
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ─── Public API ──────────────────────────────────────────────────


class JLCPCBMapper:
    """Map an :class:`EMLModule` to a JLCPCB-upload bundle."""

    def __init__(
        self,
        *,
        custom_registry: Optional[tuple[PartRegistryEntry, ...]] = None,
        rtol: float = _DEFAULT_RTOL,
    ):
        self._registry = custom_registry or _REGISTRY
        self._rtol = rtol

    def map_module(self, mod: EMLModule) -> MapResult:
        components = _harvest(mod)
        if not components:
            raise CompileError(
                f"no SPICE-decorated components in module "
                f"{mod.name!r}; declare a circuit by hosting "
                "@spice_resistor / @spice_capacitor / @spice_voltage / "
                "etc. on a function."
            )
        matches:   list[PartMatch]          = []
        unmatched: list[UnmatchedComponent] = []
        warnings:  list[str]                = []
        for c in components:
            entry = _match_one(c, self._registry, rtol=self._rtol)
            if entry is None:
                unmatched.append(UnmatchedComponent(
                    designator=c.name, kind=c.kind, value=c.value,
                    reason=(
                        f"no registry entry within {self._rtol*100:.0f}% of "
                        f"{c.value} for {c.kind}"
                    ),
                ))
                continue
            matches.append(PartMatch(
                designator=c.name, value=c.value, entry=entry,
            ))
            # Tolerance warning when match is loose.
            if c.kind not in ("spice_voltage", "spice_current") and entry.value > 0:
                err = abs(entry.value - c.value) / c.value
                if err > 0.001:
                    warnings.append(
                        f"{c.name}: registry match {entry.lcsc_id} ({entry.description}) "
                        f"differs from declared value {c.value} by {err*100:.1f}%"
                    )
        if unmatched:
            warnings.append(
                f"{len(unmatched)} component(s) had no registry match; "
                f"the BOM excludes them — JLC will refuse the upload "
                f"until they're resolved (see manifest.unmatched)."
            )
        return MapResult(
            matches=tuple(matches),
            unmatched=tuple(unmatched),
            warnings=tuple(warnings),
        )

    def bundle(self, mod: EMLModule) -> BundleArtifacts:
        result = self.map_module(mod)
        return BundleArtifacts(
            bom_csv=_emit_bom_csv(result.matches),
            cpl_csv=_emit_cpl_csv(),
            manifest=_emit_manifest(
                project_name=mod.name or "eml_circuit",
                matches=result.matches,
                unmatched=result.unmatched,
                warnings=result.warnings,
            ),
            matched=len(result.matches),
            unmatched=len(result.unmatched),
        )
