"""WGSL (WebGPU Shading Language) backend.

Emits a single ``.wgsl`` file with one function per EML function and
no shader entry point. The output is a function library to be
included in a vertex / fragment / compute / mesh shader at the
caller's discretion.

WGSL is the shader language for WebGPU and is replacing GLSL in
browsers. Syntax is Rust-like (``fn``, ``let``, ``var``, return-arrow
return types). The backend serves both browser-gaming use cases and
non-gaming GPU compute -- scientific visualization, ML inference,
real-time audio.

Float32-only (every WebGPU implementation has f32; f16 is an
optional extension). EML ``Real`` and ``f64`` lower to WGSL ``f32``
with a header warning. A drift-risk comment is emitted above any
function whose chain order is >= 2 OR whose drift_risk is HIGH.

Mapping
=======

  EML AST kind        ->  WGSL output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0" (no suffix; AbstractFloat -> f32)
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier (snake_case preserved)
  BINOP +/-/*//       ->  arithmetic
  BINOP &&/||         ->  && / ||
  UNARYOP -           ->  unary minus
  UNARYOP !           ->  !
  EXP/LN/SIN/COS/...  ->  exp/log/sin/cos/...    (built-ins; log
                          is natural log)
  ABS(x)              ->  abs(x)
  CLAMP(x, lo, hi)    ->  clamp(x, lo, hi)
  POW(x, y)           ->  pow(x, y)
  CALL                ->  forward function call
  TUPLE return        ->  struct FooResult { e0: f32, e1: f32 }
  LET name = expr     ->  "let name: <type> = <expr>;"
  LET_MUT name = expr ->  "var name: <type> = <expr>;"  (var = mut)
  ASSIGN name = expr  ->  "name = <expr>;"
  WHILE cond block    ->  loop { if (!cond) { break; } <block> }
                          (WGSL has no `while`; the loop+break form
                          is the standard idiom.)
  BLOCK               ->  brace block; final expr -> return
  requires            ->  // forge.requires comment (advisory)
  ensures             ->  // forge.ensures comment (advisory)
  @verify(lean, ...)  ->  // forge.verify lean theorem=...

The output has no entry point. Validate with:

    naga path/to/output.wgsl

(or ship through wgpu's ShaderModuleDescriptor at runtime; the
WebGPU shader compiler runs the same naga frontend.)

Reference: https://www.w3.org/TR/WGSL/
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Builtin NodeKind -> WGSL built-in function name. WGSL math
# built-ins follow the GLSL/HLSL naming (lowercase, no namespace).
_BUILTIN_TO_WGSL: dict[NodeKind, str] = {
    NodeKind.EXP:   "exp",
    NodeKind.LN:    "log",      # WGSL `log` is natural log (base-e)
    NodeKind.SIN:   "sin",
    NodeKind.COS:   "cos",
    NodeKind.TAN:   "tan",
    NodeKind.SQRT:  "sqrt",
    NodeKind.ABS:   "abs",
    NodeKind.ASIN:  "asin",
    NodeKind.ACOS:  "acos",
    NodeKind.ATAN:  "atan",
    NodeKind.SINH:  "sinh",
    NodeKind.COSH:  "cosh",
    NodeKind.TANH:  "tanh",
    NodeKind.POW:   "pow",
}


# EML type -> WGSL type. Real/f64 -> f32 (WebGPU has no native f64).
_TYPE_TO_WGSL: dict[str, str] = {
    "Real":    "f32",
    "f64":     "f32",   # forced to f32 -- see header warning
    "f32":     "f32",
    "f16":     "f32",   # f16 is an extension; default to safe f32
    "bf16":    "f32",   # no bf16 in WGSL
    "u8":      "u32",
    "u16":     "u32",
    "u32":     "u32",
    "u64":     "u32",   # WGSL has no u64
    "i8":      "i32",
    "i16":     "i32",
    "i32":     "i32",
    "i64":     "i32",   # WGSL has no i64
    "bool":    "bool",
}


# Chain order >= this triggers the drift warning comment block. Same
# threshold as HLSL/GLSL -- chain 2+ in float32 is the precision-risk
# regime regardless of which shader language we lower to.
_DRIFT_WARN_CHAIN_FLOOR = 2


# WGSL reserved + built-in identifiers that frequently collide with
# EML variable / parameter names. WGSL's grammar reserves a large
# pool of words for forward compatibility (e.g. `enum`, `match`)
# even though the current spec doesn't use them. Pick the names
# that gaming / scientific kernels are likely to use.
_WGSL_RESERVED: frozenset[str] = frozenset({
    # Declaration / control flow keywords
    "fn", "let", "var", "const", "struct", "type", "alias",
    "return", "if", "else", "for", "while", "loop", "break",
    "continue", "discard", "switch", "case", "default", "fallthrough",
    # Address-space + access-mode words
    "private", "function", "workgroup", "uniform", "storage",
    "read", "write", "read_write", "handle",
    # Common type names
    "bool", "f16", "f32", "i32", "u32", "vec2", "vec3", "vec4",
    "mat2x2", "mat3x3", "mat4x4", "array", "atomic",
    "sampler", "sampler_comparison",
    "texture_1d", "texture_2d", "texture_3d", "texture_cube",
    # Reserved for forward compatibility
    "enum", "match", "do", "typedef", "static", "ref", "ptr",
    "true", "false", "NULL", "null",
    # Built-in numeric / vector functions that callers might use
    # as variable names. (These ARE valid identifiers in WGSL, but
    # shadowing a built-in is confusing and naga warns about it.)
    "step", "smoothstep", "mix", "fract", "sign", "clamp",
    "saturate", "transpose", "determinant", "normalize", "length",
    "cross", "dot", "select", "modf", "frexp", "ldexp",
})


# Call-target rewrites: SymPy / EML names -> WGSL built-ins or
# synthesized helpers. WGSL has the same trig / hyperbolic surface
# as GLSL, so most rewrites match those.
_CALL_REWRITE: dict[str, str] = {
    "exp10":  "_forge_exp10",   # WGSL has no exp10; synth helper
    "log10":  "_forge_log10",   # WGSL has no log10; synth helper
    "log2":   "log2",           # WGSL has log2 natively
    "exp2":   "exp2",           # WGSL has exp2 natively
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "asinh":  "asinh",
    "acosh":  "acosh",
    "atanh":  "atanh",
}


# Synthesized helper bodies. Emitted inline whenever a CALL
# targets the rewrite key.
_HELPERS_BY_REWRITE: dict[str, tuple[str, str]] = {
    "_forge_exp10": (
        "_forge_exp10",
        "// _forge_exp10 -- WGSL has no exp10 built-in; lower as 10^x.\n"
        "fn _forge_exp10(x: f32) -> f32 { return pow(10.0, x); }",
    ),
    "_forge_log10": (
        "_forge_log10",
        "// _forge_log10 -- WGSL has no log10 built-in; lower as ln(x)/ln(10).\n"
        "fn _forge_log10(x: f32) -> f32 { return log(x) / log(10.0); }",
    ),
}


def _safe_ident(name: str) -> str:
    """Rename an EML identifier when it collides with a WGSL
    reserved / built-in word."""
    if name in _WGSL_RESERVED:
        return name + "_"
    return name


# ── Phase E.2: refinement guard helpers ──────────────────────────────────────


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


def _wgsl_type(eml_type: str) -> str:
    return _TYPE_TO_WGSL.get(eml_type, "f32")


def _struct_name(fn_name: str) -> str:
    parts = fn_name.split("_")
    camel = "".join(p[:1].upper() + p[1:] for p in parts) or "Anon"
    return f"{camel}Result"


def _wants_drift_warning(profile: dict | None) -> tuple[bool, str]:
    if profile is None:
        return False, ""
    if profile.get("status") == "complex_body":
        return False, ""
    co = profile.get("chain_order")
    drift = profile.get("fp16_drift_risk", "LOW")
    if isinstance(co, int) and co >= _DRIFT_WARN_CHAIN_FLOOR:
        return True, f"chain_order={co} (>= {_DRIFT_WARN_CHAIN_FLOOR})"
    if drift in ("MEDIUM", "HIGH"):
        return True, f"drift_risk={drift}"
    return False, ""


class CompileError(Exception):
    """Raised on a NodeKind the WGSL backend doesn't recognize."""


class WGSLBackend:
    """Compile an EMLModule to a single .wgsl function-library file."""

    name = "wgsl"

    def __init__(self, indent: str = "    ", *, optimize: bool = True):
        self.indent = indent
        self.optimize = optimize

    def compile(self, mod: EMLModule) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        self._helpers_used: set[str] = set()
        self._in_module_names: set[str] = (
            {fn.name for fn in mod.functions}
            | {c.name for c in mod.constants}
        )

        any_drift = any(
            _wants_drift_warning(fn.profile)[0]
            for fn in mod.functions
            if not fn.is_extern
        )

        lines: list[str] = [
            "// Generated by EML-lang WGSL backend (function library)",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {mod.source_file}",
            f"// Functions:     {len(mod.functions)}",
            f"// Constants:     {len(mod.constants)}",
            "//",
            "// Float32-only. EML `Real` and `f64` lower to WGSL `f32`.",
            "// WebGPU has no native f64; f16 is an optional extension",
            "// (`enable f16;`). If you need >32-bit precision, do the",
            "// high-precision step on CPU and ship a float32 result.",
        ]
        if any_drift:
            lines.extend([
                "//",
                "// At least one function in this module has chain_order "
                f">= {_DRIFT_WARN_CHAIN_FLOOR}; per-function drift",
                "// warnings appear inline above each affected function.",
            ])
        lines.extend([
            "//",
            "// No entry point is provided; this is a function library.",
            "// Validate with `naga <output.wgsl>` or include in your own",
            "// vertex / fragment / compute shader and call from there.",
            "",
        ])

        # Tuple-return structs -- WGSL requires structs at module
        # scope, before first use.
        for fn in mod.functions:
            if fn.return_tuple_types:
                rec = _struct_name(fn.name)
                lines.append(f"struct {rec} {{")
                for i, t in enumerate(fn.return_tuple_types):
                    lines.append(f"{self.indent}e{i}: {_wgsl_type(t)},")
                lines.append("}")
                lines.append("")

        # Constants
        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Functions -- emit into a buffer first so we know which
        # synthesized helpers were referenced.
        fn_lines: list[str] = []
        for fn in mod.functions:
            if fn.is_extern:
                fn_lines.extend(self._emit_extern(fn))
            else:
                fn_lines.extend(self._emit_function(fn))
            fn_lines.append("")

        # Prepend synthesized helpers (if any). WGSL has no forward
        # declarations -- helper definitions must come before first use.
        for helper_key in sorted(self._helpers_used):
            _, src = _HELPERS_BY_REWRITE[helper_key]
            for ln in src.split("\n"):
                lines.append(ln)
            lines.append("")

        lines.extend(fn_lines)

        return "\n".join(lines).rstrip() + "\n"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        wgsl_type = _wgsl_type(c.type_name)
        rhs = self._emit_expr(c.value)
        return [f"const {_safe_ident(c.name)}: {wgsl_type} = {rhs};"]

    # ── Extern (FFI) ──────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _wgsl_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_safe_ident(p.name)}: {_wgsl_type(p.type_name)}"
            for p in fn.params
        )
        # WGSL has no extern; emit a placeholder body that returns
        # zero so a downstream caller still parses.
        zero = "0.0" if ret == "f32" else f"{ret}()"
        return [
            f"// extern: {fn.name} -- WGSL has no extern; replace the",
            f"// body before validating, or keep the stub for wiring.",
            f"fn {_safe_ident(fn.name)}({params}) -> {ret} {{",
            f"{self.indent}return {zero};",
            "}",
        ]

    # ── Function emit ─────────────────────────────────────────

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        out: list[str] = []
        emit_warn, why = _wants_drift_warning(fn.profile)
        out.extend(self._fn_header_comment(fn, emit_warn=emit_warn, why=why))

        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _wgsl_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_safe_ident(p.name)}: {_wgsl_type(p.type_name)}"
            for p in fn.params
        )

        out.append(f"fn {_safe_ident(fn.name)}({params}) -> {ret} {{")
        record = _struct_name(fn.name) if fn.return_tuple_types else None
        body = self._emit_block(
            fn.body, return_value=True, tuple_record=record,
        )
        for ln in body:
            out.append(self.indent + ln)
        out.append("}")
        return out

    # ── Phase E.2: refinement doc-comments (shader doc-only tier) ────

    def _emit_refinement_comments(self, fn: EMLFunction) -> list[str]:
        """Return one doc-comment line per refined parameter (Phase E.2).

        WGSL has no asserts; shader languages emit doc-comment obligations
        only. Binder-substitution mirrors the E.1 pattern.

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
                    f"//   refinement obligation: "
                    f"{fn.name}: {p.name}: {cond_str}"
                )
                continue
            try:
                cond = self._emit_expr(pred)
                msg = (
                    f"{fn.name}: refinement violated on {p.name}: {cond}"
                )
                out.append(f"//   forge.refinement: {msg}")
            except CompileError as e:
                out.append(
                    f"//   forge.refinement: unsupported ({e})"
                )
        return out

    def _fn_header_comment(
        self,
        fn: EMLFunction,
        *,
        emit_warn: bool,
        why: str,
    ) -> list[str]:
        out = [f"// {fn.name}"]
        if fn.profile is not None and fn.profile.get("status") != "complex_body":
            cc = fn.profile.get("cost_class", "?")
            co = fn.profile.get("chain_order", "?")
            drift = fn.profile.get("fp16_drift_risk", "?")
            out.append(
                f"//   Pfaffian profile: chain_order={co}, "
                f"cost_class={cc}, drift_risk={drift}."
            )
        if emit_warn:
            out.append(
                f"//   WARNING: float32 precision drift risk -- {why}."
            )
            out.append(
                "//   Consider doing the high-precision composition "
                "on CPU and"
            )
            out.append(
                "//   passing the float32 result into the shader."
            )
        # Phase E.2: refinement doc-comments (before existing requires)
        out.extend(self._emit_refinement_comments(fn))
        for r in fn.requires:
            try:
                out.append(f"//   forge.requires: {self._emit_expr(r)}")
            except CompileError:
                pass
        # Phase G: `assume` clauses -- trusted hypotheses, zero runtime cost.
        for a in fn.assumes:
            try:
                out.append(f"// assume: {self._emit_expr(a)}")
            except CompileError as e:
                out.append(f"// assume: unsupported ({e})")
        for r in fn.ensures:
            try:
                out.append(
                    f"//   forge.ensures: "
                    f"{self._emit_expr(r, result_subst='result')}"
                )
            except CompileError:
                pass
        for a in fn.annotations:
            if a.kind == "verify":
                tname = a.args.get("theorem", fn.name)
                out.append(f"//   forge.verify: lean theorem={tname}")
        return out

    # ── Statements ────────────────────────────────────────────

    def _emit_block(
        self,
        block: ASTNode | None,
        *,
        return_value: bool,
        tuple_record: str | None = None,
    ) -> list[str]:
        if block is None or block.kind != NodeKind.BLOCK:
            return ["// empty body"]
        out: list[str] = []
        for i, stmt in enumerate(block.children):
            is_last = (i == len(block.children) - 1)
            if stmt.kind == NodeKind.LET:
                wgsl_type = _wgsl_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"let {_safe_ident(str(stmt.value))}: {wgsl_type} = "
                    f"{rhs};"
                )
            elif stmt.kind == NodeKind.LET_MUT:
                wgsl_type = _wgsl_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"var {_safe_ident(str(stmt.value))}: {wgsl_type} = "
                    f"{rhs};"
                )
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{_safe_ident(str(stmt.value))} = {rhs};")
            elif stmt.kind == NodeKind.WHILE:
                # WGSL has no `while`. The standard rewrite:
                #   loop { if (!cond) { break; } <body> }
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(
                    stmt.children[1], return_value=False, tuple_record=None,
                )
                out.append("loop {")
                out.append(f"{self.indent}if (!({cond})) {{ break; }}")
                for ln in inner:
                    out.append(self.indent + ln)
                out.append("}")
            elif stmt.kind == NodeKind.EXPR_STMT:
                out.append(f"{self._emit_expr(stmt.children[0])};")
            elif (
                is_last and return_value
                and stmt.kind == NodeKind.TUPLE
                and tuple_record is not None
            ):
                # WGSL struct constructor: StructName(arg0, arg1, ...).
                elems = ", ".join(self._emit_expr(c) for c in stmt.children)
                out.append(f"return {tuple_record}({elems});")
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
                s = repr(v)
                if "." not in s and "e" not in s and "E" not in s:
                    s += ".0"
                # Plain decimal literal -- WGSL's AbstractFloat
                # concretises to f32 in f32 contexts. No suffix
                # needed (and `f` suffix only works in WGSL with
                # the float-suffixes proposal which isn't yet
                # in the spec).
                return s

        if kind == NodeKind.LITERAL:
            raise CompileError(f"unsupported literal: {node.value!r}")

        if kind == NodeKind.VAR:
            name = str(node.value)
            if result_subst is not None and name == "result":
                return result_subst
            return _safe_ident(name)

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
            return f"({left} {node.value} {right})"

        if kind == NodeKind.TUPLE:
            elems = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            raise CompileError(
                f"WGSL backend: tuple expression outside return needs "
                f"a generated struct (got {elems})"
            )

        if kind == NodeKind.CLAMP:
            x, lo, hi = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"clamp({x}, {lo}, {hi})"

        if kind == NodeKind.EML:
            x, y = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"(exp({x}) - log({y}))"

        if kind in _BUILTIN_TO_WGSL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_WGSL[kind]}({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            callee = str(node.value)
            rewritten = _CALL_REWRITE.get(callee)
            if rewritten is not None:
                if rewritten in _HELPERS_BY_REWRITE:
                    self._helpers_used.add(rewritten)
                return f"{rewritten}({args})"
            if callee in self._in_module_names:
                return f"{_safe_ident(callee)}({args})"
            return f"{callee}({args})"

        raise CompileError(
            f"WGSL backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
