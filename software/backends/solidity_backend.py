"""Solidity 0.8 backend.

Emits a single ``.sol`` file with one ``contract`` per EML module.
The contract is ``pure`` (no storage reads / writes) by default —
verified kernels become ``external pure`` entry points, helpers
become ``internal pure``, and module-level constants become
``int256 constant`` (or the matching integer width for typed
parameters).

Mapping
=======

  EML AST kind        →  Solidity output
  ─────────────────────────────────────
  module M            →  contract MPascalCase { ... }
  const K: T = lit    →  T constant K = lit;
  fn name(...) -> T   →  function nameCamel(...) external|internal pure returns (T)
  @verify(lean, t=X)  →  /// @notice Formal proof: X (MachLib)  +  external visibility
  requires expr       →  require(expr, "name: requires expr");
  ensures  expr       →  /// @dev ensures: expr   (NatSpec only;
                          Solidity has no postcondition syntax)
  let x = expr        →  T x = expr;
  while cond { ... }  →  while (cond) { ... }
  EXP/LN/SIN/COS/...  →  _exp(x), _ln(x), ...   (internal stubs that
                          REVERT by default; override with PRBMath
                          or your own fixed-point implementation —
                          see header for the override pattern)
  ABS(x)              →  _abs(x)
  POW(x, y)           →  _pow(x, y)
  CLAMP(x, lo, hi)    →  _clamp(x, lo, hi)      (internal helper
                          emitted only when needed, naive
                          ``a < b ? a : b`` style)
  EML(x, y)           →  (_exp(x) - _ln(y))

Real-number semantics
=====================

EML ``Real`` (and the floating-point aliases ``f64``/``f32``/...) all
map to ``int256``. There is **no implicit WAD scaling** — literals
emit as their natural integer value. For an integer-coordinated
kernel (PID with gains scaled to integers, e.g. Kp=2.5 represented
as the constant ``250`` and divided back by ``100``) the emitted
contract is correct and deployable as-is.

For kernels that use transcendentals (``exp``/``ln``/``sin``/``cos``/...)
the emitted ``_exp(x)``/``_ln(x)``/... calls reach for the contract's
internal stubs, which REVERT by default. To make the contract
deployable, derive a child contract that overrides the stubs:

    import "@prb/math/src/SD59x18.sol";
    contract MyKernelImpl is GeneratedKernel {
        using SD59x18 for int256;
        function _exp(int256 x) internal pure override returns (int256) {
            return x.exp();
        }
        // ... etc for _ln, _sin, _cos
    }

This keeps the generated contract library-free (no PRBMath import
in the codegen output) while making the override path one obvious
inheritance away.

Reference: lang/spec/EML_LANG_DESIGN.md + Phase 4 backend roadmap;
SOL-001 session 2026-05-01.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Builtin NodeKind -> Solidity internal-helper function name. The
# helpers themselves are emitted as `revert` stubs at the bottom of
# the contract so the file always compiles; the user overrides them
# in a derived contract with PRBMath or a custom implementation.
_BUILTIN_TO_SOLIDITY: dict[NodeKind, str] = {
    NodeKind.EXP:   "_exp",
    NodeKind.LN:    "_ln",
    NodeKind.SIN:   "_sin",
    NodeKind.COS:   "_cos",
    NodeKind.TAN:   "_tan",
    NodeKind.SQRT:  "_sqrt",
    NodeKind.ABS:   "_abs",
    NodeKind.ASIN:  "_asin",
    NodeKind.ACOS:  "_acos",
    NodeKind.ATAN:  "_atan",
    NodeKind.SINH:  "_sinh",
    NodeKind.COSH:  "_cosh",
    NodeKind.TANH:  "_tanh",
    NodeKind.POW:   "_pow",
}


# EML type → Solidity type. All Real-family types collapse to
# int256 (no implicit fixed-point scaling — see header).
_TYPE_TO_SOLIDITY: dict[str, str] = {
    "Real": "int256",
    "f64":  "int256",
    "f32":  "int256",
    "f16":  "int256",
    "bf16": "int256",
    "u8":   "uint8",
    "u16":  "uint16",
    "u32":  "uint32",
    "u64":  "uint64",
    "u128": "uint128",
    "u256": "uint256",
    "i8":   "int8",
    "i16":  "int16",
    "i32":  "int32",
    "i64":  "int64",
    "i128": "int128",
    "i256": "int256",
    "Int":  "int256",
    "Nat":  "uint256",
    "bool": "bool",
}


def _sol_type(eml_type: str) -> str:
    return _TYPE_TO_SOLIDITY.get(eml_type, "int256")


def _to_camel(snake: str) -> str:
    """Convert snake_case to camelCase (Solidity convention for
    function and parameter names). The first segment stays
    lowercase; subsequent segments are title-cased."""
    parts = snake.split("_")
    if not parts:
        return snake
    return parts[0] + "".join(p.title() for p in parts[1:])


def _to_pascal(snake: str) -> str:
    """Convert snake_case to PascalCase (Solidity convention for
    contract names)."""
    return "".join(p.title() for p in snake.split("_") if p)


def _contract_name(mod: EMLModule) -> str:
    base = mod.name or "ForgeKernel"
    return _to_pascal(base) or "ForgeKernel"


class CompileError(Exception):
    """Raised on a NodeKind the Solidity backend doesn't recognize."""


class SolidityBackend:
    """Compile an EMLModule to a single Solidity source file."""

    name = "solidity"

    def __init__(
        self,
        indent: str = "    ",
        *,
        optimize: bool = True,
        gas_estimate: bool = True,
    ):
        # Solidity convention: 4-space indent (per the official style
        # guide). solc itself doesn't care about whitespace.
        self.indent = indent
        self.optimize = optimize
        # NatSpec @dev gas annotation. On by default -- the estimate
        # is cheap and the audit-trail value is high. Toggle off
        # when round-tripping through the formatter or for diff
        # tests that should be insensitive to the gas table.
        self.gas_estimate = gas_estimate
        # Track which builtin helpers a module actually invokes so
        # we can emit only the stubs that are referenced. Populated
        # by _emit_expr; flushed in compile().
        self._used_builtins: set[NodeKind] = set()
        # Did any call site reach for CLAMP? Emitted as a separate
        # internal helper if so (concrete impl, not a stub).
        self._used_clamp: bool = False
        # Number of fractional float literals that got rounded to
        # int. Surfaced as a top-of-file warning so users with
        # fixed-point kernels know the rounded values are nonsense
        # without WAD scaling + a PRBMath override.
        self._fractional_rounded: int = 0

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        # Reset per-compile state (the same backend instance may be
        # reused across modules in tests / batch CLI runs).
        self._used_builtins = set()
        self._used_clamp = False
        self._fractional_rounded = 0

        contract = _contract_name(mod)
        verified_names = {
            f.name for f in mod.functions
            if any(self._is_lean_verify(a) for a in f.annotations)
        }

        # Render bodies first so `_used_builtins` is populated by the
        # time we know which stubs to emit.
        body_lines: list[str] = []
        for c in mod.constants:
            body_lines.extend(self._emit_constant(c))
        if mod.constants:
            body_lines.append("")
        for fn in mod.functions:
            body_lines.extend(
                self._emit_function(fn, is_verified=fn.name in verified_names)
            )
            body_lines.append("")

        if self._used_clamp:
            body_lines.extend(self._emit_clamp_helper())
            body_lines.append("")

        for kind in sorted(self._used_builtins, key=lambda k: k.name):
            body_lines.extend(self._emit_builtin_stub(kind))
            body_lines.append("")

        # Header. Stays intentionally library-free; the override
        # pattern in a derived contract is the integration point.
        header: list[str] = [
            "// SPDX-License-Identifier: MIT",
            "// Generated by EML-lang Solidity backend",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {mod.source_file}",
            f"// Functions:     {len(mod.functions)} "
            f"({len(verified_names)} @verify-annotated)",
            f"// Constants:     {len(mod.constants)}",
        ]
        if self._used_builtins:
            header.append(
                f"// Transcendental stubs: "
                f"{', '.join(sorted(b.name.lower() for b in self._used_builtins))} "
                f"-- override in a derived contract (see PRBMath SD59x18)"
            )
        if self._fractional_rounded > 0:
            header.extend([
                f"// WARNING: {self._fractional_rounded} fractional Real "
                f"literal(s) were rounded to int256 (e.g. 0.6108 -> 1).",
                "// For fixed-point semantics, scale your EML constants",
                "// by WAD (1e18) and override the transcendental stubs",
                "// with PRBMath SD59x18 in a derived contract.",
            ])
        header.extend([
            "",
            "pragma solidity ^0.8.20;",
            "",
            f"contract {contract} {{",
        ])

        # Indent body.
        indented = [self.indent + ln if ln else "" for ln in body_lines]

        full = "\n".join(header + indented + ["}"])
        return full.rstrip() + "\n"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        sol_type = _sol_type(c.type_name)
        try:
            rhs = self._emit_expr(c.value)
        except CompileError as e:
            return [f"// const {c.name}: unsupported value ({e})"]
        # Solidity contract-level constants must be of value type and
        # initialised with a constant expression. Literals always
        # qualify; composed expressions usually do too (the optimiser
        # has already folded what it can).
        return [f"{sol_type} constant {c.name} = {rhs};"]

    # ── Functions ─────────────────────────────────────────────

    def _emit_function(
        self, fn: EMLFunction, *, is_verified: bool,
    ) -> list[str]:
        out: list[str] = self._doc(fn, is_verified=is_verified)
        # Return type: scalar -> "int256"; tuple -> "(int256, int256, ...)".
        # Solidity supports tuple returns natively.
        if fn.return_tuple_types:
            ret_inner = ", ".join(
                _sol_type(t) for t in fn.return_tuple_types
            )
            ret = f"({ret_inner})"
        else:
            ret = _sol_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_sol_type(p.type_name)} {_to_camel(p.name)}"
            for p in fn.params
        )
        # @verify-annotated functions are entry points -> external.
        # Helpers stay internal so derived contracts can use them
        # without exposing them on the contract ABI.
        visibility = "external" if is_verified else "internal"
        sig_name = _to_camel(fn.name)
        out.append(
            f"function {sig_name}({params}) {visibility} pure "
            f"returns ({ret}) {{"
        )

        # `requires` lower to runtime guards via require(). Solidity's
        # require() takes an optional revert string -- we synthesise
        # one from the kernel name + condition for debugging.
        for r in fn.requires:
            try:
                cond = self._emit_expr(r)
                # Truncate long messages -- Solidity revert strings
                # cost gas per byte and the EVM caps practical use.
                msg = f"{fn.name}: requires {cond}"
                if len(msg) > 100:
                    msg = msg[:97] + "..."
                # Escape any embedded double quotes.
                msg_safe = msg.replace('"', '\\"')
                out.append(
                    f'{self.indent}require({cond}, "{msg_safe}");'
                )
            except CompileError as e:
                out.append(f"{self.indent}// require: unsupported ({e})")

        body = self._emit_block(fn.body, return_value=True)
        for ln in body:
            out.append(self.indent + ln)
        out.append("}")
        return out

    # ── Doc comment (NatSpec) ─────────────────────────────────

    def _doc(self, fn: EMLFunction, *, is_verified: bool) -> list[str]:
        out: list[str] = []
        # Top NatSpec line: function name + verified marker.
        if is_verified:
            verify_annot = next(
                (a for a in fn.annotations if self._is_lean_verify(a)),
                None,
            )
            theorem = (
                verify_annot.args.get("theorem", fn.name)
                if verify_annot else fn.name
            )
            out.append(
                f"/// @notice Formal proof: {theorem} (MachLib). "
                f"Compiled from EML-lang."
            )
        else:
            out.append(f"/// @notice {fn.name} -- compiled from EML-lang.")

        # Pfaffian profile (chain order, drift risk).
        if fn.profile is not None and fn.profile.get("status") != "complex_body":
            cc = fn.profile.get("cost_class", "?")
            co = fn.profile.get("chain_order", "?")
            drift = fn.profile.get("fp16_drift_risk", "?")
            out.append(
                f"/// @dev Pfaffian profile: chain_order={co}, "
                f"cost_class={cc}, drift_risk={drift}."
            )

        # Gas estimate sourced from solidity_gas.estimate_function_gas.
        # Numbers assume PRBMath SD59x18 overrides for transcendentals
        # (the default emitted stubs revert). Surfaced as a NatSpec
        # @dev line so auditors and devs see an order-of-magnitude
        # cost without running a Foundry gas-bench.
        if self.gas_estimate and fn.body is not None:
            from software.backends.solidity_gas import (
                estimate_function_gas, format_gas_estimate,
            )
            gas = estimate_function_gas(fn)
            out.append(
                f"/// @dev Gas estimate: {format_gas_estimate(gas)} "
                f"(PRBMath SD59x18 overrides assumed; run forge gas-bench "
                f"for the canonical signal)."
            )
        # @param lines for each parameter.
        for p in fn.params:
            out.append(
                f"/// @param {_to_camel(p.name)} {p.name} "
                f"({_sol_type(p.type_name)})"
            )
        # ensures clauses surface as @dev annotations (Solidity has
        # no postcondition syntax; assert() is wrong here because it
        # consumes all gas).
        for r in fn.ensures:
            try:
                out.append(
                    f"/// @dev ensures: {self._emit_expr(r, result_subst='result')}"
                )
            except CompileError:
                pass
        return out

    # ── Statements ────────────────────────────────────────────

    def _emit_block(
        self,
        block: ASTNode | None,
        *,
        return_value: bool,
    ) -> list[str]:
        if block is None or block.kind != NodeKind.BLOCK:
            return ["// empty body"]
        out: list[str] = []
        for i, stmt in enumerate(block.children):
            is_last = (i == len(block.children) - 1)
            if stmt.kind in (NodeKind.LET, NodeKind.LET_MUT):
                # EML `let x = expr` -> Solidity `int256 x = expr;`.
                # We don't track the EML let-type explicitly so we
                # fall back to int256 (the Real default).
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"int256 {_to_camel(str(stmt.value))} = {rhs};")
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{_to_camel(str(stmt.value))} = {rhs};")
            elif stmt.kind == NodeKind.WHILE:
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(stmt.children[1], return_value=False)
                out.append(f"while ({cond}) {{")
                for ln in inner:
                    out.append(self.indent + ln)
                out.append("}")
            elif stmt.kind == NodeKind.EXPR_STMT:
                out.append(f"{self._emit_expr(stmt.children[0])};")
            elif is_last and return_value:
                out.append(f"return {self._emit_expr(stmt)};")
            else:
                out.append(f"{self._emit_expr(stmt)};")
        return out

    # ── Expressions ───────────────────────────────────────────

    def _emit_expr(
        self,
        node: ASTNode,
        *,
        result_subst: str | None = None,
    ) -> str:
        kind = node.kind

        if kind == NodeKind.LITERAL:
            v = node.value
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, float):
                # Solidity has no float literal. Two paths:
                #   - whole-number floats (3.0, 100.0) -> emit as int
                #   - fractional floats (0.5, 17.27)   -> ROUND to int
                #     and warn in a comment. Integer-coordinated
                #     kernels emit clean code; fractional Real kernels
                #     should be redesigned around fixed-point literals
                #     OR the contract should be deployed against a
                #     PRBMath-overriding child (see header).
                if v.is_integer():
                    return str(int(v))
                # Fractional literal — preserve precision via a comment
                # showing the original float, emit the rounded int.
                # Bumps a counter so the file header can warn once.
                rounded = int(round(v))
                self._fractional_rounded += 1
                return f"{rounded} /* {v!r} rounded; see header re fixed-point */"
            raise CompileError(f"unsupported literal: {v!r}")

        if kind == NodeKind.VAR:
            name = str(node.value)
            if result_subst is not None and name == "result":
                return result_subst
            # Constants stay SCREAMING_SNAKE; everything else camels.
            if name.isupper() or "_" in name and name.replace("_", "").isupper():
                return name
            return _to_camel(name)

        if kind == NodeKind.UNARYOP:
            sub = self._emit_expr(node.children[0], result_subst=result_subst)
            if node.value == "-":
                return f"(-{sub})"
            if node.value == "!":
                return f"(!{sub})"
            raise CompileError(f"unsupported unary op: {node.value!r}")

        if kind == NodeKind.BINOP:
            left = self._emit_expr(node.children[0], result_subst=result_subst)
            right = self._emit_expr(node.children[1], result_subst=result_subst)
            op = node.value
            # EML `&&`/`||` map directly to Solidity `&&`/`||`.
            return f"({left} {op} {right})"

        if kind == NodeKind.TUPLE:
            # Solidity has native tuple expressions: (a, b, c).
            # Used in return position for tuple-returning functions.
            elems = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"({elems})"

        if kind == NodeKind.CLAMP:
            self._used_clamp = True
            x, lo, hi = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"_clamp({x}, {lo}, {hi})"

        if kind == NodeKind.EML:
            # eml(x, y) = exp(x) - log(y).
            self._used_builtins.add(NodeKind.EXP)
            self._used_builtins.add(NodeKind.LN)
            x, y = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"(_exp({x}) - _ln({y}))"

        if kind in _BUILTIN_TO_SOLIDITY:
            self._used_builtins.add(kind)
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_SOLIDITY[kind]}({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            # User-defined function calls -> camelCase the callee.
            return f"{_to_camel(str(node.value))}({args})"

        raise CompileError(
            f"Solidity backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )

    # ── Builtin helper stubs ──────────────────────────────────

    def _emit_builtin_stub(self, kind: NodeKind) -> list[str]:
        """Emit an internal `pure virtual` helper that reverts. The
        derived contract overrides these with real fixed-point math
        (typically PRBMath SD59x18). Emitted only for builtins the
        kernel actually references."""
        name = _BUILTIN_TO_SOLIDITY[kind]
        # POW is the only 2-arg builtin we currently emit.
        if kind == NodeKind.POW:
            sig = "int256 base, int256 exp_"
            args_doc = "base, exp_"
        else:
            sig = "int256 x"
            args_doc = "x"
        msg = (
            f"{name}: stub — override in a derived contract "
            f"(see PRBMath SD59x18.{kind.name.lower()})"
        )
        return [
            f"/// @dev {kind.name.lower()} stub — override with a "
            f"fixed-point implementation.",
            f"function {name}({sig}) internal pure virtual returns (int256) {{",
            f"{self.indent}{args_doc}; // silence unused-param warning",
            f'{self.indent}revert("{msg}");',
            f"}}",
        ]

    def _emit_clamp_helper(self) -> list[str]:
        """Emit an int256 clamp(x, lo, hi). Concrete (not virtual);
        overflow/underflow checks come from Solidity 0.8 default
        arithmetic."""
        return [
            f"/// @dev clamp helper -- min(max(x, lo), hi).",
            f"function _clamp(int256 x, int256 lo, int256 hi) internal pure returns (int256) {{",
            f"{self.indent}if (x < lo) return lo;",
            f"{self.indent}if (x > hi) return hi;",
            f"{self.indent}return x;",
            f"}}",
        ]

    # ── Annotation helpers ────────────────────────────────────

    @staticmethod
    def _is_lean_verify(a: Annotation) -> bool:
        # Mirrors LeanBackend._is_lean_verify -- the EML annotation
        # is `@verify(lean, theorem = "X")` so the first positional
        # arg (key 0 in the args dict) carries the verifier name.
        if a.kind != "verify":
            return False
        return a.args.get(0) == "lean"
