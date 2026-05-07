"""KiCad backend -- Phase E2 of the Math-to-Manufactured-PCB pipeline.

Compiles an :class:`EMLModule` to a KiCad 8 ``.kicad_sch`` schematic
file (S-expression format, version ``20231120``). Reuses the SPICE
backend's decorator convention (``@spice_resistor``, etc.) so a
single EML source compiles to BOTH a simulatable netlist (via
``--target spice``) AND an editable schematic (via ``--target
kicad``) without duplication.

What v1 ships
-------------
  * R / C / L / V / I components on a horizontal grid.
  * Connectivity via net-name labels placed exactly on each pin
    endpoint -- KiCad treats matching label names as electrically
    connected, so no wire-routing solver is needed.
  * Embedded minimal ``lib_symbols`` stubs for every component
    type used in the module, so the generated file is
    self-contained: KiCad opens it without requiring the standard
    ``Device`` / ``Simulation_SPICE`` libraries to be installed.
  * Deterministic UUIDs derived from the module hash so the same
    EML source always emits a byte-identical schematic (important
    for fingerprinting + diff-friendly review).

What v1 deliberately defers
---------------------------
  * Multi-pin devices (op-amps, MOSFETs, ICs) -- the v1 layout
    grid only knows about 2-pin vertical components. E2.5.
  * Hierarchical sheets, sheet pins -- single root sheet only.
  * PCB layout (``.kicad_pcb``) -- E4 territory; the schematic is
    a netlist with placement, not a manufactured board.
  * Pretty graphics on the embedded lib_symbols. The stubs draw
    a rectangle + 2 pins -- functionally correct, visually
    minimal. Users who want the canonical KiCad styling can
    "Update Symbols from Library" once the file is open.

Standing rule
-------------
The roadmap (``monogate-research/roadmap/math-to-manufactured-pcb.md``)
forbids "verified" claims on output before a human opens the
artifact in the target tool. The KiCad backend's claim is
*structural*: it produces a schema-conforming .kicad_sch that
KiCad 8 should open without errors. Whether the schematic
matches the user's intent is the user's call after opening it.
"""
from __future__ import annotations

import dataclasses
import hashlib
import uuid as _uuid_mod
from typing import Optional

from lang.parser.ast_nodes import (
    Annotation,
    EMLFunction,
    EMLModule,
)
from software.backends.spice_backend import (
    CompileError as _SpiceCompileError,
    _COMPONENT_DECORATORS,
    _coerce_float,
    _coerce_name,
    _coerce_net,
    _format_value,
    _has_any_spice_decoration,
)


# ─── Component → KiCad symbol mapping ─────────────────────────────

# Each entry is (lib_id, default_footprint_hint). The lib_id is the
# canonical KiCad standard-library name; we ALSO embed a minimal
# stub of each used symbol in the file's ``lib_symbols`` block so
# the file is self-contained.
_LIB_ID: dict[str, str] = {
    "spice_resistor":  "Device:R",
    "spice_capacitor": "Device:C",
    "spice_inductor":  "Device:L",
    "spice_voltage":   "Simulation_SPICE:VDC",
    "spice_current":   "Simulation_SPICE:IDC",
}

# SPICE-letter → KiCad reference designator letter. Same letters
# in this case -- the conventions overlap -- but we keep the
# mapping explicit so future divergence (e.g. SPICE 'U' vs KiCad
# 'U') doesn't surprise a reader.
_REF_PREFIX: dict[str, str] = {
    "spice_resistor":  "R",
    "spice_capacitor": "C",
    "spice_inductor":  "L",
    "spice_voltage":   "V",
    "spice_current":   "I",
}


# ─── Embedded lib_symbol stubs ────────────────────────────────────
#
# Each stub is the minimum KiCad 8 will accept: a rectangle for
# the body + two pins (one on top at +3.81mm, one on bottom at
# -3.81mm). The names match KiCad's standard library so a "Update
# Symbols from Library" inside KiCad replaces them with the
# canonical pretty versions.

_STUB_SYMBOLS: dict[str, str] = {
    "Device:R": '''(symbol "Device:R"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 0))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "R" (at 2.032 0 90)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Value" "R" (at 0 0 90)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Footprint" "" (at -1.778 0 90)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Datasheet" "~" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Description" "Resistor" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "R_0_1"
\t\t\t(rectangle (start -1.016 -2.54) (end 1.016 2.54)
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none))))
\t\t(symbol "R_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 1.27)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 0 -3.81 90) (length 1.27)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27)))))))''',
    "Device:C": '''(symbol "Device:C"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 0.254))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "C" (at 0.635 2.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t\t(property "Value" "C" (at 0.635 -2.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t\t(property "Footprint" "" (at 0.9652 -3.81 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left) (hide yes)))
\t\t(property "Datasheet" "~" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Description" "Unpolarized capacitor" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "C_0_1"
\t\t\t(polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762))
\t\t\t\t(stroke (width 0.508) (type default))
\t\t\t\t(fill (type none)))
\t\t\t(polyline (pts (xy -2.032 0.762) (xy 2.032 0.762))
\t\t\t\t(stroke (width 0.508) (type default))
\t\t\t\t(fill (type none))))
\t\t(symbol "C_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 2.794)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 0 -3.81 90) (length 2.794)
\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27)))))))''',
    "Device:L": '''(symbol "Device:L"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 1.016) (hide yes))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "L" (at -1.27 0 90)
\t\t\t(effects (font (size 1.27 1.27)) (justify center)))
\t\t(property "Value" "L" (at 1.905 0 90)
\t\t\t(effects (font (size 1.27 1.27)) (justify center)))
\t\t(property "Footprint" "" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Datasheet" "~" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Description" "Inductor" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "L_0_1"
\t\t\t(rectangle (start -1.016 -2.54) (end 1.016 2.54)
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none))))
\t\t(symbol "L_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 1.27)
\t\t\t\t(name "1" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 0 -3.81 90) (length 1.27)
\t\t\t\t(name "2" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27)))))))''',
    "Simulation_SPICE:VDC": '''(symbol "Simulation_SPICE:VDC"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 0))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "V" (at 2.54 2.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t\t(property "Value" "VDC" (at 2.54 -2.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t\t(property "Footprint" "" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Datasheet" "~" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Description" "DC voltage source (SPICE)" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "VDC_0_1"
\t\t\t(circle (center 0 0) (radius 1.27)
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none)))
\t\t\t(polyline (pts (xy -0.508 0.508) (xy 0.508 0.508))
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none)))
\t\t\t(polyline (pts (xy 0 0.254) (xy 0 0.762))
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none)))
\t\t\t(polyline (pts (xy -0.508 -0.508) (xy 0.508 -0.508))
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none))))
\t\t(symbol "VDC_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 2.54)
\t\t\t\t(name "+" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 0 -3.81 90) (length 2.54)
\t\t\t\t(name "-" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27)))))))''',
    "Simulation_SPICE:IDC": '''(symbol "Simulation_SPICE:IDC"
\t\t(pin_numbers (hide yes))
\t\t(pin_names (offset 0))
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(property "Reference" "I" (at 2.54 2.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t\t(property "Value" "IDC" (at 2.54 -2.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left)))
\t\t(property "Footprint" "" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Datasheet" "~" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Description" "DC current source (SPICE)" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "IDC_0_1"
\t\t\t(circle (center 0 0) (radius 1.27)
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none)))
\t\t\t(polyline (pts (xy 0 0.762) (xy 0 -0.762))
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none)))
\t\t\t(polyline (pts (xy -0.381 -0.381) (xy 0 -0.762) (xy 0.381 -0.381))
\t\t\t\t(stroke (width 0.254) (type default))
\t\t\t\t(fill (type none))))
\t\t(symbol "IDC_1_1"
\t\t\t(pin passive line (at 0 3.81 270) (length 2.54)
\t\t\t\t(name "+" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27)))))
\t\t\t(pin passive line (at 0 -3.81 90) (length 2.54)
\t\t\t\t(name "-" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "2" (effects (font (size 1.27 1.27)))))))''',
}


# ─── Layout constants ─────────────────────────────────────────────

# A4 page = 297 x 210 mm, origin top-left. Components sit on a
# horizontal rail near the top of the page; one column per part,
# 30 mm column pitch -- gives plenty of room for the value text
# and the two net labels above/below.

_ROW_Y          = 80.0    # vertical centre of every component
_COLUMN_X0      = 50.8    # leftmost column
_COLUMN_PITCH   = 30.48   # 1200 mils -- a clean KiCad grid step
_PIN_OFFSET     = 3.81    # pins sit at row_y +/- 3.81 mm
_LABEL_OFFSET   = 0.0     # label sits exactly on the pin endpoint


# ─── Diagnostics ──────────────────────────────────────────────────


# KiCad shares its component-validation helpers with the SPICE
# backend, so it shares the exception type too. A single
# ``CompileError`` class lets callers catch one symbol regardless
# of which backend surfaced the diagnostic.
CompileError = _SpiceCompileError


# ─── UUID generator ───────────────────────────────────────────────
#
# KiCad needs a UUID per symbol, per pin, per label, plus a root
# UUID. We derive every UUID from a deterministic stream so the
# same EML input yields a byte-identical .kicad_sch (essential for
# diff-friendly review and for fingerprint binding).


class _UUIDStream:
    """Deterministic UUID generator, namespaced to one module."""

    _NAMESPACE = _uuid_mod.UUID("6e6d6f74-6f67-6174-6566-6f7267650000")

    def __init__(self, seed: str):
        self._seed = seed
        self._n = 0

    def next(self, tag: str) -> str:
        self._n += 1
        h = hashlib.sha256(
            f"{self._seed}|{self._n}|{tag}".encode("utf-8")
        ).digest()[:16]
        return str(_uuid_mod.UUID(bytes=h, version=4))


# ─── Module → component records ───────────────────────────────────


@dataclasses.dataclass(frozen=True)
class _Component:
    """Internal record per parsed @spice_<kind> decoration."""
    kind:    str          # "spice_resistor", ...
    name:    str          # "R1", "C1", "Vin", ...
    net_a:   str          # net at pin 1 (top)
    net_b:   str          # net at pin 2 (bottom)
    value:   float        # raw numeric value
    lib_id:  str          # KiCad lib_id


def _harvest_components(mod: EMLModule) -> list[_Component]:
    """Walk every host function in source order and pull out every
    component decoration. Order is preserved because schematic
    column placement depends on it."""
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
            prefix = _REF_PREFIX[ann.kind]
            name   = _coerce_name(ann.args["name"], where=where, prefix=prefix)
            net_a  = _coerce_net(ann.args["a"], where=where)
            net_b  = _coerce_net(ann.args["b"], where=where)
            value  = _coerce_float(ann.args["value"], where=where)
            out.append(_Component(
                kind=ann.kind, name=name, net_a=net_a, net_b=net_b,
                value=value, lib_id=_LIB_ID[ann.kind],
            ))
    return out


# ─── Value pretty-printing ────────────────────────────────────────


def _value_text(c: _Component) -> str:
    """Human-friendly value string for the schematic Value field.
    KiCad displays this beside the symbol; SI suffixes make
    review easier than raw scientific notation."""
    if c.kind == "spice_resistor":
        return _si_suffix(c.value, "Ohm")
    if c.kind == "spice_capacitor":
        return _si_suffix(c.value, "F")
    if c.kind == "spice_inductor":
        return _si_suffix(c.value, "H")
    if c.kind in ("spice_voltage", "spice_current"):
        unit = "V" if c.kind == "spice_voltage" else "A"
        return f"{_format_value(c.value)}{unit}"
    return _format_value(c.value)


def _si_suffix(v: float, unit: str) -> str:
    """Pretty-print with SI prefix (k, M, G, m, u, n, p)."""
    if v == 0:
        return f"0{unit}"
    av = abs(v)
    sign = "-" if v < 0 else ""
    if av >= 1e9:  return f"{sign}{av/1e9:g}G{unit}"
    if av >= 1e6:  return f"{sign}{av/1e6:g}M{unit}"
    if av >= 1e3:  return f"{sign}{av/1e3:g}k{unit}"
    if av >= 1:    return f"{sign}{av:g}{unit}"
    if av >= 1e-3: return f"{sign}{av*1e3:g}m{unit}"
    if av >= 1e-6: return f"{sign}{av*1e6:g}u{unit}"
    if av >= 1e-9: return f"{sign}{av*1e9:g}n{unit}"
    return f"{sign}{av*1e12:g}p{unit}"


# ─── S-expression emitters ────────────────────────────────────────


def _mm(v: float) -> str:
    """Format a millimetre coordinate the way KiCad writes them:
    fixed 2 decimals, trailing zeros kept. Avoids the
    ``111.75999999999999`` float-noise that pure ``str(v)`` would
    leak from accumulated arithmetic."""
    return f"{v:.2f}"


def _emit_symbol_instance(
    c: _Component,
    column_idx: int,
    uuid_stream: _UUIDStream,
    project_name: str,
    root_uuid: str,
) -> tuple[str, list[str]]:
    """Emit one (symbol ...) instance block + the labels at its
    two pin endpoints. Returns (symbol_block_text, [label_block_texts])."""
    cx = _COLUMN_X0 + column_idx * _COLUMN_PITCH
    cy = _ROW_Y
    sym_uuid  = uuid_stream.next(f"sym/{c.name}")
    pin1_uuid = uuid_stream.next(f"sym/{c.name}/pin1")
    pin2_uuid = uuid_stream.next(f"sym/{c.name}/pin2")
    val = _value_text(c)

    sym_text = (
        f'\t(symbol\n'
        f'\t\t(lib_id "{c.lib_id}")\n'
        f'\t\t(at {_mm(cx)} {_mm(cy)} 0)\n'
        f'\t\t(unit 1)\n'
        f'\t\t(exclude_from_sim no)\n'
        f'\t\t(in_bom yes)\n'
        f'\t\t(on_board yes)\n'
        f'\t\t(dnp no)\n'
        f'\t\t(uuid "{sym_uuid}")\n'
        f'\t\t(property "Reference" "{c.name}" (at {_mm(cx + 3.81)} {_mm(cy - 1.27)} 0)\n'
        f'\t\t\t(effects (font (size 1.27 1.27)) (justify left)))\n'
        f'\t\t(property "Value" "{val}" (at {_mm(cx + 3.81)} {_mm(cy + 1.27)} 0)\n'
        f'\t\t\t(effects (font (size 1.27 1.27)) (justify left)))\n'
        f'\t\t(property "Footprint" "" (at {_mm(cx)} {_mm(cy)} 0)\n'
        f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'\t\t(property "Datasheet" "~" (at {_mm(cx)} {_mm(cy)} 0)\n'
        f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'\t\t(pin "1" (uuid "{pin1_uuid}"))\n'
        f'\t\t(pin "2" (uuid "{pin2_uuid}"))\n'
        f'\t\t(instances\n'
        f'\t\t\t(project "{project_name}"\n'
        f'\t\t\t\t(path "/{root_uuid}" (reference "{c.name}") (unit 1))))\n'
        f'\t)'
    )

    label_a_uuid = uuid_stream.next(f"label/{c.name}/a")
    label_b_uuid = uuid_stream.next(f"label/{c.name}/b")
    pin1_x, pin1_y = cx, cy - _PIN_OFFSET
    pin2_x, pin2_y = cx, cy + _PIN_OFFSET

    labels = [
        # Top pin (pin "1") -> net_a. Label faces upward (rot 90).
        f'\t(label "{c.net_a}" (at {_mm(pin1_x)} {_mm(pin1_y - _LABEL_OFFSET)} 90)\n'
        f'\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n'
        f'\t\t(uuid "{label_a_uuid}"))',
        # Bottom pin (pin "2") -> net_b. Label faces downward (rot 270).
        f'\t(label "{c.net_b}" (at {_mm(pin2_x)} {_mm(pin2_y + _LABEL_OFFSET)} 270)\n'
        f'\t\t(effects (font (size 1.27 1.27)) (justify left bottom))\n'
        f'\t\t(uuid "{label_b_uuid}"))',
    ]
    return sym_text, labels


def _emit_lib_symbols(used_kinds: set[str]) -> str:
    """Embed the minimal lib_symbol stubs for every component
    type the module actually uses. Skip stubs for unused kinds
    so the file stays small."""
    if not used_kinds:
        return "\t(lib_symbols)"
    lib_ids = sorted({_LIB_ID[k] for k in used_kinds})
    body = "\n\t".join(_STUB_SYMBOLS[lid] for lid in lib_ids)
    return f"\t(lib_symbols\n\t{body}\n\t)"


# ─── Public API ───────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class KiCadCompileResult:
    """What the backend produces."""
    schematic:       str
    component_count: int
    label_count:     int
    used_lib_ids:    tuple[str, ...]


class KiCadBackend:
    """Compile an :class:`EMLModule` to a KiCad 8 .kicad_sch file."""

    name = "kicad"

    def __init__(self, *, optimize: bool = True):
        # Same rationale as SpiceBackend -- the EML optimizer
        # rewrites function bodies; circuit-host functions don't
        # have meaningful bodies to optimize. Accept the kw for
        # API symmetry with audit.py's invoker.
        self.optimize = optimize

    def compile(self, mod: EMLModule) -> str:
        return self.compile_full(mod).schematic

    def compile_full(self, mod: EMLModule) -> KiCadCompileResult:
        components = _harvest_components(mod)
        if not components:
            raise CompileError(
                f"no SPICE-decorated components in module "
                f"{mod.name!r}; declare a circuit by hosting "
                "@spice_resistor / @spice_capacitor / @spice_voltage / "
                "etc. on a function."
            )

        used_kinds = {c.kind for c in components}
        # Deterministic seed: stable across runs for the same
        # module name + component list. We use the components
        # themselves (not the module hash) so a benign comment-
        # only edit doesn't change the UUIDs.
        seed_input = mod.name + "|" + "|".join(
            f"{c.kind}:{c.name}:{c.net_a}:{c.net_b}:{c.value!r}"
            for c in components
        )
        uuid_stream = _UUIDStream(seed_input)
        root_uuid    = uuid_stream.next("root")
        project_name = mod.name or "eml_circuit"

        # Body
        sym_blocks:   list[str] = []
        label_blocks: list[str] = []
        for idx, c in enumerate(components):
            sb, lbs = _emit_symbol_instance(
                c, idx, uuid_stream, project_name, root_uuid,
            )
            sym_blocks.append(sb)
            label_blocks.extend(lbs)

        lib_block = _emit_lib_symbols(used_kinds)

        text = (
            "(kicad_sch\n"
            "\t(version 20231120)\n"
            f'\t(generator "eml-forge")\n'
            f'\t(generator_version "8.0")\n'
            f'\t(uuid "{root_uuid}")\n'
            '\t(paper "A4")\n'
            f"{lib_block}\n"
            f"{chr(10).join(sym_blocks)}\n"
            f"{chr(10).join(label_blocks)}\n"
            "\t(sheet_instances\n"
            '\t\t(path "/" (page "1"))\n'
            "\t)\n"
            ")\n"
        )

        return KiCadCompileResult(
            schematic=text,
            component_count=len(components),
            label_count=len(label_blocks),
            used_lib_ids=tuple(sorted({c.lib_id for c in components})),
        )


# audit.py imports `Backend` from each module; expose the alias.
Backend = KiCadBackend
