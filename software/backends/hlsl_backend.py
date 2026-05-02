"""HLSL shader backend (function library form, float32-only).

Emits a single ``.hlsl`` file with one function per EML function and
no shader entry point. The output is meant to be ``#include``-d into
a vertex / fragment / compute / raytracing shader (any shader stage):

    #include "<module>.hlsl"
    float4 main(...) : SV_Target {
        return float4(my_kernel_function(input.x), 0, 0, 1);
    }

Float32-only because most GPUs do not support double natively;
HLSL's ``double`` keyword exists but is emulated on most hardware
and is unavailable in many compilation profiles. EML ``Real`` /
``f64`` therefore lower to HLSL ``float`` with a precision warning
emitted at the file header.

Chain-order-aware drift warnings
================================

EML's Pfaffian chain order maps directly to GPU float32 precision
risk: chain 0-1 functions stay numerically safe in float32, but
chain 2+ accumulate ULP drift along nested transcendentals. The
backend emits a ``// WARNING: chain_order=N -- float32 drift risk``
comment block above any function whose chain order is >= 2 OR whose
drift_risk is HIGH. The user is then explicitly informed at the
shader source level, not buried in a config file.

Mapping
=======

  EML AST kind        ->  HLSL output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0f"     (explicit float suffix)
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier (snake_case preserved)
  BINOP +/-/*//       ->  HLSL arithmetic (scalar)
  BINOP comparisons   ->  HLSL comparison
  BINOP &&/||         ->  HLSL && / || (scalar form -- our kernels
                          are scalar so this is the right primitive,
                          NOT the vector and()/or() functions)
  UNARYOP -           ->  HLSL unary minus
  UNARYOP !           ->  HLSL !
  EXP/LN/SIN/COS/...  ->  exp/log/sin/cos/...   (HLSL intrinsics --
                          no Math. prefix; lowercase names; log is
                          natural-log per HLSL spec)
  ABS(x)              ->  abs(x)
  CLAMP(x, lo, hi)    ->  clamp(x, lo, hi)
                          (NOT saturate -- we don't auto-detect [0,1]
                          and force the optimization there; GPU
                          compilers fold clamp(x, 0, 1) -> saturate
                          themselves.)
  POW(x, y)           ->  pow(x, y)
  EML(x, y)           ->  (exp(x) - log(y))
  CALL                ->  forward function call (same module)
  TUPLE return        ->  struct FooResult { float e0; float e1; ... }
  LET name = expr     ->  "<type> name = <expr>;"
  LET_MUT name = expr ->  "<type> name = <expr>;"
  ASSIGN name = expr  ->  "name = <expr>;"
  WHILE cond block    ->  while (<cond>) { <block> }
  BLOCK               ->  brace block; final expression -> return
  requires            ->  // forge.requires comment (advisory)
  ensures             ->  // forge.ensures comment (advisory)
  @verify(lean, ...)  ->  // forge.verify lean theorem=...

We deliberately do NOT emit runtime require/ensures checks: a GPU
shader can't throw, and the cost of a per-call branch on the hot
path defeats the inlining the HLSL compiler is going to do anyway.

Reference: lang/spec/EML_LANG_DESIGN.md + Phase 4 backend roadmap.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Builtin NodeKind -> HLSL intrinsic name. All HLSL math intrinsics
# are lowercase function-name (no namespace, no Math. prefix).
_BUILTIN_TO_HLSL: dict[NodeKind, str] = {
    NodeKind.EXP:   "exp",
    NodeKind.LN:    "log",      # HLSL `log` is natural log (base-e)
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


# EML type -> HLSL type. Every Real / f64 lowers to `float` with a
# header warning -- HLSL `double` is emulated on most GPUs and not
# available in many shader profiles.
_TYPE_TO_HLSL: dict[str, str] = {
    "Real":    "float",
    "f64":     "float",   # forced to float32 -- see header warning
    "f32":     "float",
    "f16":     "half",
    "bf16":    "float",   # no native bf16 in HLSL; promote
    "u8":      "uint",
    "u16":     "uint",
    "u32":     "uint",
    "u64":     "uint",    # uint64_t needs SM 6.0+; default safe
    "i8":      "int",
    "i16":     "int",
    "i32":     "int",
    "i64":     "int",     # int64_t needs SM 6.0+; default safe
    "bool":    "bool",
}


# Chain order >= this triggers the drift warning comment block in
# generated HLSL. Float32 + chain 2+ is the precision-risk regime.
_DRIFT_WARN_CHAIN_FLOOR = 2


# HLSL reserved words that frequently collide with EML identifier
# names. The most common collision in practice is `linear` (used as
# an audio / signal-domain variable name, also an HLSL interpolation
# modifier on input parameters). Any identifier in this set gets a
# trailing underscore appended on emit so it doesn't accidentally
# parse as a modifier or built-in. Function calls that target
# in-module functions also get renamed transparently.
_HLSL_RESERVED: frozenset[str] = frozenset({
    # Geometry-shader primitive topology modifiers (these parse as
    # modifiers before a parameter type; using them as identifiers
    # gives "modifiers must appear before type")
    "point", "line", "triangle", "lineadj", "triangleadj",
    # Interpolation modifiers
    "linear", "nointerpolation", "noperspective", "sample", "centroid",
    # Parameter direction modifiers
    "in", "out", "inout",
    # Storage / layout / packing modifiers
    "uniform", "shared", "groupshared", "precise", "volatile",
    "register", "row_major", "column_major", "snorm", "unorm",
    # Type names that EML doesn't surface but HLSL parses
    "vector", "matrix", "string", "texture", "sampler",
    "Buffer", "RWBuffer", "ByteAddressBuffer", "RWByteAddressBuffer",
    "Texture1D", "Texture2D", "Texture3D", "TextureCube",
    "RWTexture1D", "RWTexture2D", "RWTexture3D",
    # Common HLSL intrinsic names (collide if used as VAR names)
    "lerp", "smoothstep", "saturate", "frac", "step", "sign",
    "mad", "rcp", "rsqrt", "ddx", "ddy", "fwidth", "discard",
    "transpose", "determinant",
})


# CALL targets that aren't defined in-module but happen to be HLSL
# math intrinsics with a different name. Map the EML/SymPy name to
# the HLSL form. Anything not in this map passes through verbatim
# (and will surface as an undeclared-identifier error at DXC time
# if it isn't actually defined elsewhere in the file).
_CALL_REWRITE: dict[str, str] = {
    "exp10":  "_forge_exp10",  # synth helper, see _HELPERS_BY_REWRITE
    "log10":  "log10",         # HLSL has log10 natively
    "log2":   "log2",          # HLSL has log2 natively
    "exp2":   "exp2",          # HLSL has exp2 natively
    # SymPy-style names that EML's parser preserves verbatim.
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "asinh":  "asinh",
    "acosh":  "acosh",
    "atanh":  "atanh",
}


# Synthesized helper bodies that the backend emits inline whenever
# the corresponding rewrite is referenced. Each entry: (name, src).
_HELPERS_BY_REWRITE: dict[str, tuple[str, str]] = {
    "_forge_exp10": (
        "_forge_exp10",
        "// _forge_exp10 -- HLSL has no exp10 intrinsic; lower as 10^x.\n"
        "float _forge_exp10(float x) { return pow(10.0f, x); }",
    ),
}


def _safe_ident(name: str) -> str:
    """Rename an EML identifier when it collides with an HLSL
    reserved word. We append a single trailing underscore -- a
    deterministic, easily-reversible mangling that keeps source
    diffability while letting DXC parse cleanly."""
    if name in _HLSL_RESERVED:
        return name + "_"
    return name


def _hlsl_type(eml_type: str) -> str:
    return _TYPE_TO_HLSL.get(eml_type, "float")


def _include_guard(mod_name: str) -> str:
    return f"FORGE_{mod_name.upper()}_HLSL"


def _struct_name(fn_name: str) -> str:
    """PascalCase + Result, mirrors Java/C# convention."""
    parts = fn_name.split("_")
    camel = "".join(p[:1].upper() + p[1:] for p in parts) or "Anon"
    return f"{camel}Result"


def _wants_drift_warning(profile: dict | None) -> tuple[bool, str]:
    """Return (emit_warning, reason) for a function profile."""
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
    """Raised on a NodeKind the HLSL backend doesn't recognize."""


class HLSLBackend:
    """Compile an EMLModule to a single .hlsl function-library file."""

    name = "hlsl"

    def __init__(self, indent: str = "    ", *, optimize: bool = True):
        self.indent = indent
        self.optimize = optimize

    def compile(self, mod: EMLModule) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        # Track which synthesized helpers are referenced by the
        # generated body so we can prepend their definitions.
        self._helpers_used: set[str] = set()
        # The set of names defined IN this module. CALL targets
        # outside this set are treated as externals and emitted
        # verbatim (they may resolve to HLSL intrinsics like step,
        # smoothstep, lerp, etc. -- renaming would break those).
        self._in_module_names: set[str] = (
            {fn.name for fn in mod.functions}
            | {c.name for c in mod.constants}
        )

        guard = _include_guard(mod.name or "anon")
        any_drift = any(
            _wants_drift_warning(fn.profile)[0]
            for fn in mod.functions
            if not fn.is_extern
        )

        lines: list[str] = [
            "// Generated by EML-lang HLSL backend (function library)",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {mod.source_file}",
            f"// Functions:     {len(mod.functions)}",
            f"// Constants:     {len(mod.constants)}",
            "//",
            "// Float32-only. EML `Real` and `f64` lower to HLSL `float`.",
            "// HLSL `double` is emulated on most GPUs and unavailable in",
            "// many shader profiles -- if you need >32-bit precision, do",
            "// the high-precision step on CPU and ship a float32 result.",
        ]
        if any_drift:
            lines.append("//")
            lines.append(
                "// At least one function in this module has chain_order >= "
                f"{_DRIFT_WARN_CHAIN_FLOOR}; per-function drift warnings"
            )
            lines.append(
                "// appear inline above each affected function."
            )
        lines.extend([
            "//",
            "// Include this file in a vertex / fragment / compute /",
            "// raytracing shader. No entry point is provided; the file is",
            "// a function library (compile with DXC -T lib_6_3 to verify).",
            "",
            f"#ifndef {guard}",
            f"#define {guard}",
            "",
        ])

        # Tuple-return structs go before the constants. HLSL has no
        # forward declarations; structs must precede first use.
        struct_lines: list[str] = []
        for fn in mod.functions:
            if fn.return_tuple_types:
                rec = _struct_name(fn.name)
                struct_lines.append(f"struct {rec}")
                struct_lines.append("{")
                for i, t in enumerate(fn.return_tuple_types):
                    struct_lines.append(
                        f"{self.indent}{_hlsl_type(t)} e{i};"
                    )
                struct_lines.append("};")
                struct_lines.append("")
        lines.extend(struct_lines)

        # Constants
        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Forward declarations for every function, before any body.
        # HLSL DXC (and FXC) accept C-style forward declarations for
        # free functions. Without these, an .eml file that defines
        # `caller()` BEFORE its callee `helper()` -- or that declares
        # `helper()` as `extern fn` (which we lower to a stub body
        # at the bottom of the file) -- fails compile with
        # "use of undeclared identifier `helper`".
        decl_lines: list[str] = [
            "// Forward declarations -- ensures every CALL target is",
            "// visible regardless of source order or extern placement.",
        ]
        for fn in mod.functions:
            decl_lines.append(self._emit_forward_decl(fn))
        decl_lines.append("")
        lines.extend(decl_lines)

        # Functions -- emit into a buffer first so we know which
        # synthesized helpers were referenced before we lay them out.
        fn_lines: list[str] = []
        for fn in mod.functions:
            if fn.is_extern:
                fn_lines.extend(self._emit_extern(fn))
            else:
                fn_lines.extend(self._emit_function(fn))
            fn_lines.append("")

        # Synthesized helper definitions (if any). These must precede
        # their first call site -- emitted between forward decls and
        # function bodies so callers in fn_lines can resolve them.
        for helper_key in sorted(self._helpers_used):
            _, src = _HELPERS_BY_REWRITE[helper_key]
            for ln in src.split("\n"):
                lines.append(ln)
            lines.append("")

        lines.extend(fn_lines)

        lines.append(f"#endif  // {guard}")
        return "\n".join(lines).rstrip() + "\n"

    # ── Forward declarations ──────────────────────────────────

    def _emit_forward_decl(self, fn: EMLFunction) -> str:
        """Single-line `<ret> <name>(<params>);` so callers earlier
        in the file can name the function before the body lands."""
        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _hlsl_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_hlsl_type(p.type_name)} {_safe_ident(p.name)}"
            for p in fn.params
        )
        return f"{ret} {_safe_ident(fn.name)}({params});"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        hlsl_type = _hlsl_type(c.type_name)
        rhs = self._emit_expr(c.value)
        return [f"static const {hlsl_type} {_safe_ident(c.name)} = {rhs};"]

    # ── Extern (FFI) ──────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        # HLSL has no equivalent of an extern at the language level
        # (everything ships in the shader). We emit a placeholder
        # signature plus a comment so consumers can substitute their
        # own body before compiling.
        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _hlsl_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_hlsl_type(p.type_name)} {_safe_ident(p.name)}"
            for p in fn.params
        )
        return [
            f"// extern: {fn.name} -- HLSL has no extern; provide a body",
            f"// before compiling, or keep the stub for unit-test wiring.",
            f"{ret} {_safe_ident(fn.name)}({params})",
            "{",
            f"{self.indent}// extern stub -- replace with implementation",
            f"{self.indent}return ({ret})0;",
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
            ret = _hlsl_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_hlsl_type(p.type_name)} {_safe_ident(p.name)}"
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
                "//   WARNING: float32 precision drift risk -- "
                f"{why}."
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
                hlsl_type = _hlsl_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"{hlsl_type} {_safe_ident(str(stmt.value))} = {rhs};"
                )
            elif stmt.kind == NodeKind.LET_MUT:
                hlsl_type = _hlsl_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(
                    f"{hlsl_type} {_safe_ident(str(stmt.value))} = {rhs};"
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
                # Tuple-return: build the struct field-by-field. HLSL
                # supports `struct FooResult r = { e0, e1 };` initialiser
                # syntax at function scope, which is the cleanest form.
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
                # HLSL float-suffix `f` so the literal isn't promoted
                # to double in the host expression -- some shader
                # profiles warn on float/double mixing.
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
            # Outside of a return slot, HLSL has no native tuple
            # type. Surface as a comma list inside parens; callers
            # that hit this in expression position get a CompileError
            # via the parent NodeKind handling.
            elems = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            raise CompileError(
                f"HLSL backend: tuple expression outside return needs "
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

        if kind in _BUILTIN_TO_HLSL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_HLSL[kind]}({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            callee = str(node.value)
            # Rewrite calls into HLSL-equivalent intrinsics or
            # synthesized helpers. Anything else passes through;
            # if the callee isn't defined in this module DXC will
            # flag it as an undeclared identifier (typically from
            # an un-inlined cross-module import upstream).
            rewritten = _CALL_REWRITE.get(callee)
            if rewritten is not None:
                if rewritten in _HELPERS_BY_REWRITE:
                    self._helpers_used.add(rewritten)
                return f"{rewritten}({args})"
            # Only rename when the call resolves to an in-module
            # function whose name we already mangled. External
            # calls (HLSL intrinsics like step, smoothstep, lerp,
            # or upstream un-inlined helpers) must pass through
            # untouched.
            if callee in self._in_module_names:
                return f"{_safe_ident(callee)}({args})"
            return f"{callee}({args})"

        raise CompileError(
            f"HLSL backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
