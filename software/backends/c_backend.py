"""C99 backend -- emits standalone .c files using libmonogate.h.

Walks an EMLModule (already parsed + profiled) and produces a
self-contained C file that links against `software/runtime/c/libmonogate.h`.

Mapping
=======

  EML AST kind        →  C output
  ─────────────────────────────────
  LITERAL int         →  "42"
  LITERAL float       →  "42.0"
  LITERAL bool        →  "1" / "0"
  VAR                 →  identifier
  BINOP +/-/*//       →  C arithmetic
  BINOP comparisons   →  C comparison (yields int 0/1)
  BINOP &&/||         →  C boolean
  UNARYOP -           →  C unary minus
  UNARYOP !           →  C logical NOT
  EXP/LN/SIN/COS/...  →  mg_exp / mg_ln / mg_sin / ...
  EML(x, y)           →  mg_eml(x, y)
  POW(x, y)           →  mg_pow(x, y)
  CLAMP(x, lo, hi)    →  mg_clamp(x, lo, hi)
  CALL                →  user-function call (assumed already emitted)
  TUPLE(a, b)         →  struct literal -- only valid in return position
  LET name = expr     →  "double name = <expr>;"
  LET_MUT name = expr →  "double name = <expr>;"  (C has no const distinction)
  ASSIGN name = expr  →  "name = <expr>;"
  WHILE cond block    →  "while (<cond>) { <block> }"
  EXPR_STMT           →  "<expr>;"
  BLOCK               →  brace-enclosed sequence; final expr is `return <expr>;`

Tuple-return functions
======================

For `fn park(...) -> (f64, f64)` we synthesize a struct type
`park_result_t { double e0; double e1; }` at the top of the file
and the function returns that struct. Tuple literal `(v_d, v_q)`
becomes `(park_result_t){v_d, v_q}`.

Phase E.3: refinement-aware lowering.
  - `requires` clauses lower to `assert(cond && "msg")` guards.
  - Refined parameters lower to `assert(cond && "msg")` guards BEFORE requires.
  - `#include <assert.h>` is injected into the file header IFF at least one
    function in the module has requires clauses or refined parameters.
    Clean kernels (neither) are byte-identical to pre-E.3 output.
  - ABS maps to mg_abs (via the existing _BUILTIN_TO_C table), consistent
    with the rest of the C backend's libmonogate dispatch.

Reference: lang/spec/EML_LANG_DESIGN.md section 2.1.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Builtin NodeKind -> libmonogate function name.
_BUILTIN_TO_C: dict[NodeKind, str] = {
    NodeKind.EXP:   "mg_exp",
    NodeKind.LN:    "mg_ln",
    NodeKind.SIN:   "mg_sin",
    NodeKind.COS:   "mg_cos",
    NodeKind.TAN:   "mg_tan",
    NodeKind.SQRT:  "mg_sqrt",
    NodeKind.ABS:   "mg_abs",
    NodeKind.ASIN:  "mg_asin",
    NodeKind.ACOS:  "mg_acos",
    NodeKind.ATAN:  "mg_atan",
    NodeKind.SINH:  "mg_sinh",
    NodeKind.COSH:  "mg_cosh",
    NodeKind.TANH:  "mg_tanh",
    NodeKind.POW:   "mg_pow",
    NodeKind.EML:   "mg_eml",
    NodeKind.CLAMP: "mg_clamp",
}

# When the optimizer marks a function `drift_risk=HIGH`, these
# NodeKinds dispatch to libmonogate's SuperBEST routing variants
# instead of the naive form. Picks the canonical sub-domain form
# (Padé near zero, sign() at saturation, etc.) -- Patent #01.
_BUILTIN_TO_C_HIGH_DRIFT: dict[NodeKind, str] = {
    NodeKind.TANH: "mg_tanh_route",
}


# Map EML-lang type names to C types. Anything not in this map
# (i.e. a user-declared alias or a custom type) defaults to `double`
# since EML-lang's numeric domain is real-valued.
_TYPE_TO_C: dict[str, str] = {
    "Real":  "double",
    "f64":   "double",
    "f32":   "float",
    "f16":   "float",   # C99 has no native fp16 -- promote
    "bf16":  "float",   # likewise
    "u8":    "uint8_t",
    "u16":   "uint16_t",
    "u32":   "uint32_t",
    "u64":   "uint64_t",
    "i8":    "int8_t",
    "i16":   "int16_t",
    "i32":   "int32_t",
    "i64":   "int64_t",
    "bool":  "int",     # C99 has _Bool but `int` keeps it simple
    "void":  "void",
}


def _c_type(eml_type: str) -> str:
    """Translate an EML-lang type name to a C type. Aliases default
    to `double` since chain-order constraints don't change the
    runtime numeric type."""
    return _TYPE_TO_C.get(eml_type, "double")


# ── Phase E.3: refinement guard helpers ──────────────────────────────────────


def _substitute_var(node: ASTNode, old: str, new: str) -> ASTNode:
    """Return a new ASTNode tree with every VAR named *old* replaced by *new*.

    Immutable: the original tree is never modified.
    """
    if node.kind == NodeKind.VAR and node.value == old:
        return ASTNode(
            kind=NodeKind.VAR, value=new, children=[],
            type_annotation=node.type_annotation,
            chain_constraint=node.chain_constraint,
            line=node.line, col=node.col,
        )
    new_children = [_substitute_var(c, old, new) for c in node.children]
    return ASTNode(
        kind=node.kind, value=node.value, children=new_children,
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line, col=node.col,
    )


def _var_names(node: ASTNode) -> set[str]:
    """Collect every VAR name that appears anywhere in *node*."""
    names: set[str] = set()
    if node.kind == NodeKind.VAR:
        names.add(str(node.value))
    for c in node.children:
        names.update(_var_names(c))
    return names


def _module_needs_assert(funcs: list) -> bool:
    """Return True iff any function in the module has requires clauses or
    refined parameters -- triggering #include <assert.h> injection."""
    for fn in funcs:
        if fn.requires:
            return True
        for p in fn.params:
            if p.refinement is not None:
                return True
    return False


class CompileError(Exception):
    """Raised on something the C backend genuinely cannot translate
    (e.g. a NodeKind it doesn't recognize)."""


class CBackend:
    """Compile an EMLModule to C99 source."""

    name = "c"

    def __init__(self, indent: str = "    ", *, optimize: bool = True):
        self.indent = indent
        self.optimize = optimize
        # Per-function drift level set during _emit_function.
        # "HIGH" routes drift-prone ops (tanh) to mg_*_route variants.
        self._drift_risk: str = "LOW"

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule) -> str:
        """Return the full C source as a string.

        When `optimize=True` (the default), the input module is
        passed through `optimize_module()` first so constant-folded
        expressions and CSE'd let-bindings appear in the emitted C."""
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)
        lines: list[str] = [
            "/*",
            f" * Generated by EML-lang C backend",
            f" * Source module: {mod.name or '(unnamed)'}",
            f" * Source file:   {mod.source_file}",
            f" * Functions:     {len(mod.functions)}",
            f" * Constants:     {len(mod.constants)}",
            f" * Types:         {len(mod.types)}",
            " */",
            "",
            '#include "libmonogate.h"',
            "#include <stdint.h>",
            "#include <math.h>",
        ]
        # Phase E.3: inject assert.h only when the module has requires
        # clauses or refined parameters -- keeps clean kernels byte-identical.
        if _module_needs_assert(mod.functions):
            lines.append("#include <assert.h>")
        lines.append("")
        # Tuple-return struct types come before any function signature.
        struct_decls = self._emit_tuple_structs(mod.functions)
        if struct_decls:
            lines.extend(struct_decls)
            lines.append("")

        # Module-level constants.
        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Functions.
        for fn in mod.functions:
            lines.extend(self._emit_function(fn))
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    # ── Tuple struct types ────────────────────────────────────

    def _emit_tuple_structs(self, funcs: list[EMLFunction]) -> list[str]:
        out: list[str] = []
        for fn in funcs:
            if not fn.return_tuple_types:
                continue
            type_name = self._tuple_type_name(fn.name)
            fields = "; ".join(
                f"{_c_type(t)} e{i}"
                for i, t in enumerate(fn.return_tuple_types)
            )
            out.append(f"typedef struct {{ {fields}; }} {type_name};")
        return out

    @staticmethod
    def _tuple_type_name(fn_name: str) -> str:
        return f"{fn_name}_result_t"

    # ── Constants + functions ─────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        return [
            f"static const {_c_type(c.type_name)} {c.name} = "
            f"{self._emit_expr(c.value)};"
        ]

    # ── Phase E.3: refinement guards ─────────────────────────────

    def _emit_refinement_guards(self, fn: EMLFunction) -> list[str]:
        """Return one assert() line per refined parameter (Phase E.3).

        C idiom: assert(cond && "message") -- the string literal is
        non-NULL so `&& "msg"` is always truthy; it merely embeds the
        message in the assertion failure output via assert's __FILE__/
        __LINE__ machinery.

        Cross-param refinements emit a comment-only obligation line.
        """
        out: list[str] = []
        param_names = {p.name for p in fn.params}
        for p in fn.params:
            if p.refinement is None:
                continue
            ref = p.refinement
            pred = _substitute_var(ref.predicate, ref.binder, p.name)
            pred_vars = _var_names(pred)
            other_params_in_pred = (pred_vars - {p.name}) & param_names
            if other_params_in_pred:
                try:
                    cond_str = self._emit_expr(pred)
                except CompileError as e:
                    cond_str = f"<unsupported: {e}>"
                out.append(
                    f"{self.indent}/* refinement obligation: "
                    f"{fn.name}: {p.name}: {cond_str} */"
                )
                continue
            try:
                cond = self._emit_expr(pred)
                msg = f"{fn.name}: refinement violated on {p.name}: {cond}"
                out.append(
                    f'{self.indent}assert(({cond}) && "{msg}");'
                )
            except CompileError as e:
                out.append(
                    f"{self.indent}/* refinement: unsupported ({e}) */"
                )
        return out

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        # Record drift risk so _emit_expr can route TANH (and any
        # future drift-prone NodeKind) to the libmonogate _route variant.
        self._drift_risk = (
            (fn.profile or {}).get("fp16_drift_risk", "LOW") or "LOW"
        )

        # Extern fns are forward declarations -- the implementation
        # is provided by some other compilation unit (libmonogate, a
        # vendor lib, hand-written C).
        if fn.is_extern:
            if fn.return_tuple_types:
                ret_type = self._tuple_type_name(fn.name)
            else:
                ret_type = _c_type(fn.return_type or "Real")
            params_c = ", ".join(
                f"{_c_type(p.type_name)} {p.name}" for p in fn.params
            ) or "void"
            return [
                f"/* extern: {fn.name} -- declaration only, "
                f"implementation provided externally */",
                f"extern {ret_type} {fn.name}({params_c});",
            ]

        out: list[str] = self._profile_comment(fn)

        # Signature
        if fn.return_tuple_types:
            ret_type = self._tuple_type_name(fn.name)
        else:
            ret_type = _c_type(fn.return_type or "Real")
        params_c = ", ".join(
            f"{_c_type(p.type_name)} {p.name}" for p in fn.params
        ) or "void"
        out.append(f"{ret_type} {fn.name}({params_c}) {{")

        # Phase E.3: refinement-derived guards fire BEFORE requires guards.
        out.extend(self._emit_refinement_guards(fn))

        # `requires` lower to assert(cond && "msg") guards.
        for r in fn.requires:
            try:
                cond = self._emit_expr(r)
                out.append(
                    f'{self.indent}assert(({cond}) && "{fn.name}: requires ({cond})");'
                )
            except CompileError as e:
                out.append(f"{self.indent}/* requires: unsupported ({e}) */")

        # Phase G: `assume` clauses -- trusted hypotheses, zero runtime cost.
        # Emit as comment-only; no assert() guard is generated.
        for a in fn.assumes:
            try:
                pred = self._emit_expr(a)
                out.append(f"{self.indent}/* assume: {pred} */")
            except CompileError as e:
                out.append(f"{self.indent}/* assume: unsupported ({e}) */")

        # Body -- pass the struct name when returning a tuple so the
        # final expression gets the C99 cast `(name){...}`.
        struct_name = (
            self._tuple_type_name(fn.name) if fn.return_tuple_types else None
        )
        body_lines = self._emit_block(
            fn.body, return_value=True, tuple_struct=struct_name,
        )
        for ln in body_lines:
            out.append(self.indent + ln)
        out.append("}")
        return out

    def _profile_comment(self, fn: EMLFunction) -> list[str]:
        if fn.profile is None:
            return [
                f"/* {fn.name}: no profile available "
                f"-- run Profiler.profile_module() first */",
            ]
        p = fn.profile
        status = p.get("status", "?")
        if status == "complex_body":
            return [
                f"/*",
                f" * {fn.name} -- COMPLEX BODY (Phase 2 will analyze)",
                f" * note: {p.get('note', '')}",
                f" */",
            ]
        cc = p.get("cost_class", "?")
        co = p.get("chain_order", "?")
        depth = p.get("eml_depth", "?")
        dyn = p.get("dynamics", {})
        fp = p.get("fpga_estimate", {})
        drift = p.get("fp16_drift_risk", "?")
        warns = p.get("stability_warnings", [])
        lines = [
            "/*",
            f" * {fn.name}",
            f" * Chain order: {co}     Cost class: {cc}",
            f" * EML depth:   {depth}  Drift risk: {drift}",
        ]
        if dyn:
            lines.append(
                f" * Dynamics:    {dyn.get('oscillations', 0)} osc, "
                f"{dyn.get('decays', 0)} decay  "
                f"(predicted_r={dyn.get('predicted_r', 0)})"
            )
        if fp:
            lines.append(
                f" * FPGA est:   {fp.get('mac_units', 0)} MAC, "
                f"{fp.get('exp_units', 0)} exp, "
                f"{fp.get('ln_units', 0)} ln, "
                f"{fp.get('trig_units', 0)} trig "
                f"-> {fp.get('estimated_latency_cycles', 0)} cy "
                f"@ {fp.get('precision_bits_needed', 32)}-bit"
            )
        for w in warns:
            lines.append(f" * WARNING: {w}")
        lines.append(" */")
        return lines

    # ── Block / statement emission ────────────────────────────

    def _emit_block(
        self,
        block: ASTNode | None,
        *,
        return_value: bool,
        tuple_struct: str | None = None,
    ) -> list[str]:
        """Emit the statements of a BLOCK. When `return_value` is
        True (function body), the final expression becomes
        `return <expr>;`. When False (a while-loop body), it's
        treated as an expression-statement.

        When the function returns a tuple, `tuple_struct` carries
        the struct type name so a final TUPLE expression gets the
        C99 compound-literal cast `(<struct>){...}` prepended."""
        if block is None or block.kind != NodeKind.BLOCK:
            return ["/* empty block */"]
        out: list[str] = []
        for i, stmt in enumerate(block.children):
            is_last = (i == len(block.children) - 1)
            if stmt.kind == NodeKind.LET or stmt.kind == NodeKind.LET_MUT:
                ctype = _c_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{ctype} {stmt.value} = {rhs};")
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{stmt.value} = {rhs};")
            elif stmt.kind == NodeKind.WHILE:
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(stmt.children[1], return_value=False)
                out.append(f"while ({cond}) {{")
                for ln in inner:
                    out.append(self.indent + ln)
                out.append("}")
            elif stmt.kind == NodeKind.EXPR_STMT:
                expr = self._emit_expr(stmt.children[0])
                out.append(f"{expr};")
            elif is_last:
                # Final expression of the block.
                if (return_value
                        and stmt.kind == NodeKind.TUPLE
                        and tuple_struct is not None):
                    elems = ", ".join(
                        self._emit_expr(c) for c in stmt.children
                    )
                    out.append(f"return ({tuple_struct}){{{elems}}};")
                else:
                    expr = self._emit_expr(stmt)
                    out.append(
                        f"return {expr};" if return_value else f"{expr};"
                    )
            else:
                # Non-final non-statement node treated as expr-stmt.
                expr = self._emit_expr(stmt)
                out.append(f"{expr};")
        return out

    # ── Expression emission ───────────────────────────────────

    def _emit_expr(self, node: ASTNode) -> str:
        kind = node.kind

        if kind == NodeKind.LITERAL:
            v = node.value
            if isinstance(v, bool):
                return "1" if v else "0"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, float):
                # Preserve enough decimals for round-trip identity.
                s = repr(v)
                # repr(0.5) -> "0.5"; ensure we always look like a float
                if "." not in s and "e" not in s and "E" not in s:
                    s += ".0"
                return s
            raise CompileError(f"unsupported literal: {v!r}")

        if kind == NodeKind.VAR:
            return str(node.value)

        if kind == NodeKind.UNARYOP:
            sub = self._emit_expr(node.children[0])
            if node.value == "-":
                return f"(-{sub})"
            if node.value == "!":
                return f"(!{sub})"
            raise CompileError(f"unsupported unary op: {node.value!r}")

        if kind == NodeKind.BINOP:
            left = self._emit_expr(node.children[0])
            right = self._emit_expr(node.children[1])
            return f"({left} {node.value} {right})"

        if kind == NodeKind.TUPLE:
            # Tuple literals only make sense in return position; emit
            # as a struct compound-literal. The function this tuple
            # is returning from gives us the struct name. We don't
            # have access to it here, so emit a placeholder syntax
            # and rely on _emit_function to wrap if needed.
            elems = ", ".join(self._emit_expr(c) for c in node.children)
            # The return-statement emit path knows the struct name;
            # for bare tuple expressions outside return position,
            # the user needs to assign to a struct value explicitly.
            return f"{{{elems}}}"

        # Built-in function call -- dispatch to libmonogate.
        # Drift-prone ops route through mg_*_route on HIGH-drift fns.
        if kind in _BUILTIN_TO_C:
            args = ", ".join(self._emit_expr(c) for c in node.children)
            if self._drift_risk == "HIGH" and kind in _BUILTIN_TO_C_HIGH_DRIFT:
                return f"{_BUILTIN_TO_C_HIGH_DRIFT[kind]}({args})"
            return f"{_BUILTIN_TO_C[kind]}({args})"

        # User function call
        if kind == NodeKind.CALL:
            args = ", ".join(self._emit_expr(c) for c in node.children)
            return f"{node.value}({args})"

        raise CompileError(
            f"C backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
