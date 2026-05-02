"""Swift backend.

Emits a single ``.swift`` file with top-level functions (Swift
supports file-scope ``func`` declarations, no class wrapper needed).
Math routines route through ``Foundation`` so the same source
compiles on iOS / macOS / iPadOS / visionOS / watchOS / Linux Swift.

Templated from kotlin_backend.py -- Swift and Kotlin share the
typed-functional shape; the differences are in keyword spelling
and standard-library names.

Mapping
=======

  EML AST kind        ->  Swift output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0"
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier
  BINOP +/-/*//       ->  Swift arithmetic (yields Double)
  BINOP comparisons   ->  Swift comparison (yields Bool)
  BINOP &&/||         ->  &&  / ||
  EXP/LN/SIN/COS/...  ->  exp / log / sin / cos / ...
                          (Foundation imports the C math globals;
                          log is natural log)
  ABS(x)              ->  abs(x)
  CLAMP(x, lo, hi)    ->  min(max(x, lo), hi)   (Swift stdlib has
                          clamped(to:) on Comparable, but not on
                          arbitrary scalars; the min/max idiom is
                          portable across stdlib versions)
  POW(x, y)           ->  pow(x, y)
  EML(x, y)           ->  (exp(x) - log(y))
  LET name = expr     ->  "let name = <expr>"
  LET_MUT name = expr ->  "var name = <expr>"
  ASSIGN name = expr  ->  "name = <expr>"
  WHILE cond block    ->  while cond { ... }
  BLOCK               ->  brace block; final expression -> return
  requires            ->  precondition(<expr>, "...")
  ensures             ->  doc-comment-only (Swift's `assert(...)`
                          fires at runtime on the post-condition,
                          which is rarely what callers want; we
                          surface ensures advisory like Kotlin)
  @verify(lean, ...)  ->  doc-comment @forge.verify line

Reserved-word handling
======================

Swift has the largest reserved-word set of any backend we ship.
The _SWIFT_RESERVED frozenset captures the keywords the spec
documents, plus the contextual keywords that frequently collide
with EML variable / parameter names (``operator``, ``static``,
``where``, ``in``, etc.). Collisions get a trailing underscore.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Swift sources `Foundation` math globals (`sin`, `cos`, `exp`,
# `log`, `sqrt`, `pow`, `abs`, etc.) directly into scope on
# `import Foundation`. We emit the bare names; this matches how
# Apple's own sample code is written.
_BUILTIN_TO_SWIFT: dict[NodeKind, str] = {
    NodeKind.EXP:   "exp",
    NodeKind.LN:    "log",      # Swift `log(x)` is natural log
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
}


_TYPE_TO_SWIFT: dict[str, str] = {
    "Real": "Double",
    "f64":  "Double",
    "f32":  "Float",
    "f16":  "Float",      # Swift has Float16 but it's iOS 14+
    "bf16": "Float",
    "u8":   "UInt8",
    "u16":  "UInt16",
    "u32":  "UInt32",
    "u64":  "UInt64",
    "i8":   "Int8",
    "i16":  "Int16",
    "i32":  "Int32",
    "i64":  "Int64",
    "bool": "Bool",
}


# Swift's reserved-word set. Only true keywords -- contextual
# keywords (`get`, `set`, `final`, etc.) are allowed as identifiers
# in most positions and Foundation function names (`sin`, `cos`,
# `min`, `max`, etc.) MUST stay un-renamed because EML kernels call
# them by name. An earlier version stuffed the math globals into
# this set and the renamer mangled `min(a, b)` into `min_(a, b)`,
# which then failed swiftc with "cannot find 'min_' in scope".
_SWIFT_RESERVED: frozenset[str] = frozenset({
    # Declarations
    "associatedtype", "class", "deinit", "enum", "extension",
    "fileprivate", "func", "import", "init", "inout", "internal",
    "let", "open", "operator", "private", "precedencegroup",
    "protocol", "public", "rethrows", "static", "struct", "subscript",
    "typealias", "var",
    # Statements
    "break", "case", "catch", "continue", "default", "defer", "do",
    "else", "fallthrough", "for", "guard", "if", "in", "repeat",
    "return", "throw", "switch", "where", "while",
    # Expressions / types
    "Any", "as", "await", "false", "is", "nil", "rethrows", "self",
    "Self", "super", "throw", "throws", "true", "try", "Type",
    # Reserved patterns
    "_",
})


# Call-target rewrites. SymPy-style names that EML preserves as
# verbatim CALL identifiers (`arcsin`, `arccos`, `arctan`) need to
# be lowered to Foundation's spelling. Functions Foundation doesn't
# have at all (`step`, `exp10`) get synthesized as inline helpers.
_CALL_REWRITE: dict[str, str] = {
    "exp10":  "_forge_exp10",   # Foundation has no exp10
    "step":   "_forge_step",    # GLSL/HLSL builtin; Swift has none
    "log10":  "log10",          # Foundation has log10 natively
    "log2":   "log2",           # Foundation has log2
    "exp2":   "exp2",           # Foundation has exp2
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "asinh":  "asinh",
    "acosh":  "acosh",
    "atanh":  "atanh",
}


# Synthesized inline helpers. Emitted before first use whenever the
# corresponding rewrite is referenced.
_HELPERS_BY_REWRITE: dict[str, tuple[str, str]] = {
    "_forge_exp10": (
        "_forge_exp10",
        "// _forge_exp10 -- Foundation has no exp10; lower as 10^x.\n"
        "@inline(__always) public func _forge_exp10(_ x: Double) -> Double {\n"
        "    return pow(10.0, x)\n"
        "}",
    ),
    "_forge_step": (
        "_forge_step",
        "// _forge_step -- GLSL-style step. Returns 0 if x < edge, 1 otherwise.\n"
        "@inline(__always) public func _forge_step(_ edge: Double, _ x: Double) -> Double {\n"
        "    return x < edge ? 0.0 : 1.0\n"
        "}",
    ),
}


_DRIFT_WARN_CHAIN_FLOOR = 2


def _safe_ident(name: str) -> str:
    if name in _SWIFT_RESERVED:
        return name + "_"
    return name


def _swift_type(eml_type: str) -> str:
    return _TYPE_TO_SWIFT.get(eml_type, "Double")


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
    """Raised on a NodeKind the Swift backend doesn't recognize."""


class SwiftBackend:
    """Compile an EMLModule to a single .swift source file."""

    name = "swift"

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
        # outside this set + outside the rewrite map are emitted
        # verbatim (they may resolve to Foundation globals like
        # `sin`, `min`, `max`, or to upstream un-inlined helpers).
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
            "// Generated by EML-lang Swift backend",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {mod.source_file}",
            f"// Functions:     {len(mod.functions)}",
            f"// Constants:     {len(mod.constants)}",
        ]
        if any_drift:
            lines.append("//")
            lines.append(
                "// At least one function in this module has chain_order "
                f">= {_DRIFT_WARN_CHAIN_FLOOR}; per-function drift"
            )
            lines.append(
                "// warnings appear inline above each affected function."
            )
        lines.extend([
            "",
            "import Foundation",
            "",
        ])

        # Tuple-returning functions get a Swift `struct` so callers
        # access fields by name. (Swift tuples would also work but
        # leak unnamed-element ergonomics into call sites.)
        for fn in mod.functions:
            if fn.return_tuple_types:
                rec = _struct_name(fn.name)
                lines.append(f"public struct {rec} {{")
                for i, t in enumerate(fn.return_tuple_types):
                    lines.append(f"{self.indent}public let e{i}: {_swift_type(t)}")
                # Default memberwise initializer is implicit, but make
                # it `public` so callers in another module can use it.
                init_params = ", ".join(
                    f"e{i}: {_swift_type(t)}"
                    for i, t in enumerate(fn.return_tuple_types)
                )
                lines.append(f"{self.indent}public init({init_params}) {{")
                for i in range(len(fn.return_tuple_types)):
                    lines.append(f"{self.indent}{self.indent}self.e{i} = e{i}")
                lines.append(f"{self.indent}}}")
                lines.append("}")
                lines.append("")

        # Constants
        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Functions -- emit into a buffer first so we know which
        # synthesized helpers were referenced before we lay them out.
        fn_lines: list[str] = []
        for fn in mod.functions:
            if fn.is_extern:
                fn_lines.extend(self._emit_extern(fn))
            else:
                fn_lines.extend(self._emit_function(fn))
            fn_lines.append("")

        # Synthesized helpers (if any were used) before first call.
        for helper_key in sorted(self._helpers_used):
            _, src = _HELPERS_BY_REWRITE[helper_key]
            for ln in src.split("\n"):
                lines.append(ln)
            lines.append("")

        lines.extend(fn_lines)

        return "\n".join(lines).rstrip() + "\n"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        sw_type = _swift_type(c.type_name)
        rhs = self._emit_expr(c.value)
        # `public let` so a Swift Package that depends on the
        # generated file can reference the constants externally.
        return [f"public let {_safe_ident(c.name)}: {sw_type} = {rhs}"]

    # ── Extern (FFI) ──────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _swift_type(fn.return_type or "Real")
        params = ", ".join(
            f"_ {_safe_ident(p.name)}: {_swift_type(p.type_name)}"
            for p in fn.params
        )
        return [
            f"// extern: {fn.name} -- supply via @_cdecl bridge or",
            f"// linked C symbol; the stub returns zero so the file",
            f"// compiles without the implementation present.",
            f"@inline(__always) public func "
            f"{_safe_ident(fn.name)}({params}) -> {ret} {{",
            f"{self.indent}return {ret}() // extern stub",
            f"}}",
        ]

    # ── Function emit ─────────────────────────────────────────

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        out: list[str] = self._docstring(fn)

        if fn.return_tuple_types:
            ret = _struct_name(fn.name)
        else:
            ret = _swift_type(fn.return_type or "Real")
        # Unlabeled parameters with `_` so call sites match the EML
        # convention: `pid(error, integral, kp, ki)` rather than
        # `pid(error: error, integral: integral, ...)`.
        params = ", ".join(
            f"_ {_safe_ident(p.name)}: {_swift_type(p.type_name)}"
            for p in fn.params
        )

        out.append(
            f"@inline(__always) public func "
            f"{_safe_ident(fn.name)}({params}) -> {ret} {{"
        )

        # Preconditions via Swift's `precondition()` -- always
        # checked, including in release builds (matching Kotlin's
        # `require`).  `assert()` would be debug-only and is the
        # wrong semantic for an EML `requires` contract.
        for r in fn.requires:
            try:
                cond = self._emit_expr(r)
                msg = f"{fn.name}: requires {cond}"
                # Escape any embedded double-quotes or backslashes in
                # the message string. EML expressions don't normally
                # contain them but we play it safe.
                msg = msg.replace("\\", "\\\\").replace('"', '\\"')
                out.append(
                    f"{self.indent}precondition({cond}, \"{msg}\")"
                )
            except CompileError as e:
                out.append(f"{self.indent}// require: unsupported ({e})")

        record = (
            _struct_name(fn.name) if fn.return_tuple_types else None
        )
        body = self._emit_block(
            fn.body, return_value=True, tuple_record=record,
        )
        for ln in body:
            out.append(self.indent + ln)
        out.append("}")
        return out

    # ── Doc-comment ───────────────────────────────────────────

    def _docstring(self, fn: EMLFunction) -> list[str]:
        out: list[str] = ["/// " + fn.name]
        emit_warn, why = _wants_drift_warning(fn.profile)
        if fn.profile is not None and fn.profile.get("status") != "complex_body":
            cc = fn.profile.get("cost_class", "?")
            co = fn.profile.get("chain_order", "?")
            drift = fn.profile.get("fp16_drift_risk", "?")
            out.append(
                f"/// Pfaffian profile: chain_order={co}, "
                f"cost_class={cc}, drift_risk={drift}."
            )
        if emit_warn:
            out.append(f"/// WARNING: float32 drift risk -- {why}.")
        for r in fn.requires:
            try:
                out.append(f"/// - forge.requires: {self._emit_expr(r)}")
            except CompileError:
                pass
        for r in fn.ensures:
            try:
                out.append(
                    f"/// - forge.ensures: "
                    f"{self._emit_expr(r, result_subst='result')}"
                )
            except CompileError:
                pass
        for a in fn.annotations:
            if a.kind == "verify":
                tname = a.args.get("theorem", fn.name)
                out.append(f"/// - forge.verify: lean theorem={tname}")
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
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"let {_safe_ident(str(stmt.value))} = {rhs}")
            elif stmt.kind == NodeKind.LET_MUT:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"var {_safe_ident(str(stmt.value))} = {rhs}")
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{_safe_ident(str(stmt.value))} = {rhs}")
            elif stmt.kind == NodeKind.WHILE:
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(
                    stmt.children[1], return_value=False, tuple_record=None,
                )
                out.append(f"while {cond} {{")
                for ln in inner:
                    out.append(self.indent + ln)
                out.append("}")
            elif stmt.kind == NodeKind.EXPR_STMT:
                out.append(self._emit_expr(stmt.children[0]))
            elif (
                is_last and return_value
                and stmt.kind == NodeKind.TUPLE
                and tuple_record is not None
            ):
                # Swift named-init form. Each element is named eN to
                # match the struct's field declarations.
                elems = ", ".join(
                    f"e{i}: {self._emit_expr(c)}"
                    for i, c in enumerate(stmt.children)
                )
                out.append(f"return {tuple_record}({elems})")
            elif is_last and return_value:
                out.append(f"return {self._emit_expr(stmt)}")
            else:
                out.append(self._emit_expr(stmt))
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
                f"Swift backend: tuple expression outside return needs "
                f"a generated struct (got {elems})"
            )

        if kind == NodeKind.CLAMP:
            x, lo, hi = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            # Portable across Swift stdlib versions.
            return f"min(max({x}, {lo}), {hi})"

        if kind == NodeKind.POW:
            base, exp_node = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"pow({base}, {exp_node})"

        if kind == NodeKind.EML:
            x, y = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"(exp({x}) - log({y}))"

        if kind in _BUILTIN_TO_SWIFT:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_SWIFT[kind]}({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            callee = str(node.value)
            # Lower SymPy-style names + missing math via the rewrite
            # table. Helper synthesis fires here so the helper is
            # only emitted when actually needed.
            rewritten = _CALL_REWRITE.get(callee)
            if rewritten is not None:
                if rewritten in _HELPERS_BY_REWRITE:
                    self._helpers_used.add(rewritten)
                return f"{rewritten}({args})"
            # Only mangle in-module calls. External calls (Foundation
            # globals like `sin`, `cos`, `min`, `max`, or upstream
            # un-inlined helpers) pass through verbatim.
            if callee in self._in_module_names:
                return f"{_safe_ident(callee)}({args})"
            return f"{callee}({args})"

        raise CompileError(
            f"Swift backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
