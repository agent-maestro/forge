"""PRBMath SD59x18 override emitter.

Companion to the Solidity backend. Given the parent contract name
+ the set of builtins the parent uses, returns a `<Parent>WithPRBMath`
child contract that overrides each supported stub by routing it
through PRBMath SD59x18 fixed-point math.

PRBMath SD59x18 (v4.x) exposes the following math functions in
``src/sd59x18/Math.sol``:

  exp, exp2, ln, log2, log10, sqrt, pow, powu,
  gm, abs, ceil, floor, frac, avg, inv

Notably absent: every trig + hyperbolic function (sin, cos, tan,
asin, acos, atan, sinh, cosh, tanh). For those, the generator
leaves the parent's revert stub in place and emits a `/// @dev`
comment listing the gap so an integrator can drop in their own
implementation (ABDK trig, custom Taylor series, etc.).

The override contract is a thin wrapper — the parent's full logic,
NatSpec, and require() guards stay where they are. This keeps the
audit trail anchored on the parent .sol and lets the override be
diff-reviewed in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass

from lang.parser.ast_nodes import NodeKind


# Builtin → PRBMath SD59x18 function name (one-to-one mapping for
# the math functions PRBMath supplies). Builtins absent from this
# dict have NO PRBMath counterpart and are handled by the
# `_UNSUPPORTED` set below.
_BUILTIN_TO_PRBMATH: dict[NodeKind, str] = {
    NodeKind.EXP:  "exp",
    NodeKind.LN:   "ln",
    NodeKind.SQRT: "sqrt",
    NodeKind.ABS:  "abs",
    NodeKind.POW:  "pow",
}

# Builtins PRBMath SD59x18 doesn't provide. We route these through
# the companion ``TrigSD59x18`` library (see software.backends.
# solidity_trig). The override contract imports both libraries.
_VIA_TRIG_LIBRARY: frozenset[NodeKind] = frozenset({
    NodeKind.SIN, NodeKind.COS, NodeKind.TAN,
    NodeKind.ASIN, NodeKind.ACOS, NodeKind.ATAN,
    NodeKind.SINH, NodeKind.COSH, NodeKind.TANH,
})

# Kept for backwards-compatible callers; identical to the trig set
# (any builtin we previously left unsupported is now covered).
_UNSUPPORTED: frozenset[NodeKind] = frozenset()


# ── Result type ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class PRBMathOverride:
    """Generated override contract metadata."""
    contract_name: str
    """The child contract's name, e.g. ``VpdControlWithPRBMath``."""
    parent_name: str
    """The parent contract being overridden."""
    source: str
    """Full Solidity source of the override contract."""
    overridden: tuple[NodeKind, ...]
    """Builtins that received a PRBMath-backed override."""
    via_trig_library: tuple[NodeKind, ...]
    """Builtins routed through the TrigSD59x18 companion library."""
    unsupported: tuple[NodeKind, ...]
    """Builtins still left as parent revert stubs (none in v1+)."""


# ── Public API ──────────────────────────────────────────────────────


def emit_prbmath_override(
    *,
    parent_name: str,
    used_builtins: set[NodeKind],
    parent_path: str = "./{parent}.sol",
    indent: str = "    ",
) -> PRBMathOverride:
    """Build an override contract that wires the parent's transcendental
    stubs to PRBMath SD59x18.

    Parameters
    ----------
    parent_name
        PascalCase name of the parent contract (e.g. ``VpdControl``).
    used_builtins
        ``SolidityBackend._used_builtins`` after compiling the parent.
    parent_path
        Solidity import path of the parent. ``{parent}`` is filled in
        with ``parent_name``. Default sits next to the override.
    indent
        4-space default to match Solidity style.
    """
    overridden = tuple(
        sorted(
            (k for k in used_builtins if k in _BUILTIN_TO_PRBMATH),
            key=lambda k: k.name,
        ),
    )
    via_trig_library = tuple(
        sorted(
            (k for k in used_builtins if k in _VIA_TRIG_LIBRARY),
            key=lambda k: k.name,
        ),
    )
    unsupported = tuple(
        sorted(
            (k for k in used_builtins if k in _UNSUPPORTED),
            key=lambda k: k.name,
        ),
    )
    contract_name = f"{parent_name}WithPRBMath"
    source = _render(
        parent_name=parent_name,
        contract_name=contract_name,
        parent_path=parent_path.format(parent=parent_name),
        overridden=overridden,
        via_trig_library=via_trig_library,
        unsupported=unsupported,
        indent=indent,
    )
    return PRBMathOverride(
        contract_name=contract_name,
        parent_name=parent_name,
        source=source,
        overridden=overridden,
        via_trig_library=via_trig_library,
        unsupported=unsupported,
    )


# ── Rendering ────────────────────────────────────────────────────────


def _render(
    *,
    parent_name: str,
    contract_name: str,
    parent_path: str,
    overridden: tuple[NodeKind, ...],
    via_trig_library: tuple[NodeKind, ...],
    unsupported: tuple[NodeKind, ...],
    indent: str,
) -> str:
    from software.backends.solidity_trig import trig_function_name

    lines: list[str] = []
    lines.append("// SPDX-License-Identifier: MIT")
    lines.append("pragma solidity ^0.8.20;")
    lines.append("")
    lines.append(
        f"// {contract_name} — PRBMath + TrigSD59x18 overrides for "
        f"{parent_name}."
    )
    lines.append(
        "// Generated by monogate-forge --target solidity --with-prbmath."
    )
    lines.append("//")
    lines.append(
        "// Inherits the parent's full logic + NatSpec; only overrides "
        "the transcendental"
    )
    lines.append(
        "// stubs. Drop into your Foundry project after `forge install "
        "PaulRBerg/prb-math`."
    )
    if unsupported:
        names = ", ".join(k.name.lower() for k in unsupported)
        lines.append(
            f"// Note: parent also uses {names}; no override emitted."
        )
    lines.append("")
    lines.append(f'import "{parent_path}";')
    lines.append(
        'import { SD59x18, sd, unwrap } from "@prb/math/src/SD59x18.sol";'
    )
    if overridden:
        names = ", ".join(_BUILTIN_TO_PRBMATH[k] for k in overridden)
        lines.append(
            f'import {{ {names} }} from "@prb/math/src/sd59x18/Math.sol";'
        )
    if via_trig_library:
        lines.append(
            'import { TrigSD59x18 } from "./TrigSD59x18.sol";'
        )
    lines.append("")
    lines.append(
        f"contract {contract_name} is {parent_name} {{"
    )
    if not overridden and not via_trig_library:
        lines.append(
            f"{indent}// No PRBMath-supported builtins are used by the "
            f"parent."
        )
    for kind in overridden:
        lines.append("")
        lines.extend(_render_prbmath_override(kind, indent=indent))
    for kind in via_trig_library:
        lines.append("")
        lines.extend(_render_trig_override(
            kind, fn_name=trig_function_name(kind), indent=indent,
        ))
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _render_prbmath_override(kind: NodeKind, *, indent: str) -> list[str]:
    """Emit a single `override` function for one PRBMath builtin."""
    pmath = _BUILTIN_TO_PRBMATH[kind]
    if kind == NodeKind.POW:
        sig = "int256 base, int256 exp_"
        body = f"return unwrap({pmath}(sd(base), sd(exp_)));"
    else:
        sig = "int256 x"
        body = f"return unwrap({pmath}(sd(x)));"
    return [
        f"{indent}/// @dev {kind.name.lower()} via PRBMath SD59x18.",
        f"{indent}function _{kind.name.lower()}({sig}) internal pure "
        f"override returns (int256) {{",
        f"{indent}{indent}{body}",
        f"{indent}}}",
    ]


def _render_trig_override(
    kind: NodeKind, *, fn_name: str, indent: str,
) -> list[str]:
    """Emit a single `override` function routed to TrigSD59x18."""
    return [
        f"{indent}/// @dev {kind.name.lower()} via TrigSD59x18 "
        f"(Taylor / PRBMath exp).",
        f"{indent}function _{kind.name.lower()}(int256 x) internal pure "
        f"override returns (int256) {{",
        f"{indent}{indent}return unwrap(TrigSD59x18.{fn_name}(sd(x)));",
        f"{indent}}}",
    ]
