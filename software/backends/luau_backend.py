"""Luau backend (Roblox's typed Lua).

Emits a single ``.luau`` file with one ``function M.name(...)`` per
EML function, stitched into a module table at the end. Math routines
route through the global ``math`` table that ships with both
standard Lua 5.x and Roblox's Luau runtime.

Templated from python_backend.py with these adaptations:
  - `local function` (top-level) and `function M.name(...)` (module
    methods) instead of `def`
  - `math.exp(x)` etc. (lowercase, period-namespaced)
  - `^` operator instead of `math.pow(x, y)` -- Luau's idiom
  - `--` line comments, `--[[ ]]` block comments
  - `local` keyword required for ALL non-export bindings
  - Trailing `return M` so the file works as a Lua module
  - Type annotations: `function M.f(x: number): number`
  - No native `clamp` (synthesize as `math.min(math.max(x, lo), hi)`;
    the Roblox runtime adds `math.clamp` but we keep portability
    with vanilla Lua 5.x)

Mapping
=======

  EML AST kind        ->  Luau output
  ─────────────────────────────────────────
  LITERAL int         ->  "42"
  LITERAL float       ->  "42.0"
  LITERAL bool        ->  "true" / "false"
  VAR                 ->  identifier
  BINOP +/-/*//       ->  arithmetic
  BINOP &&             ->  `and`
  BINOP ||             ->  `or`
  UNARYOP -            ->  unary minus
  UNARYOP !            ->  `not`
  EXP/LN/SIN/COS/...   ->  math.exp / math.log / math.sin / ...
                          (math.log is natural log)
  ABS(x)               ->  math.abs(x)
  CLAMP(x, lo, hi)     ->  math.min(math.max(x, lo), hi)
  POW(x, y)            ->  (x ^ y)              (Luau idiom)
  EML(x, y)            ->  (math.exp(x) - math.log(y))
  LET name = expr      ->  "local name = <expr>"
  LET_MUT name = expr  ->  "local name = <expr>"
                          (Lua has no const/let/var distinction;
                          local handles both)
  ASSIGN name = expr   ->  "name = <expr>"
  WHILE cond block     ->  while <cond> do ... end
  BLOCK                ->  block; final expression -> `return <expr>`
  requires             ->  assert(<cond>, "...")
  ensures              ->  --[[ comment-only advisory ]]
  @verify(lean, ...)   ->  -- comment annotation

The output is loadable via Roblox's `require()`, Lune, vanilla Lua
5.1+, or any Luau runtime.
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


_BUILTIN_TO_LUAU: dict[NodeKind, str] = {
    NodeKind.EXP:   "math.exp",
    NodeKind.LN:    "math.log",      # math.log is natural log
    NodeKind.SIN:   "math.sin",
    NodeKind.COS:   "math.cos",
    NodeKind.TAN:   "math.tan",
    NodeKind.SQRT:  "math.sqrt",
    NodeKind.ABS:   "math.abs",
    NodeKind.ASIN:  "math.asin",
    NodeKind.ACOS:  "math.acos",
    NodeKind.ATAN:  "math.atan",
    # math.sinh / cosh / tanh ARE present on Luau (Roblox extension)
    # but were removed from vanilla Lua 5.3+. We emit them and let
    # the caller verify their runtime is Luau or Lua 5.1/5.2.
    NodeKind.SINH:  "math.sinh",
    NodeKind.COSH:  "math.cosh",
    NodeKind.TANH:  "math.tanh",
}


# Lua / Luau reserved words. Note Lua's keyword set is tiny -- mostly
# control flow + boolean / nil literals. The Luau extensions add a
# few more (`continue`, `type`, `export`).
_LUAU_RESERVED: frozenset[str] = frozenset({
    # Lua 5.x keywords
    "and", "break", "do", "else", "elseif", "end", "false", "for",
    "function", "goto", "if", "in", "local", "nil", "not", "or",
    "repeat", "return", "then", "true", "until", "while",
    # Luau additions
    "continue", "type", "export",
    # Standard library globals that would shadow if used as IDs
    "math", "string", "table", "os", "io", "print", "ipairs",
    "pairs", "tostring", "tonumber", "select", "type",
    "assert", "error", "pcall", "xpcall", "rawget", "rawset",
    "rawequal", "setmetatable", "getmetatable",
})


_DRIFT_WARN_CHAIN_FLOOR = 2


def _safe_ident(name: str) -> str:
    if name in _LUAU_RESERVED:
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
    """Raised on a NodeKind the Luau backend doesn't recognize."""


class LuauBackend:
    """Compile an EMLModule to a single .luau module file."""

    name = "luau"

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
            "-- Generated by EML-lang Luau backend",
            f"-- Source module: {mod.name or '(unnamed)'}",
            f"-- Source file:   {src_file}",
            f"-- Functions:     {len(mod.functions)}",
            f"-- Constants:     {len(mod.constants)}",
        ]
        if any_drift:
            lines.append("--")
            lines.append(
                "-- At least one function in this module has chain_order "
                f">= {_DRIFT_WARN_CHAIN_FLOOR}; per-function drift"
            )
            lines.append(
                "-- warnings appear inline above each affected function."
            )
        lines.extend([
            "",
            "local M = {}",
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

        lines.append("return M")
        return "\n".join(lines).rstrip() + "\n"

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        rhs = self._emit_expr(c.value)
        # Constants live both on the module table (for external
        # callers) and as a local (for in-file lookups, since
        # `M.NAME` requires a table dereference at every use).
        return [
            f"local {_safe_ident(c.name)} = {rhs}",
            f"M.{_safe_ident(c.name)} = {_safe_ident(c.name)}",
        ]

    # ── Extern (FFI) ──────────────────────────────────────────

    def _emit_extern(self, fn: EMLFunction) -> list[str]:
        params = ", ".join(
            f"{_safe_ident(p.name)}: number" for p in fn.params
        )
        return [
            f"-- extern: {fn.name} -- supply by overriding M.{fn.name}",
            f"-- before requiring this module; the stub returns 0.",
            f"function M.{_safe_ident(fn.name)}({params}): number",
            f"{self.indent}return 0 -- extern stub",
            "end",
        ]

    # ── Phase E.1: refinement guards ──────────────────────────

    def _emit_refinement_guards(self, fn: EMLFunction) -> list[str]:
        """Return one assert line per refined parameter (Phase E.1).

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
                    f"{self.indent}-- refinement obligation: "
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
                    f'{self.indent}assert({cond}, "{msg}")'
                )
            except CompileError as e:
                out.append(
                    f"{self.indent}-- refinement: unsupported ({e})"
                )
        return out

    # ── Function emit ─────────────────────────────────────────

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        out: list[str] = self._docstring(fn)

        params = ", ".join(
            f"{_safe_ident(p.name)}: number" for p in fn.params
        )
        # Luau type annotations: `function M.f(x: number): number`.
        out.append(
            f"function M.{_safe_ident(fn.name)}({params}): number"
        )

        # Phase E.1: refinement guards fire BEFORE requires guards.
        out.extend(self._emit_refinement_guards(fn))

        # Preconditions via Lua's assert. Includes a message so the
        # stack trace surfaces the contract that failed.
        for r in fn.requires:
            try:
                cond = self._emit_expr(r)
                msg = f"{fn.name}: requires {cond}"
                msg = msg.replace("\\", "\\\\").replace('"', '\\"')
                out.append(
                    f'{self.indent}assert({cond}, "{msg}")'
                )
            except CompileError as e:
                out.append(f"{self.indent}-- require: unsupported ({e})")

        # Phase G: `assume` clauses -- trusted hypotheses, zero runtime cost.
        for a in fn.assumes:
            try:
                out.append(f"{self.indent}-- assume: {self._emit_expr(a)}")
            except CompileError as e:
                out.append(f"{self.indent}-- assume: unsupported ({e})")

        body = self._emit_block(fn.body, return_value=True)
        for ln in body:
            out.append(self.indent + ln)
        out.append("end")
        return out

    def _docstring(self, fn: EMLFunction) -> list[str]:
        out: list[str] = [f"-- {fn.name}"]
        emit_warn, why = _wants_drift_warning(fn.profile)
        if fn.profile is not None and fn.profile.get("status") != "complex_body":
            cc = fn.profile.get("cost_class", "?")
            co = fn.profile.get("chain_order", "?")
            drift = fn.profile.get("fp16_drift_risk", "?")
            out.append(
                f"--   Pfaffian profile: chain_order={co}, "
                f"cost_class={cc}, drift_risk={drift}."
            )
        if emit_warn:
            out.append(f"--   WARNING: float drift risk -- {why}.")
        for r in fn.requires:
            try:
                out.append(f"--   forge.requires: {self._emit_expr(r)}")
            except CompileError:
                pass
        for r in fn.ensures:
            try:
                out.append(
                    f"--   forge.ensures: "
                    f"{self._emit_expr(r, result_subst='result')}"
                )
            except CompileError:
                pass
        for a in fn.annotations:
            if a.kind == "verify":
                tname = a.args.get("theorem", fn.name)
                out.append(f"--   forge.verify: lean theorem={tname}")
        return out

    # ── Statements ────────────────────────────────────────────

    def _emit_block(
        self,
        block: ASTNode | None,
        *,
        return_value: bool,
    ) -> list[str]:
        if block is None or block.kind != NodeKind.BLOCK:
            return ["-- empty body"]
        out: list[str] = []
        for i, stmt in enumerate(block.children):
            is_last = (i == len(block.children) - 1)
            if stmt.kind in (NodeKind.LET, NodeKind.LET_MUT):
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"local {_safe_ident(str(stmt.value))} = {rhs}")
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                out.append(f"{_safe_ident(str(stmt.value))} = {rhs}")
            elif stmt.kind == NodeKind.WHILE:
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(
                    stmt.children[1], return_value=False,
                )
                out.append(f"while {cond} do")
                for ln in inner:
                    out.append(self.indent + ln)
                out.append("end")
            elif stmt.kind == NodeKind.EXPR_STMT:
                out.append(self._emit_expr(stmt.children[0]))
            elif is_last and return_value:
                if stmt.kind == NodeKind.TUPLE:
                    elems = ", ".join(self._emit_expr(c) for c in stmt.children)
                    # Lua supports multiple return values directly.
                    out.append(f"return {elems}")
                else:
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
                return f"(not {sub})"
            raise CompileError(f"unsupported unary op: {node.value!r}")

        if kind == NodeKind.BINOP:
            left = self._emit_expr(node.children[0], result_subst=result_subst)
            right = self._emit_expr(node.children[1], result_subst=result_subst)
            op = node.value
            if op == "&&":
                op = "and"
            elif op == "||":
                op = "or"
            elif op == "!=":
                op = "~="     # Lua's not-equal operator
            return f"({left} {op} {right})"

        if kind == NodeKind.TUPLE:
            elems = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            raise CompileError(
                f"Luau backend: tuple expression outside return needs "
                f"to surface via multi-return (got {elems})"
            )

        if kind == NodeKind.CLAMP:
            x, lo, hi = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"math.min(math.max({x}, {lo}), {hi})"

        if kind == NodeKind.POW:
            base, exp_node = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"({base} ^ {exp_node})"

        if kind == NodeKind.EML:
            x, y = (
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"(math.exp({x}) - math.log({y}))"

        if kind in _BUILTIN_TO_LUAU:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"{_BUILTIN_TO_LUAU[kind]}({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            # In-module calls go through the module table M.
            callee = str(node.value)
            return f"M.{_safe_ident(callee)}({args})"

        raise CompileError(
            f"Luau backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )
