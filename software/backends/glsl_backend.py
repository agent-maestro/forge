"""GLSL shader backend (function library, two flavors).

Emits a single ``.glsl`` (desktop) or ``.glsles`` (mobile / WebGL 2.0)
file with one function per EML function and no shader entry point.
The output is meant to be ``#include``-d into a vertex / fragment /
compute shader for Godot, OpenGL desktop, OpenGL ES, or WebGL 2.0.

Two flavors
===========

  ``flavor="desktop"`` -> ``#version 330 core`` (OpenGL 3.3+)
  ``flavor="es"``      -> ``#version 300 es`` + ``precision highp float;``

The desktop flavor is the natural choice for Godot 4 + OpenGL ES 3
fallback and any Linux / Mac / Windows OpenGL renderer. The es flavor
is what WebGL 2.0 + OpenGL ES 3.0 mobile devices speak; the precision
header is mandatory in ES.

Float32-only -- GLSL has no ``double`` outside GL 4.0 + the
``GL_ARB_gpu_shader_fp64`` extension, which is rare and not present
in GLSL 330 or GLSL ES 300.

Chain-order-aware drift warnings
================================

Same policy as the HLSL backend: any function whose Pfaffian
``chain_order >= 2`` OR whose ``drift_risk`` is MEDIUM/HIGH gets an
inline ``// WARNING: float32 precision drift risk`` comment block
above its definition. This is the same precision-risk regime as
HLSL since both languages target the same GPU hardware.

Mapping
=======

  EML AST kind        ->  GLSL output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0"   (no f-suffix -- portable across
                                     desktop 330 and ES 300)
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier (snake_case preserved)
  BINOP +/-/*//       ->  GLSL arithmetic
  BINOP comparisons   ->  GLSL comparison
  BINOP &&/||         ->  GLSL && / ||
  UNARYOP -/!         ->  GLSL unary minus / not
  EXP/LN/SIN/COS/...  ->  exp/log/sin/cos/...   (GLSL intrinsics --
                          same names as HLSL, no namespace prefix)
  ABS(x)              ->  abs(x)
  CLAMP(x, lo, hi)    ->  clamp(x, lo, hi)
                          (GLSL has no `saturate`; we never emit
                          it -- clamp(x,0,1) is the canonical form)
  POW(x, y)           ->  pow(x, y)
  EML(x, y)           ->  (exp(x) - log(y))
  CALL                ->  forward function call
  TUPLE return        ->  struct FooResult { float e0; float e1; ... }
  LET name = expr     ->  "<type> name = <expr>;"
  LET_MUT name = expr ->  "<type> name = <expr>;"
  ASSIGN name = expr  ->  "name = <expr>;"
  WHILE cond block    ->  while (<cond>) { <block> }
  BLOCK               ->  brace block; final expression -> return
  requires            ->  // forge.requires comment (advisory)
  ensures             ->  // forge.ensures comment (advisory)
  @verify(lean, ...)  ->  // forge.verify lean theorem=...

Notable differences from the HLSL backend
=========================================

  - No `static` qualifier on file-scope constants -- GLSL uses
    plain `const` (HLSL uses `static const`).
  - No `f` suffix on float literals -- portable across GLSL 330
    desktop and GLSL ES 300 (GLSL 4.0 with ARB_gpu_shader_fp64
    requires it but is rare).
  - GLSL has different reserved-word collisions; e.g. HLSL's
    `linear` interpolation modifier is not reserved in GLSL
    (GLSL uses `flat`/`smooth`/`noperspective`).
  - ES flavor adds a mandatory `precision highp float;` after the
    version directive.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Builtin NodeKind -> GLSL intrinsic name. All GLSL math intrinsics
# are lowercase, no namespace -- same as HLSL.
_BUILTIN_TO_GLSL: dict[NodeKind, str] = {
    NodeKind.EXP:   "exp",
    NodeKind.LN:    "log",       # GLSL `log` is natural log
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


# EML type -> GLSL type. Float32 only (GLSL has no widely-supported
# `double`; GL 4.0 + ARB_gpu_shader_fp64 is rare).
_TYPE_TO_GLSL: dict[str, str] = {
    "Real":    "float",
    "f64":     "float",   # forced to float32 -- see header note
    "f32":     "float",
    "f16":     "float",   # GLSL has no half/min16float -- promote
    "bf16":    "float",
    "u8":      "uint",
    "u16":     "uint",
    "u32":     "uint",
    "u64":     "uint",    # uint64 needs ARB_gpu_shader_int64 -- rare
    "i8":      "int",
    "i16":     "int",
    "i32":     "int",
    "i64":     "int",     # int64 needs ARB_gpu_shader_int64 -- rare
    "bool":    "bool",
}


# Chain order >= this triggers the drift warning comment block.
_DRIFT_WARN_CHAIN_FLOOR = 2


# GLSL reserved words / built-in names that may collide with EML
# identifiers. Keep the set conservative -- only words that are
# actual reserved keywords or commonly-used built-ins.
_GLSL_RESERVED: frozenset[str] = frozenset({
    # Storage / qualifier keywords
    "attribute", "varying", "uniform", "buffer", "shared", "coherent",
    "volatile", "restrict", "readonly", "writeonly",
    "in", "out", "inout", "centroid", "sample", "patch",
    "flat", "smooth", "noperspective", "invariant", "precise",
    "subroutine", "layout", "discard",
    # Precision qualifiers
    "precision", "highp", "mediump", "lowp",
    # Built-in functions (collide if used as VAR names)
    "mix", "smoothstep", "step", "fract", "sign", "length",
    "normalize", "dot", "cross", "reflect", "refract", "transpose",
    "determinant", "inverse", "outerProduct",
    "dFdx", "dFdy", "dFdxFine", "dFdyFine", "fwidth",
    "radians", "degrees", "atan2",
    # Type names (in case EML accidentally exposes them)
    "vec2", "vec3", "vec4", "mat2", "mat3", "mat4", "ivec2", "ivec3",
    "ivec4", "uvec2", "uvec3", "uvec4", "bvec2", "bvec3", "bvec4",
    "sampler2D", "sampler3D", "samplerCube",
})


# Calls into HLSL/SymPy-style names that need translation to GLSL
# intrinsics. Most are identical to HLSL but exp10 still needs a
# synthesised helper (GLSL has exp/exp2 but no exp10).
_CALL_REWRITE: dict[str, str] = {
    "exp10":  "_forge_exp10",
    "log10":  "log",        # GLSL has no log10 in 330 core; lower
                            # below as `(log(x) / log(10.0))` via
                            # synth helper. We special-case this so
                            # GLSL ES 300 compatibility stays.
    "log2":   "log2",       # GLSL has log2
    "exp2":   "exp2",       # GLSL has exp2
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "asinh":  "asinh",
    "acosh":  "acosh",
    "atanh":  "atanh",
}


# Synthesised helper bodies. Lazily emitted only when referenced.
_HELPERS_BY_REWRITE: dict[str, tuple[str, str]] = {
    "_forge_exp10": (
        "_forge_exp10",
        "// _forge_exp10 -- GLSL has no exp10 intrinsic; lower as 10^x.\n"
        "float _forge_exp10(float x) { return pow(10.0, x); }",
    ),
}


def _glsl_type(eml_type: str) -> str:
    return _TYPE_TO_GLSL.get(eml_type, "float")


def _struct_name(fn_name: str) -> str:
    """PascalCase + Result, mirrors HLSL/Java/C# convention."""
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


def _safe_ident(name: str) -> str:
    if name in _GLSL_RESERVED:
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


# Version directives keyed by flavor. Anything else raises.
_VERSION_DIRECTIVE: dict[str, str] = {
    "desktop": "#version 330 core",
    "es":      "#version 300 es",
}


class CompileError(Exception):
    """Raised on a NodeKind the GLSL backend doesn't recognize."""


class GLSLBackend:
    """Compile an EMLModule to a single .glsl function-library file.

    `flavor`:
      ``"desktop"`` -- ``#version 330 core``, no precision header
      ``"es"``      -- ``#version 300 es`` + ``precision highp float;``
    """

    name = "glsl"

    def __init__(
        self,
        indent: str = "    ",
        *,
        optimize: bool = True,
        flavor: str = "desktop",
    ):
        if flavor not in _VERSION_DIRECTIVE:
            raise ValueError(
                f"GLSLBackend: flavor must be one of "
                f"{sorted(_VERSION_DIRECTIVE)}; got {flavor!r}"
            )
        self.indent = indent
        self.optimize = optimize
        self.flavor = flavor

    def compile(self, mod: EMLModule) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        # Track synthesised helpers used by the body.
        self._helpers_used: set[str] = set()
        # In-module names so we only mangle CALL targets that we
        # know we defined here. External calls pass through.
        self._in_module_names: set[str] = (
            {fn.name for fn in mod.functions}
            | {c.name for c in mod.constants}
        )

        any_drift = any(
            _wants_drift_warning(fn.profile)[0]
            for fn in mod.functions
            if not fn.is_extern
        )

        flavor_label = "desktop GLSL 330 core" if self.flavor == "desktop" \
                       else "GLSL ES 300 (mobile / WebGL 2.0)"

        lines: list[str] = [
            _VERSION_DIRECTIVE[self.flavor],
        ]
        if self.flavor == "es":
            # Mandatory precision header for ES. We choose `highp`
            # uniformly; chain >= 2 functions get a per-function
            # warning anyway, and reduced-precision GPUs that don't
            # support highp will silently downgrade.
            lines.append("precision highp float;")
            lines.append("precision highp int;")
        lines.extend([
            "",
            f"// Generated by EML-lang GLSL backend ({flavor_label})",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {mod.source_file}",
            f"// Functions:     {len(mod.functions)}",
            f"// Constants:     {len(mod.constants)}",
            "//",
            "// Float32-only. GLSL has no widely-supported double; ",
            "// GL 4.0 + ARB_gpu_shader_fp64 is rare and is not",
            "// available in GLSL 330 core or GLSL ES 300.",
        ])
        if any_drift:
            lines.append("//")
            lines.append(
                "// At least one function has chain_order >= "
                f"{_DRIFT_WARN_CHAIN_FLOOR}; per-function drift warnings"
            )
            lines.append(
                "// appear inline above each affected function."
            )
        lines.extend([
            "//",
            "// Include this file in a vertex / fragment / compute",
            "// shader. No entry point is provided; the file is a",
            "// function library.",
            "",
        ])

        # Tuple-return structs precede the constants. GLSL has no
        # forward declarations.
        struct_lines: list[str] = []
        for fn in mod.functions:
            if fn.return_tuple_types:
                rec = _struct_name(fn.name)
                struct_lines.append(f"struct {rec}")
                struct_lines.append("{")
                for i, t in enumerate(fn.return_tuple_types):
                    struct_lines.append(
                        f"{self.indent}{_glsl_type(t)} e{i};"
                    )
                struct_lines.append("};")
                struct_lines.append("")
        lines.extend(struct_lines)

        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Buffer the function bodies first so we know which
        # synthesised helpers were referenced.
        fn_lines: list[str] = []
        for fn in mod.functions:
            if fn.is_extern:
                fn_lines.extend(self._emit_extern(fn))
            else:
                fn_lines.extend(self._emit_function(fn))
            fn_lines.append("")

        # Prepend helper definitions before the bodies.
        for helper_key in sorted(self._helpers_used):
            _, src = _HELPERS_BY_REWRITE[helper_key]
            for ln in src.split("\n"):
                lines.append(ln)
            lines.append("")

        lines.extend(fn_lines)
        return "\n".join(lines).rstrip() + "\n"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        glsl_type = _glsl_type(c.type_name)
        rhs = self._emit_expr(c.value)
        return [f"const {glsl_type} {_safe_ident(c.name)} = {rhs};"]

    # ── Extern (FFI) ──────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _glsl_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_glsl_type(p.type_name)} {_safe_ident(p.name)}"
            for p in fn.params
        )
        return [
            f"// extern: {fn.name} -- GLSL has no extern; provide a body",
            f"// before compiling, or keep the stub for unit-test wiring.",
            f"{ret} {_safe_ident(fn.name)}({params})",
            "{",
            f"{self.indent}// extern stub -- replace with implementation",
            f"{self.indent}return {ret}(0);",
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
            ret = _glsl_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_glsl_type(p.type_name)} {_safe_ident(p.name)}"
            for p in fn.params
        )

        out.append(f"{ret} {_safe_ident(fn.name)}({params})")
        out.append("{")
        record = (
            _struct_name(fn.name) if fn.return_tuple_types else None
        )
        body = self._emit_block(fn.body, return_value=True, tuple_record=record)
        for ln in body:
            out.append(self.indent + ln)
        out.append("}")
        return out

    # ── Phase E.2: refinement doc-comments (shader doc-only tier) ────

    def _emit_refinement_comments(self, fn: EMLFunction) -> list[str]:
        """Return one doc-comment line per refined parameter (Phase E.2).

        GLSL has no asserts; shader languages emit doc-comment obligations
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
                glsl_type = _glsl_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"{glsl_type} {_safe_ident(str(stmt.value))} = {rhs};"
                )
            elif stmt.kind == NodeKind.LET_MUT:
                glsl_type = _glsl_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"{glsl_type} {_safe_ident(str(stmt.value))} = {rhs};"
                )
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{_safe_ident(str(stmt.value))} = {rhs};")
            elif stmt.kind == NodeKind.WHILE:
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(
                    stmt.children[1], return_value=False, tuple_record=None,
                )
                out.append(f"while ({cond})")
                out.append("{")
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
                # GLSL struct literal: `FooResult(e0, e1)`. Returned
                # by value (no allocation).
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
                # No `f` suffix -- portable across GLSL 330 desktop
                # and GLSL ES 300. (GLSL 4.0 with the fp64 extension
                # would require it but is rare.)
                return s

            raise CompileError(f"unsupported literal: {v!r}")

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
                f"GLSL backend: tuple expression outside return needs "
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

        if kind in _BUILTIN_TO_GLSL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_GLSL[kind]}({args})"

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
                # Special case: log10 isn't natively present in GLSL
                # 330 core or ES 300; emit `(log(x) / log(10.0))`.
                if callee == "log10":
                    # `args` here is exactly the single argument
                    # expression; wrap inline.
                    return f"(log({args}) / log(10.0))"
                return f"{rewritten}({args})"
            if callee in self._in_module_names:
                return f"{_safe_ident(callee)}({args})"
            return f"{callee}({args})"

        raise CompileError(
            f"GLSL backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
