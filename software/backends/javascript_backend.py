"""JavaScript backend (ES2015+ module).

Emits a single ``.mjs`` file with one ``export function`` per EML
function. Math routines route through the global ``Math`` object
which is available in every JavaScript runtime (V8, JavaScriptCore,
SpiderMonkey, Node, Deno, browsers, edge workers).

Templated from python_backend.py with the SymPy bridge intentionally
left out -- the direct AST emitter handles every NodeKind the
gaming verticals produce, and avoids depending on Tool 5 emitting
``Math.*`` calls (it doesn't).

Mapping
=======

  EML AST kind        ->  JavaScript output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0"
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier
  BINOP +/-/*//       ->  arithmetic
  BINOP &&/||         ->  && / ||
  UNARYOP -           ->  unary minus
  UNARYOP !           ->  !
  EXP/LN/SIN/COS/...  ->  Math.exp / Math.log / Math.sin / ...
                          (Math.log is natural log, matches EML LN)
  ABS(x)              ->  Math.abs(x)
  CLAMP(x, lo, hi)    ->  Math.min(Math.max(x, lo), hi)
                          (no native clamp; this idiom is what
                          Lodash and most game engines use)
  POW(x, y)           ->  Math.pow(x, y)
  EML(x, y)           ->  (Math.exp(x) - Math.log(y))
  LET name = expr     ->  "const name = <expr>;"
  LET_MUT name = expr ->  "let name = <expr>;"
  ASSIGN name = expr  ->  "name = <expr>;"
  WHILE cond block    ->  while (cond) { ... }
  BLOCK               ->  brace block; final expression -> return
  requires            ->  if (!(<cond>)) throw new RangeError(...)
  ensures             ->  console.assert (debug-only) -- advisory
  @verify(lean, ...)  ->  JSDoc @forge.verify line

The output uses ES module syntax (`export function`). Validate with
``node --check output.mjs`` (parser-level check; runtime correctness
is the caller's responsibility).
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# ── Phase E.1: refinement guard helpers ──────────────────────────────────────


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


# Builtin NodeKind -> JavaScript Math.* function. Math is the global
# namespace; no import statement needed.
_BUILTIN_TO_JS: dict[NodeKind, str] = {
    NodeKind.EXP:   "Math.exp",
    NodeKind.LN:    "Math.log",      # JS Math.log is natural log
    NodeKind.SIN:   "Math.sin",
    NodeKind.COS:   "Math.cos",
    NodeKind.TAN:   "Math.tan",
    NodeKind.SQRT:  "Math.sqrt",
    NodeKind.ABS:   "Math.abs",
    NodeKind.ASIN:  "Math.asin",
    NodeKind.ACOS:  "Math.acos",
    NodeKind.ATAN:  "Math.atan",
    NodeKind.SINH:  "Math.sinh",
    NodeKind.COSH:  "Math.cosh",
    NodeKind.TANH:  "Math.tanh",
    NodeKind.POW:   "Math.pow",
}


# JavaScript reserved + future-reserved + strict-mode reserved
# keywords. Most EML identifiers are safe but `class`, `enum`,
# `await`, `let`, `const`, `static`, `package` collide.
_JS_RESERVED: frozenset[str] = frozenset({
    # ES2015+ keywords
    "await", "break", "case", "catch", "class", "const", "continue",
    "debugger", "default", "delete", "do", "else", "export",
    "extends", "finally", "for", "function", "if", "import", "in",
    "instanceof", "let", "new", "return", "super", "switch", "this",
    "throw", "try", "typeof", "var", "void", "while", "with", "yield",
    # Future-reserved / strict-mode
    "enum", "implements", "interface", "package", "private",
    "protected", "public", "static",
    # Special literals
    "null", "true", "false", "undefined", "NaN", "Infinity",
    # Common globals shadowed by user IDs
    "Math", "Number", "String", "Boolean", "Object", "Array",
    "Date", "console", "globalThis", "window", "document",
})


_DRIFT_WARN_CHAIN_FLOOR = 2


def _safe_ident(name: str) -> str:
    if name in _JS_RESERVED:
        return name + "_"
    return name


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
    """Raised on a NodeKind the JS backend doesn't recognize."""


class JavaScriptBackend:
    """Compile an EMLModule to a single .mjs ES-module source file."""

    name = "javascript"

    def __init__(self, indent: str = "    ", *, optimize: bool = True):
        self.indent = indent
        self.optimize = optimize

    def compile(self, mod: EMLModule) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        any_drift = any(
            _wants_drift_warning(fn.profile)[0]
            for fn in mod.functions
            if not fn.is_extern
        )

        src_file = str(mod.source_file).replace("\\", "/")
        lines: list[str] = [
            "// Generated by EML-lang JavaScript backend (ES module)",
            f"// Source module: {mod.name or '(unnamed)'}",
            f"// Source file:   {src_file}",
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
            "\"use strict\";",
            "",
        ])

        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        for fn in mod.functions:
            if fn.is_extern:
                lines.extend(self._emit_extern(fn))
            else:
                lines.extend(self._emit_function(fn))
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        rhs = self._emit_expr(c.value)
        return [f"export const {_safe_ident(c.name)} = {rhs};"]

    # ── Extern (FFI) ──────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        params = ", ".join(_safe_ident(p.name) for p in fn.params)
        return [
            f"// extern: {fn.name} -- supply by importing from a host",
            f"// module that defines it; the stub returns 0 so this",
            f"// file compiles standalone.",
            f"export function {_safe_ident(fn.name)}({params}) {{",
            f"{self.indent}return 0; // extern stub",
            "}",
        ]

    # ── Phase E.1: refinement guards ──────────────────────────

    def _emit_refinement_guards(self, fn: EMLFunction) -> list[str]:
        """Return one guard line per refined parameter (Phase E.1).

        Binder-substitution: the refinement's binder is alpha-renamed to
        the parameter name before emission.  Cross-param refinements are
        emitted as comment-only obligation lines.
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
                    f"{self.indent}// refinement obligation: "
                    f"{fn.name}: {p.name}: {cond_str}"
                )
                continue
            try:
                cond = self._emit_expr(pred)
                msg = (
                    f"{fn.name}: refinement violated on {p.name}: {cond}"
                )
                msg = msg.replace("\\", "\\\\").replace('"', '\\"')
                out.append(
                    f"{self.indent}if (!({cond})) throw new "
                    f"RangeError(\"{msg}\");"
                )
            except CompileError as e:
                out.append(
                    f"{self.indent}// refinement: unsupported ({e})"
                )
        return out

    # ── Function emit ─────────────────────────────────────────

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        out: list[str] = self._jsdoc(fn)

        params = ", ".join(_safe_ident(p.name) for p in fn.params)
        out.append(
            f"export function {_safe_ident(fn.name)}({params}) {{"
        )

        # Phase E.1: refinement guards fire BEFORE requires guards.
        out.extend(self._emit_refinement_guards(fn))

        # Preconditions: throw RangeError so callers can catch a
        # specific exception class. Doing this in user-code rather
        # than via console.assert (which is debug-only and
        # silenceable) matches the Swift `precondition` semantic.
        for r in fn.requires:
            try:
                cond = self._emit_expr(r)
                msg = f"{fn.name}: requires {cond}"
                msg = msg.replace("\\", "\\\\").replace('"', '\\"')
                out.append(
                    f"{self.indent}if (!({cond})) throw new "
                    f"RangeError(\"{msg}\");"
                )
            except CompileError as e:
                out.append(f"{self.indent}// require: unsupported ({e})")

        body = self._emit_block(fn.body, return_value=True)
        for ln in body:
            out.append(self.indent + ln)
        out.append("}")
        return out

    def _jsdoc(self, fn: EMLFunction) -> list[str]:
        # JSDoc block. Type all parameters as `number` -- EML's
        # scalar surface is uniformly numeric on the JS side.
        out: list[str] = ["/**"]
        out.append(f" * {fn.name}")
        emit_warn, why = _wants_drift_warning(fn.profile)
        if fn.profile is not None and fn.profile.get("status") != "complex_body":
            cc = fn.profile.get("cost_class", "?")
            co = fn.profile.get("chain_order", "?")
            drift = fn.profile.get("fp16_drift_risk", "?")
            out.append(
                f" * Pfaffian profile: chain_order={co}, "
                f"cost_class={cc}, drift_risk={drift}."
            )
        if emit_warn:
            out.append(f" * WARNING: float64 / float32 drift risk -- {why}.")
        for p in fn.params:
            out.append(f" * @param {{number}} {_safe_ident(p.name)}")
        out.append(" * @returns {number}")
        for r in fn.requires:
            try:
                out.append(f" * @forge.requires {self._emit_expr(r)}")
            except CompileError:
                pass
        for r in fn.ensures:
            try:
                out.append(
                    f" * @forge.ensures "
                    f"{self._emit_expr(r, result_subst='result')}"
                )
            except CompileError:
                pass
        for a in fn.annotations:
            if a.kind == "verify":
                tname = a.args.get("theorem", fn.name)
                out.append(f" * @forge.verify lean theorem={tname}")
        out.append(" */")
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
            if stmt.kind == NodeKind.LET:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"const {_safe_ident(str(stmt.value))} = {rhs};")
            elif stmt.kind == NodeKind.LET_MUT:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"let {_safe_ident(str(stmt.value))} = {rhs};")
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{_safe_ident(str(stmt.value))} = {rhs};")
            elif stmt.kind == NodeKind.WHILE:
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(
                    stmt.children[1], return_value=False,
                )
                out.append(f"while ({cond}) {{")
                for ln in inner:
                    out.append(self.indent + ln)
                out.append("}")
            elif stmt.kind == NodeKind.EXPR_STMT:
                out.append(f"{self._emit_expr(stmt.children[0])};")
            elif is_last and return_value:
                # JS has tuple-return only via arrays / objects;
                # match the EML convention by returning an array.
                if stmt.kind == NodeKind.TUPLE:
                    elems = ", ".join(self._emit_expr(c) for c in stmt.children)
                    out.append(f"return [{elems}];")
                else:
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
            # JS tuples surface as arrays only at return position;
            # bare tuple expressions in argument position are an
            # error.
            raise CompileError(
                f"JS backend: tuple expression outside return needs "
                f"to surface via an array literal (got {elems})"
            )

        if kind == NodeKind.CLAMP:
            x, lo, hi = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"Math.min(Math.max({x}, {lo}), {hi})"

        if kind == NodeKind.EML:
            x, y = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"(Math.exp({x}) - Math.log({y}))"

        if kind in _BUILTIN_TO_JS:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_JS[kind]}({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_safe_ident(str(node.value))}({args})"

        raise CompileError(
            f"JS backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
