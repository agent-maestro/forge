"""C# backend (Unity-ready).

Emits a single ``.cs`` file containing one ``public static class``
per EML module under the ``Forge`` namespace. Functions become
``public static`` methods decorated with
``[MethodImpl(MethodImplOptions.AggressiveInlining)]`` for hot-path
performance; module constants become ``public const double`` fields
(compile-time, zero allocation). Math routines route through
``System.Math``.

Targets the Unity / IL2CPP / .NET 6+ floor where ``Math.Clamp`` is
available and ``record struct`` is the no-allocation tuple-return
form.

Mapping
=======

  EML AST kind        ->  C# output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0"
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier (snake_case preserved -- matches
                          the Java backend convention so source-to-
                          source diffs with C / Rust stay clean)
  BINOP +/-/*//       ->  C# arithmetic
  BINOP comparisons   ->  C# comparison (yields bool)
  BINOP &&/||         ->  C# && / ||
  UNARYOP -           ->  C# unary minus
  UNARYOP !           ->  C# !
  EXP/LN/SIN/COS/...  ->  Math.Exp/Math.Log/Math.Sin/...
  ABS(x)              ->  Math.Abs(x)
  CLAMP(x, lo, hi)    ->  Math.Clamp(x, lo, hi)
  POW(x, y)           ->  Math.Pow(x, y)
  EML(x, y)           ->  (Math.Exp(x) - Math.Log(y))
  CALL                ->  static method call on the same class
  TUPLE return        ->  readonly record struct (zero-allocation)
  LET name = expr     ->  "double name = <expr>;"
  LET_MUT name = expr ->  "double name = <expr>;"
  ASSIGN name = expr  ->  "name = <expr>;"
  WHILE cond block    ->  while (<cond>) { <block> }
  BLOCK               ->  brace-enclosed sequence; final expression
                          becomes a ``return <expr>;``
  requires            ->  XML doc <forge.requires> tag (advisory --
                          we deliberately do NOT emit a runtime check
                          to keep AggressiveInlining hot)
  ensures             ->  XML doc <forge.ensures> tag (advisory)
  @verify(lean, ...)  ->  XML doc <forge.verify> line

Unity-specific header
=====================

Each generated method carries a `Unity hint:` line in its XML
docstring with the chain order and a rough cost estimate. The
estimate is a heuristic indexed by chain order; it is anchored to
desktop CPU baselines (Mono / IL2CPP) -- profile on your target
hardware before relying on the number.

Reference: lang/spec/EML_LANG_DESIGN.md + Phase 4 backend roadmap.
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


# Builtin NodeKind -> System.Math method name.
_BUILTIN_TO_CSHARP: dict[NodeKind, str] = {
    NodeKind.EXP:   "Math.Exp",
    NodeKind.LN:    "Math.Log",
    NodeKind.SIN:   "Math.Sin",
    NodeKind.COS:   "Math.Cos",
    NodeKind.TAN:   "Math.Tan",
    NodeKind.SQRT:  "Math.Sqrt",
    NodeKind.ABS:   "Math.Abs",
    NodeKind.ASIN:  "Math.Asin",
    NodeKind.ACOS:  "Math.Acos",
    NodeKind.ATAN:  "Math.Atan",
    NodeKind.SINH:  "Math.Sinh",
    NodeKind.COSH:  "Math.Cosh",
    NodeKind.TANH:  "Math.Tanh",
    NodeKind.POW:   "Math.Pow",
}


_TYPE_TO_CSHARP: dict[str, str] = {
    "Real":    "double",
    "f64":     "double",
    "f32":     "float",
    "f16":     "float",   # No native f16 in core C#; promote
    "bf16":    "float",
    "u8":      "byte",
    "u16":     "ushort",
    "u32":     "uint",
    "u64":     "ulong",
    "i8":      "sbyte",
    "i16":     "short",
    "i32":     "int",
    "i64":     "long",
    "bool":    "bool",
}


# Rough per-call cost by chain order. Anchored to desktop CPU
# (Mono / IL2CPP) baselines for the Unity main thread; profile on
# your target hardware before depending on these numbers. Used only
# for the `Unity hint:` annotation in generated doc-comments.
_CHAIN_NS_HINT: dict[int, int] = {
    0: 2,   # pure rational / polynomial
    1: 10,  # one transcendental (exp, sin, sqrt, ...)
    2: 20,  # two transcendentals (e.g. exp * cos)
    3: 30,  # three transcendentals
    4: 50,  # four+ transcendentals or nested chain
}


def _csharp_type(eml_type: str) -> str:
    return _TYPE_TO_CSHARP.get(eml_type, "double")


def _class_name(mod: EMLModule) -> str:
    """C# class names use PascalCase. Convert from snake_case.
    Mirrors the Java backend's _class_name."""
    base = mod.name or "ForgeModule"
    parts = base.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts) or "ForgeModule"


def _xml_escape(s: str) -> str:
    """Escape `<`, `>`, `&` for safe placement inside an XML doc
    comment. Required because requires/ensures expressions use
    comparison operators that the C# compiler would otherwise warn
    about (CS1570: XML comment has badly formed XML)."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _budget_hint(chain_order) -> str:
    """Format the Unity budget hint line for a function's docstring."""
    if not isinstance(chain_order, int):
        return "Unity hint: chain=? (cost unknown -- profile on target)."
    ns = _CHAIN_NS_HINT.get(chain_order, 50 + 10 * (chain_order - 4))
    if ns <= 0:
        ns = 1
    calls_per_ms = max(1, 1_000_000 // max(1, ns))
    pct_of_frame_per_1k = (1_000 * ns) / 16_000_000.0 * 100.0
    return (
        f"Unity hint: chain={chain_order}; ~{ns} ns/call "
        f"(~{calls_per_ms:,} calls/ms; ~{pct_of_frame_per_1k:.3f}% of "
        f"16 ms frame per 1000 calls -- desktop CPU baseline, "
        f"profile on target)."
    )


class CompileError(Exception):
    """Raised on a NodeKind the C# backend doesn't recognize."""


class CSharpBackend:
    """Compile an EMLModule to a single .cs source file (Unity-ready)."""

    name = "csharp"

    def __init__(
        self,
        indent: str = "    ",
        *,
        optimize: bool = True,
        namespace: str = "Forge",
    ):
        self.indent = indent
        self.optimize = optimize
        self.namespace = namespace

    def compile(self, mod: EMLModule) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        cls = _class_name(mod)
        lines: list[str] = [
            "// Generated by EML-lang C# backend (Unity-ready)",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {mod.source_file}",
            f"// Functions:     {len(mod.functions)}",
            f"// Constants:     {len(mod.constants)}",
            "//",
            "// Every method carries [MethodImpl(AggressiveInlining)]",
            "// and uses System.Math (no allocations, no GC pressure).",
            "// Tuple returns ship as readonly record struct.",
            "",
            "using System;",
            "using System.Runtime.CompilerServices;",
            "",
            f"namespace {self.namespace}",
            "{",
        ]

        # Tuple-return record structs go OUTSIDE the static class so
        # they are reusable types (and so the static class stays
        # cleanly methods-only).
        records: list[str] = []
        for fn in mod.functions:
            if fn.return_tuple_types:
                rec = self._tuple_record_name(fn.name)
                fields = ", ".join(
                    f"{_csharp_type(t)} E{i}"
                    for i, t in enumerate(fn.return_tuple_types)
                )
                records.append(
                    f"{self.indent}public readonly record struct "
                    f"{rec}({fields});"
                )
        if records:
            lines.extend(records)
            lines.append("")

        lines.append(f"{self.indent}public static class {cls}")
        lines.append(f"{self.indent}{{")

        # Constants
        body_indent = self.indent * 2
        for c in mod.constants:
            for ln in self._emit_constant(c):
                lines.append(body_indent + ln)
        if mod.constants:
            lines.append("")

        # Functions
        for fn in mod.functions:
            if fn.is_extern:
                emitted = self._emit_extern(fn)
            else:
                emitted = self._emit_function(fn)
            for ln in emitted:
                lines.append(body_indent + ln)
            lines.append("")

        lines.append(f"{self.indent}}}")
        lines.append("}")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _tuple_record_name(fn_name: str) -> str:
        """Mirror the Java backend convention: PascalCase + Result."""
        parts = fn_name.split("_")
        camel = "".join(p[:1].upper() + p[1:] for p in parts) or "Anon"
        return f"{camel}Result"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        cs_type = _csharp_type(c.type_name)
        rhs = self._emit_expr(c.value)
        # `const` requires a compile-time constant. Float literal +
        # arithmetic expressions like `(-0.349)` are NOT compile-time
        # constants in C# (the unary minus prevents constant-folding
        # at the language level), so we fall back to
        # `static readonly` for those. That keeps zero allocations
        # (single static field) without forcing the user into IL2CPP
        # constant-folding edge cases.
        if self._is_const_expr(c.value):
            return [f"public const {cs_type} {c.name} = {rhs};"]
        return [f"public static readonly {cs_type} {c.name} = {rhs};"]

    @staticmethod
    def _is_const_expr(node: ASTNode) -> bool:
        """C#'s `const` accepts only literal-shaped expressions.
        Conservative: only LITERAL nodes count."""
        return node.kind == NodeKind.LITERAL

    # ── Extern (FFI) ──────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        if fn.return_tuple_types:
            ret = self._tuple_record_name(fn.name)
        else:
            ret = _csharp_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_csharp_type(p.type_name)} {p.name}" for p in fn.params
        )
        return [
            f"// extern: {fn.name} -- supply via P/Invoke or interop",
            "[MethodImpl(MethodImplOptions.AggressiveInlining)]",
            f"public static {ret} {fn.name}({params})",
            "{",
            f"{self.indent}throw new NotImplementedException("
            f"\"{fn.name}: extern not bound\");",
            "}",
        ]

    # ── Function emit ─────────────────────────────────────────

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        out: list[str] = self._xmldoc(fn)
        out.append("[MethodImpl(MethodImplOptions.AggressiveInlining)]")
        if fn.return_tuple_types:
            ret = self._tuple_record_name(fn.name)
        else:
            ret = _csharp_type(fn.return_type or "Real")
        params = ", ".join(
            f"{_csharp_type(p.type_name)} {p.name}" for p in fn.params
        )

        # Try expression-bodied form when there are no preconditions
        # (advisory only in our backend) and no tuple wrap. C#
        # expression-bodied members compile to the same IL as a body
        # with a single return; AggressiveInlining still applies.
        is_pure_expr = self._is_pure_expression_body(fn.body)
        if is_pure_expr and not fn.return_tuple_types:
            try:
                expr = self._emit_expr(self._final_expression(fn.body))
                out.append(f"public static {ret} {fn.name}({params}) => {expr};")
                return out
            except CompileError:
                pass

        out.append(f"public static {ret} {fn.name}({params})")
        out.append("{")
        record = (
            self._tuple_record_name(fn.name) if fn.return_tuple_types else None
        )
        body = self._emit_block(fn.body, return_value=True, tuple_record=record)
        for ln in body:
            out.append(self.indent + ln)
        out.append("}")
        return out

    @staticmethod
    def _is_pure_expression_body(body: ASTNode | None) -> bool:
        if body is None or body.kind != NodeKind.BLOCK:
            return False
        return (
            len(body.children) == 1
            and body.children[0].kind not in (
                NodeKind.LET, NodeKind.LET_MUT,
                NodeKind.ASSIGN, NodeKind.WHILE,
                NodeKind.EXPR_STMT,
            )
        )

    @staticmethod
    def _final_expression(body: ASTNode) -> ASTNode:
        return body.children[-1]

    # ── XML doc comment ───────────────────────────────────────

    def _xmldoc(self, fn: EMLFunction) -> list[str]:
        out: list[str] = ["/// <summary>"]
        out.append(f"/// {fn.name}")
        out.append("/// </summary>")

        # Profile + Unity budget hint
        profile_lines: list[str] = []
        chain_order = None
        if fn.profile is not None and fn.profile.get("status") != "complex_body":
            cc = fn.profile.get("cost_class", "?")
            chain_order = fn.profile.get("chain_order")
            co_str = chain_order if chain_order is not None else "?"
            drift = fn.profile.get("fp16_drift_risk", "?")
            profile_lines.append(
                f"Pfaffian profile: chain_order={co_str}, "
                f"cost_class={cc}, drift_risk={drift}."
            )
        profile_lines.append(_budget_hint(chain_order))

        # `requires` and `ensures` arrive as XML doc comments. We do
        # NOT emit runtime checks because runtime validation costs a
        # branch per call and AggressiveInlining + Unity hot-path
        # convention prefers caller-side validation.
        contract_lines: list[str] = []
        for r in fn.requires:
            try:
                contract_lines.append(
                    f"forge.requires: {_xml_escape(self._emit_expr(r))}"
                )
            except CompileError:
                pass
        for r in fn.ensures:
            try:
                contract_lines.append(
                    "forge.ensures: "
                    + _xml_escape(self._emit_expr(r, result_subst="result"))
                )
            except CompileError:
                pass
        for a in fn.annotations:
            if a.kind == "verify":
                tname = a.args.get("theorem", fn.name)
                contract_lines.append(
                    f"forge.verify: lean theorem={_xml_escape(str(tname))}"
                )

        all_remarks = profile_lines + contract_lines
        if all_remarks:
            out.append("/// <remarks>")
            for ln in all_remarks:
                out.append(f"/// {ln}")
            out.append("/// </remarks>")

        for p in fn.params:
            out.append(
                f'/// <param name="{_xml_escape(p.name)}">'
                f"type {_xml_escape(p.type_name)}</param>"
            )
        out.append(
            f"/// <returns>{_xml_escape(fn.return_type or 'Real')}</returns>"
        )
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
                cs_type = _csharp_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{cs_type} {stmt.value} = {rhs};")
            elif stmt.kind == NodeKind.LET_MUT:
                cs_type = _csharp_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{cs_type} {stmt.value} = {rhs};")
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{stmt.value} = {rhs};")
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
                # Tuple-return: wrap the final TUPLE in
                # `new RecordName(elem0, elem1, ...)`.
                elems = ", ".join(self._emit_expr(c) for c in stmt.children)
                out.append(f"return new {tuple_record}({elems});")
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
                return s
            raise CompileError(f"unsupported literal: {v!r}")

        if kind == NodeKind.VAR:
            name = str(node.value)
            if result_subst is not None and name == "result":
                return result_subst
            return name

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
            # C# *does* have first-class value tuples (`(a, b)`)
            # but for tuple returns the readonly record struct
            # produces nicer field names and IL. The wrapper is
            # applied in _emit_block when return_value && tuple_record.
            # If we hit a TUPLE in expression position outside a
            # return slot, fall back to a value tuple.
            elems = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"({elems})"

        if kind == NodeKind.CLAMP:
            x, lo, hi = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            # Math.Clamp is .NET 6+; widely available in Unity 2021.2+
            # under .NET Standard 2.1 / .NET 6 IL2CPP.
            return f"Math.Clamp({x}, {lo}, {hi})"

        if kind == NodeKind.EML:
            x, y = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"(Math.Exp({x}) - Math.Log({y}))"

        if kind in _BUILTIN_TO_CSHARP:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_CSHARP[kind]}({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{node.value}({args})"

        raise CompileError(
            f"C# backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
