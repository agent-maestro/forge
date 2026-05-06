"""SPICE backend — Phase E1 of the Math-to-Manufactured-PCB pipeline.

Compiles an :class:`EMLModule` to an ngspice-compatible netlist
text. The translation is by-decoration rather than by-syntax-
extension so v1 ships inside EML's existing grammar.

Convention
----------
Components and analyses are declared as decorators on a single
"circuit" function whose body is irrelevant (a sentinel
``0.0`` return is fine — the function exists to host the
decorators). Recognised decorators:

==================== =========================================
Decorator            Meaning
==================== =========================================
``@spice_resistor``  ``name``, ``a``, ``b``, ``value``
``@spice_capacitor`` same shape
``@spice_inductor``  same shape
``@spice_voltage``   same shape (DC value, V or VDC card)
``@spice_current``   same shape (DC source)
``@spice_analysis``  ``tran`` | ``ac`` | ``dc`` = "<args>"
``@spice_subcircuit````name = "<id>"`` — declares the wrapper
==================== =========================================

Each kw value is parsed as a single token (EML's annotation parser
limit) — so net names, component names, and numeric values all
fit. Multi-token expressions (`"dec 100 1 1meg"` for `.ac`)
arrive as quoted STRING tokens.

Example::

    @spice_resistor(name = "R1", a = "in",  b = "out", value = 1000.0)
    @spice_capacitor(name = "C1", a = "out", b = "gnd", value = 1.0e-6)
    @spice_voltage(name = "Vin", a = "in",  b = "gnd", value = 5.0)
    @spice_analysis(tran = "1u 10m")
    fn rc_filter() -> Real { 0.0 }

Functions WITHOUT any spice decorator are ignored — a netlist
module may still carry pure-math helpers.

What v1 deliberately defers
---------------------------
  * MOSFETs, BJTs, op-amps, diodes — these need device models
    and pin counts that two-net annotations can't express.
    Add ``@spice_mosfet(name, g, s, d, b, model)`` etc. in E1.5.
  * Subcircuit body emission. ``@spice_subcircuit`` declares
    the wrapper; the body is empty. E1.5 will scan inner
    decorators for the ``.SUBCKT`` body.
  * ngspice round-trip simulation. The backend produces text
    that ngspice accepts; running it requires the binary on
    PATH, which we don't gate the unit tests on.

Standing rule
-------------
The user's roadmap (``monogate-research/roadmap/math-to-manufactured-pcb.md``)
explicitly forbids "Lean-verified" claims on output before the
user opens the proof in VS Code. SPICE output here is similarly
*structural*: it produces a netlist that simulates; whether the
simulation matches reality is the user's call after running it.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable, Optional

from lang.parser.ast_nodes import (
    Annotation,
    EMLFunction,
    EMLModule,
)


# Decorator kind → SPICE one-letter designator. The lookup is also
# the white-list: a decorator whose name isn't here is ignored
# (could be a Lean / target / verify decorator).
_COMPONENT_DECORATORS: dict[str, str] = {
    "spice_resistor":  "R",
    "spice_capacitor": "C",
    "spice_inductor":  "L",
    "spice_voltage":   "V",
    "spice_current":   "I",
}

_ANALYSIS_KEYWORDS: tuple[str, ...] = ("tran", "ac", "dc", "op")


class CompileError(Exception):
    """Anything the SPICE backend can detect and report cleanly."""


# ──────────────────────────── Helpers ───────────────────────────


def _is_valid_net_name(s: str) -> bool:
    """SPICE accepts net names that are alphanumeric + a few
    safe punctuation chars. We're stricter: identifiers only,
    plus a literal "0" for ground (the SPICE convention)."""
    if not s:
        return False
    if s == "0":
        return True
    return s.replace("_", "").isalnum() and not s[0].isdigit()


def _format_value(v: float) -> str:
    """Pretty-print a numeric component value in SPICE-friendly
    form. ngspice accepts plain decimals AND scientific. We pass
    through whichever form Python repr produces — readable and
    unambiguous. The classic SPICE scale-suffix shortcut (``1k``,
    ``1u``, ``1meg``) is a future cosmetic improvement."""
    s = repr(v)
    if s.endswith(".0"):
        return s[:-2]
    return s


def _coerce_float(raw: object, *, where: str) -> float:
    """The annotation parser hands us each kw value as the raw
    token text (string for STRING / FLOAT / INT / IDENT tokens).
    For ``value = 1.0e-6`` we receive the string ``'1.0e-6'``;
    coerce to float here so ``_format_value`` can normalise it."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError as e:
            raise CompileError(
                f"{where}: expected numeric value, got {raw!r}"
            ) from e
    raise CompileError(
        f"{where}: expected numeric value, got {type(raw).__name__}"
    )


def _coerce_net(raw: object, *, where: str) -> str:
    """Net names arrive as plain strings (STRING or IDENT token
    values). Validate the shape SPICE will accept."""
    if not isinstance(raw, str):
        raise CompileError(
            f"{where}: expected net name string, got {type(raw).__name__}"
        )
    if not _is_valid_net_name(raw):
        raise CompileError(
            f"{where}: {raw!r} is not a valid SPICE net name "
            f"(use alphanumeric + underscore, or '0' for ground)"
        )
    return raw


def _coerce_name(raw: object, *, where: str, prefix: str) -> str:
    """SPICE component names must start with the type's
    designator letter (R1, C2, Vin, …). The user-supplied name
    is checked here so a malformed deck is caught at compile
    time rather than at simulation time."""
    if not isinstance(raw, str) or not raw:
        raise CompileError(
            f"{where}: expected component name string, got {raw!r}"
        )
    if raw[0].upper() != prefix:
        raise CompileError(
            f"{where}: component name {raw!r} must start with "
            f"{prefix!r} (the SPICE designator for this component type)"
        )
    return raw


def _component_line(ann: Annotation) -> str:
    """Lower one ``@spice_<kind>`` decoration to a netlist line."""
    designator = _COMPONENT_DECORATORS[ann.kind]
    where = f"@{ann.kind}(...)"
    args = ann.args

    for required in ("name", "a", "b", "value"):
        if required not in args:
            raise CompileError(
                f"{where}: missing required keyword {required!r} "
                f"(needed: name, a, b, value)"
            )

    name = _coerce_name(args["name"], where=where, prefix=designator)
    a    = _coerce_net(args["a"],    where=where)
    b    = _coerce_net(args["b"],    where=where)
    val  = _coerce_float(args["value"], where=where)

    return f"{name} {a} {b} {_format_value(val)}"


def _analysis_lines(fn: EMLFunction) -> list[str]:
    """For each ``@spice_analysis(<directive> = "...")`` on this
    function (in source order), emit one SPICE control card."""
    out: list[str] = []
    for ann in fn.annotations:
        if ann.kind != "spice_analysis":
            continue
        for kw in _ANALYSIS_KEYWORDS:
            if kw in ann.args:
                val = ann.args[kw]
                if not isinstance(val, str):
                    raise CompileError(
                        f"@spice_analysis: {kw}=... must be a string, "
                        f"got {type(val).__name__}"
                    )
                if kw == "op" and val.strip() == "":
                    out.append(".op")
                else:
                    out.append(f".{kw} {val}")
    return out


def _has_any_spice_decoration(fn: EMLFunction) -> bool:
    """A function counts as a SPICE circuit host iff it carries
    at least one recognised spice_* decoration."""
    for ann in fn.annotations:
        if ann.kind in _COMPONENT_DECORATORS:
            return True
        if ann.kind in ("spice_analysis", "spice_subcircuit"):
            return True
    return False


# ──────────────────────────── Public API ────────────────────────


@dataclasses.dataclass(frozen=True)
class SpiceCompileResult:
    """What the backend produces. ``netlist`` is the full text
    blob ready to pipe into ``ngspice -b``; the counts are
    surfaced for ``--explain``-style summaries."""
    netlist: str
    component_count: int
    analysis_count: int


class SpiceBackend:
    """Compile an :class:`EMLModule` to an ngspice netlist."""

    name = "spice"

    def __init__(self, *, optimize: bool = True):
        # The SPICE backend deliberately does NOT run the EML
        # optimizer on circuit-host functions. The optimizer
        # rewrites bodies for numerical efficiency (CSE, SuperBEST,
        # …) — none of which makes sense for a netlist
        # description. The kw is accepted for API symmetry with
        # the other backends and so audit.py's invoker can pass
        # ``optimize=True`` uniformly.
        self.optimize = optimize

    def compile(self, mod: EMLModule) -> str:
        return self.compile_full(mod).netlist

    def compile_full(self, mod: EMLModule) -> SpiceCompileResult:
        components: list[str] = []
        analyses:   list[str] = []

        host_fns = [f for f in mod.functions if _has_any_spice_decoration(f)]
        if not host_fns and not any(
            ann.kind in _COMPONENT_DECORATORS or ann.kind == "spice_analysis"
            for fn in mod.functions for ann in fn.annotations
        ):
            raise CompileError(
                "no SPICE-decorated function found in module "
                f"{mod.name!r}; declare a circuit by hosting "
                "@spice_resistor / @spice_capacitor / @spice_voltage / "
                "etc. on a function."
            )

        for fn in host_fns:
            for ann in fn.annotations:
                if ann.kind in _COMPONENT_DECORATORS:
                    components.append(_component_line(ann))
            analyses.extend(_analysis_lines(fn))

        # Header — comment block identifies the source. SPICE
        # comments start with '*'. The first line is the title
        # card (NOT a comment); ngspice silently ignores its
        # contents but requires its presence.
        src_file = str(mod.source_file).replace("\\", "/")
        title = mod.name or "eml_circuit"
        lines: list[str] = [
            title,
            "* Generated by EML-lang SPICE backend (Forge backend #34).",
            f"* Source module: {mod.name or '(unnamed)'}",
            f"* Source file:   {src_file}",
            f"* Components:    {len(components)}",
            f"* Analyses:      {len(analyses)}",
            "",
        ]

        if components:
            lines.append("* -- components ----------------------------")
            lines.extend(components)
            lines.append("")

        if analyses:
            lines.append("* -- analyses ------------------------------")
            lines.extend(analyses)
            lines.append("")

        lines.append(".end")

        return SpiceCompileResult(
            netlist="\n".join(lines).rstrip() + "\n",
            component_count=len(components),
            analysis_count=len(analyses),
        )


# Compatibility alias so audit.py's backend lookup that imports
# ``Backend`` from each backend module still works (mirrors
# python_backend, c_backend, etc.).
Backend = SpiceBackend
