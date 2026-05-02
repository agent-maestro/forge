"""Metal Shading Language (MSL) backend.

Apple's shader language for iOS / macOS / iPadOS / visionOS.
Metal is C++14-based with shader-specific extensions (attributes,
address-space qualifiers, vector built-ins). Critical for mobile
gaming on Apple platforms and any deployment that targets the
Metal Performance Shaders pipeline.

The backend emits a single ``.metal`` file with one function per
EML function and no shader entry point. The caller wires entry
points (``[[kernel]]``, ``[[vertex]]``, ``[[fragment]]``) on top
of the generated function library.

Float32-only. Metal supports ``half`` (16-bit) natively but
``double`` only on macOS Metal 2.4+ and never on iOS GPUs --
EML ``Real`` and ``f64`` therefore lower to ``float`` with a
header warning, exactly as in HLSL/GLSL/WGSL.

Mapping
=======

  EML AST kind        ->  Metal output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0f"     (explicit f suffix)
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier (snake_case preserved)
  BINOP +/-/*//       ->  arithmetic
  BINOP &&/||         ->  && / ||
  UNARYOP -           ->  unary minus
  UNARYOP !           ->  !
  EXP/LN/SIN/COS/...  ->  exp/log/sin/cos/...     (after
                          `using namespace metal;` -- bare
                          built-in names; log is natural log)
  ABS(x)              ->  abs(x)
  CLAMP(x, lo, hi)    ->  clamp(x, lo, hi)
  POW(x, y)           ->  pow(x, y)
  CALL                ->  forward function call
  TUPLE return        ->  struct FooResult { float e0; float e1; }
                          + named-init constructor on return
  LET name = expr     ->  "<type> name = <expr>;"
  LET_MUT name = expr ->  "<type> name = <expr>;"
  ASSIGN name = expr  ->  "name = <expr>;"
  WHILE cond block    ->  while (cond) { ... }
  BLOCK               ->  brace block; final expression -> return
  requires            ->  // forge.requires comment (advisory)
  ensures             ->  // forge.ensures comment (advisory)
  @verify(lean, ...)  ->  // forge.verify lean theorem=...

The output has no entry-point markers; it is a function library
intended to be ``#include``-d into a kernel / vertex / fragment
file. Validate with:

    xcrun -sdk macosx metal -c output.metal -o /dev/null

(or `xcrun metal-source` / Xcode build, which all run the same
front-end. macOS-only -- on Windows/Linux the structural-emit
correctness is the only validation available.)

Reference: https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf
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


_BUILTIN_TO_METAL: dict[NodeKind, str] = {
    NodeKind.EXP:   "exp",
    NodeKind.LN:    "log",       # Metal `log` is natural log
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


_TYPE_TO_METAL: dict[str, str] = {
    "Real":    "float",
    "f64":     "float",   # forced to f32 -- see header warning
    "f32":     "float",
    "f16":     "half",    # Metal's half is native and fast
    "bf16":    "float",   # no native bf16; promote to f32
    "u8":      "uchar",
    "u16":     "ushort",
    "u32":     "uint",
    "u64":     "uint",    # Metal lacks u64 in shader scope; default safe
    "i8":      "char",
    "i16":     "short",
    "i32":     "int",
    "i64":     "int",     # same caveat as u64
    "bool":    "bool",
}


_DRIFT_WARN_CHAIN_FLOOR = 2


# Metal reserves C++14 keywords + Metal-specific qualifiers and
# attribute names. The most common collisions for EML ports are
# `kernel`, `vertex`, `fragment`, `device`, `constant`, `thread`,
# and the C++ keywords `class`, `template`, `typename`.
_METAL_RESERVED: frozenset[str] = frozenset({
    # Metal address-space qualifiers
    "device", "constant", "threadgroup", "thread", "ray_data",
    "object_data", "instance_data",
    # Metal entry-point markers
    "kernel", "vertex", "fragment", "intersection", "visible",
    # Texture / sampler types
    "texture1d", "texture2d", "texture3d", "texturecube",
    "texture1d_array", "texture2d_array", "texturecube_array",
    "texture2d_ms", "depth2d", "depthcube",
    "sampler", "sampler_comparison",
    # Vector / matrix built-in types (and the scalar types they
    # build on -- `half` and `float` themselves are valid Metal type
    # names, not just modifiers, so EML callers using them as
    # variable names need renaming)
    "float", "half", "int", "uint", "uchar", "ushort", "char", "short",
    "float2", "float3", "float4", "half2", "half3", "half4",
    "int2", "int3", "int4", "uint2", "uint3", "uint4",
    "bool2", "bool3", "bool4",
    "float2x2", "float3x3", "float4x4",
    "half2x2", "half3x3", "half4x4",
    # C++14 keywords commonly used as variable names
    "class", "template", "typename", "namespace", "using",
    "this", "operator", "new", "delete",
    "public", "private", "protected", "virtual", "friend",
    "explicit", "inline", "const", "volatile", "mutable",
    "static", "extern", "register", "auto",
    # Common Metal built-in functions (would shadow if used as IDs)
    "saturate", "step", "smoothstep", "mix", "fract", "sign",
    "fma", "rsqrt", "fast", "precise",
    # Reserved literals
    "true", "false", "null", "nullptr",
})


_CALL_REWRITE: dict[str, str] = {
    "exp10":  "_forge_exp10",
    "log10":  "log10",
    "log2":   "log2",
    "exp2":   "exp2",
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "asinh":  "asinh",
    "acosh":  "acosh",
    "atanh":  "atanh",
}


_HELPERS_BY_REWRITE: dict[str, tuple[str, str]] = {
    "_forge_exp10": (
        "_forge_exp10",
        "// _forge_exp10 -- Metal has no exp10 intrinsic; lower as 10^x.\n"
        "inline float _forge_exp10(float x) { return pow(10.0f, x); }",
    ),
}


def _safe_ident(name: str) -> str:
    if name in _METAL_RESERVED:
        return name + "_"
    return name


def _metal_type(eml_type: str) -> str:
    return _TYPE_TO_METAL.get(eml_type, "float")


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
    """Raised on a NodeKind the Metal backend doesn't recognize."""


class MetalBackend:
    """Compile an EMLModule to a single .metal function-library file."""

    name = "metal"

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
            "// Generated by EML-lang Metal backend (function library)",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {mod.source_file}",
            f"// Functions:     {len(mod.functions)}",
            f"// Constants:     {len(mod.constants)}",
            "//",
            "// Float32-only. EML `Real` and `f64` lower to Metal `float`.",
            "// Metal supports `half` (16-bit) natively; `double` is only",
            "// available on macOS Metal 2.4+ and never on iOS GPUs --",
            "// callers needing >32-bit precision should do the heavy lift",
            "// on CPU and ship a float32 result into the shader.",
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
            "// No entry-point markers ([[kernel]] / [[vertex]] /",
            "// [[fragment]]) are emitted; this is a function library.",
            "// `#include` it from a kernel / vertex / fragment .metal",
            "// source and compose entry points there.",
            "",
            "#include <metal_stdlib>",
            "using namespace metal;",
            "",
        ])

        # Tuple-return structs at module scope. Metal/C++ requires
        # struct definitions before first use.
        for fn in mod.functions:
            if fn.return_tuple_types:
                rec = _struct_name(fn.name)
                lines.append(f"struct {rec}")
                lines.append("{")
                for i, t in enumerate(fn.return_tuple_types):
                    lines.append(f"{self.indent}{_metal_type(t)} e{i};")
                lines.append("};")
                lines.append("")

        # Constants. Metal `constant` is a buffer-binding qualifier
        # (address space) at file scope; for compile-time numeric
        # constants we want plain `static constexpr` in C++14 style.
        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Forward declarations for every function, before any body.
        # Metal is C++14 and accepts standard forward declarations.
        # Without these, an .eml file that defines `caller()` BEFORE
        # its callee `helper()` -- or that declares `helper()` as
        # `extern fn` (lowered to a stub at the bottom of the file)
        # -- fails compile with "use of undeclared identifier".
        decl_lines: list[str] = [
            "// Forward declarations -- ensures every CALL target is",
            "// visible regardless of source order or extern placement.",
        ]
        for fn in mod.functions:
            decl_lines.append(self._emit_forward_decl(fn))
        decl_lines.append("")
        lines.extend(decl_lines)

        # Functions
        fn_lines: list[str] = []
        for fn in mod.functions:
            if fn.is_extern:
                fn_lines.extend(self._emit_extern(fn))
            else:
                fn_lines.extend(self._emit_function(fn))
            fn_lines.append("")

        # Synthesized helpers (if any) before first use.
        for helper_key in sorted(self._helpers_used):
            _, src = _HELPERS_BY_REWRITE[helper_key]
            for ln in src.split("\n"):
                lines.append(ln)
            lines.append("")

        lines.extend(fn_lines)

        return "\n".join(lines).rstrip() + "\n"

    # ── Forward declarations ──────────────────────────────────

    def _emit_forward_decl(self, fn: EMLFunction) -> str:
        """Single-line `inline <ret> <name>(<params>);` so callers
        earlier in the file can name the function before the body."""
        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _metal_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_metal_type(p.type_name)} {_safe_ident(p.name)}"
            for p in fn.params
        )
        return f"inline {ret} {_safe_ident(fn.name)}({params});"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        metal_type = _metal_type(c.type_name)
        rhs = self._emit_expr(c.value)
        # `constexpr constant` would be ideal but isn't valid Metal
        # syntax (Metal's `constant` is an address-space qualifier).
        # `static constant` at file scope works for numeric literals
        # and is the idiom in Apple's sample code.
        return [f"constant {metal_type} {_safe_ident(c.name)} = {rhs};"]

    # ── Extern ────────────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _metal_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_metal_type(p.type_name)} {_safe_ident(p.name)}"
            for p in fn.params
        )
        return [
            f"// extern: {fn.name} -- supply a body before compiling.",
            f"inline {ret} {_safe_ident(fn.name)}({params});",
        ]

    # ── Function emit ─────────────────────────────────────────

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        out: list[str] = []
        emit_warn, why = _wants_drift_warning(fn.profile)
        out.extend(self._fn_header_comment(fn, emit_warn=emit_warn, why=why))

        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _metal_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_metal_type(p.type_name)} {_safe_ident(p.name)}"
            for p in fn.params
        )

        # `inline` so the Metal compiler can fold the call into the
        # caller; matches the C# AggressiveInlining + Kotlin pattern.
        out.append(f"inline {ret} {_safe_ident(fn.name)}({params})")
        out.append("{")
        record = _struct_name(fn.name) if fn.return_tuple_types else None
        body = self._emit_block(
            fn.body, return_value=True, tuple_record=record,
        )
        for ln in body:
            out.append(self.indent + ln)
        out.append("}")
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
        for r in fn.requires:
            try:
                out.append(f"//   forge.requires: {self._emit_expr(r)}")
            except CompileError:
                pass
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
                metal_type = _metal_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"{metal_type} {_safe_ident(str(stmt.value))} = {rhs};"
                )
            elif stmt.kind == NodeKind.LET_MUT:
                metal_type = _metal_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"{metal_type} {_safe_ident(str(stmt.value))} = {rhs};"
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
                # Metal/C++ aggregate-init form for a struct.
                elems = ", ".join(self._emit_expr(c) for c in stmt.children)
                out.append(f"{tuple_record} _r = {{ {elems} }};")
                out.append("return _r;")
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
                return s + "f"
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
                f"Metal backend: tuple expression outside return needs "
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

        if kind in _BUILTIN_TO_METAL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_METAL[kind]}({args})"

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
            f"Metal backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
