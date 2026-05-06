"""Ada / SPARK 2014 backend -- emits Ada package spec + body.

DO-178C-grade output. Maps EML-lang `requires` / `ensures` clauses
onto SPARK Pre / Post aspects, the closest natural equivalent in
the Ada world. The `@verify(lean, theorem = "...")` annotation
becomes a comment header pointing back to the Lean obligation;
SPARK's own gnatprove can later discharge the Pre/Post pair
independently of the Lean proof.

Output shape
============

`AdaBackend.compile_full(mod)` returns an `AdaArtifact` with two
strings: `spec` (the `.ads` file) and `body` (the `.adb` file).
`AdaBackend.compile(mod)` is a convenience that returns both
concatenated with a clear ASCII banner separator -- useful when
you want a single string to dump to stdout. The CLI's
`--target=ada` path writes both files side-by-side.

Mapping
=======

  EML AST kind        →  Ada output
  ─────────────────────────────────────
  LITERAL int         →  "42"
  LITERAL float       →  "42.0"
  LITERAL bool        →  "True" / "False"
  VAR                 →  identifier (snake_case preserved)
  BINOP +/-/*//       →  Ada arithmetic
  BINOP comparisons   →  Ada comparison (yields Boolean)
  BINOP &&/||         →  Ada `and then` / `or else`
  UNARYOP -           →  Ada unary minus
  UNARYOP !           →  Ada `not`
  EXP/LN/SIN/COS/...  →  Ada.Numerics.Long_Elementary_Functions.Exp/Log/Sin/...
  ABS(x)              →  `abs x`  (Ada is built-in operator)
  CLAMP(x, lo, hi)    →  Long_Float'Min(hi, Long_Float'Max(lo, x))
  CALL                →  user-function call
  LET name = expr     →  declare block local constant
  LET_MUT name = expr →  declare block local variable
  ASSIGN name = expr  →  Ada assignment
  WHILE cond block    →  while cond loop / end loop
  BLOCK               →  declare/begin/return/end sequence
  requires / ensures  →  with Pre => ... , Post => ...

Reference: lang/spec/EML_LANG_DESIGN.md + the Phase 1 backend
expansion roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# ── Phase E.5: refinement guard helpers ──────────────────────────────────────


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


# Builtin NodeKind -> Ada elementary-functions name. The package
# `Ada.Numerics.Long_Elementary_Functions` (specialised for
# Long_Float) provides all of these.
_BUILTIN_TO_ADA: dict[NodeKind, str] = {
    NodeKind.EXP:   "Exp",
    NodeKind.LN:    "Log",
    NodeKind.SIN:   "Sin",
    NodeKind.COS:   "Cos",
    NodeKind.TAN:   "Tan",
    NodeKind.SQRT:  "Sqrt",
    NodeKind.ASIN:  "Arcsin",
    NodeKind.ACOS:  "Arccos",
    NodeKind.ATAN:  "Arctan",
    NodeKind.SINH:  "Sinh",
    NodeKind.COSH:  "Cosh",
    NodeKind.TANH:  "Tanh",
    NodeKind.POW:   "**",   # Ada has native ** operator
}

# EML type -> Ada type. We default the analytical types to
# Long_Float (IEEE-754 binary64) since DO-178C teams typically
# want explicit precision rather than the implementation-defined
# Float.
_TYPE_TO_ADA: dict[str, str] = {
    "Real": "Long_Float",
    "f64":  "Long_Float",
    "f32":  "Float",
    "f16":  "Float",   # No native f16; promote
    "bf16": "Float",
    "u8":   "Interfaces.Unsigned_8",
    "u16":  "Interfaces.Unsigned_16",
    "u32":  "Interfaces.Unsigned_32",
    "u64":  "Interfaces.Unsigned_64",
    "i8":   "Interfaces.Integer_8",
    "i16":  "Interfaces.Integer_16",
    "i32":  "Interfaces.Integer_32",
    "i64":  "Interfaces.Integer_64",
    "bool": "Boolean",
}


def _ada_type(eml_type: str) -> str:
    return _TYPE_TO_ADA.get(eml_type, "Long_Float")


def _ada_ident(name: str) -> str:
    """Ada identifiers are case-insensitive but conventionally
    Mixed_Case for types/packages and lowercase for vars. EML
    uses snake_case; we keep it as-is since GNAT accepts it.
    Reserved-word collisions get an `_` suffix."""
    # Ada 2012 reserved words — the subset that EML identifiers
    # might realistically collide with.
    reserved = {
        "abs", "abstract", "accept", "access", "all", "and", "array",
        "at", "begin", "body", "case", "constant", "declare", "delay",
        "delta", "digits", "do", "else", "elsif", "end", "entry",
        "exception", "exit", "for", "function", "generic", "goto",
        "if", "in", "interface", "is", "limited", "loop", "mod", "new",
        "not", "null", "of", "or", "others", "out", "overriding",
        "package", "pragma", "private", "procedure", "protected",
        "raise", "range", "record", "rem", "renames", "requeue",
        "return", "reverse", "select", "separate", "some", "subtype",
        "synchronized", "tagged", "task", "terminate", "then", "type",
        "until", "use", "when", "while", "with", "xor",
    }
    if name.lower() in reserved:
        return name + "_"
    return name


def _module_name(mod: EMLModule) -> str:
    """Ada package names use Title_Case. EML module names are
    snake_case; convert."""
    base = mod.name or "Forge_Module"
    parts = base.split("_")
    return "".join(p[:1].upper() + p[1:].lower() for p in parts) or "Forge_Module"


@dataclass(frozen=True)
class AdaArtifact:
    """Result of compile_full -- spec (.ads) + body (.adb) text."""
    spec: str
    body: str
    package_name: str


class CompileError(Exception):
    """Raised on a NodeKind the Ada backend doesn't recognize."""


class AdaBackend:
    """Compile an EMLModule to Ada / SPARK source."""

    name = "ada"

    def __init__(self, indent: str = "   ", *, optimize: bool = True):
        # Ada's conventional indent is 3 spaces (GNAT default).
        self.indent = indent
        self.optimize = optimize

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule) -> str:
        art = self.compile_full(mod)
        sep = "-" * 70
        return (
            f"-- {sep}\n"
            f"-- SPEC -- save as {art.package_name.lower()}.ads\n"
            f"-- {sep}\n\n"
            f"{art.spec}\n"
            f"-- {sep}\n"
            f"-- BODY -- save as {art.package_name.lower()}.adb\n"
            f"-- {sep}\n\n"
            f"{art.body}"
        )

    def compile_full(self, mod: EMLModule) -> AdaArtifact:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)
        pkg = _module_name(mod)

        spec = self._emit_spec(mod, pkg)
        body = self._emit_body(mod, pkg)
        return AdaArtifact(spec=spec, body=body, package_name=pkg)

    # ── Spec emit ─────────────────────────────────────────────

    def _emit_spec(self, mod: EMLModule, pkg: str) -> str:
        lines: list[str] = self._file_header(mod, kind="spec")
        lines += [
            "pragma SPARK_Mode (On);",
            "",
            f"package {pkg} is",
            "",
        ]

        # Constants in spec (visible to callers).
        for c in mod.constants:
            lines.append(self.indent + self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Function signatures only (with Pre/Post aspects).
        for fn in mod.functions:
            if fn.is_extern:
                continue
            sig = self._emit_function_signature(fn)
            for ln in sig:
                lines.append(self.indent + ln)
            lines.append("")

        lines.append(f"end {pkg};")
        return "\n".join(lines).rstrip() + "\n"

    # ── Body emit ─────────────────────────────────────────────

    def _emit_body(self, mod: EMLModule, pkg: str) -> str:
        lines: list[str] = self._file_header(mod, kind="body")
        lines += [
            "pragma SPARK_Mode (On);",
            "",
            "with Ada.Numerics.Long_Elementary_Functions;",
            "use  Ada.Numerics.Long_Elementary_Functions;",
            "",
            f"package body {pkg} is",
            "",
        ]

        for fn in mod.functions:
            if fn.is_extern:
                continue
            for ln in self._emit_function_body(fn):
                lines.append(self.indent + ln)
            lines.append("")

        lines.append(f"end {pkg};")
        return "\n".join(lines).rstrip() + "\n"

    # ── File header (same on both spec + body) ────────────────

    def _file_header(self, mod: EMLModule, *, kind: str) -> list[str]:
        return [
            f"-- Generated by EML-lang Ada/SPARK backend ({kind})",
            f"-- Source module: {mod.name or '(unnamed)'}",
            f"-- Source file:   {mod.source_file}",
            f"-- Functions:     {len(mod.functions)}",
            f"-- Constants:     {len(mod.constants)}",
            "",
        ]

    # ── Constants ─────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> str:
        ada_type = _ada_type(c.type_name)
        rhs = self._emit_expr(c.value)
        return f"{_ada_ident(c.name)} : constant {ada_type} := {rhs};"

    # ── Function signature (spec) ─────────────────────────────

    def _emit_function_signature(self, fn: EMLFunction) -> list[str]:
        out: list[str] = self._profile_comment(fn)

        sig_head = self._function_head(fn)
        out.append(f"{sig_head}")

        # Split contract clauses (Pre/Post) from trailing comments
        # so we can punctuate the aspect list cleanly without
        # tacking a `,` or `;` onto a comment line.
        contract = self._contract_lines(fn)
        clauses = [ln for ln in contract if not ln.lstrip().startswith("--")]
        notes   = [ln for ln in contract if ln.lstrip().startswith("--")]
        if clauses:
            out.append(self.indent + "with")
            for i, ln in enumerate(clauses):
                suffix = "," if i < len(clauses) - 1 else ";"
                out.append(self.indent * 2 + ln + suffix)
            for ln in notes:
                out.append(self.indent * 2 + ln)
        else:
            # No contract -- close the declaration.
            out[-1] = out[-1] + ";"
            for ln in notes:
                out.append(self.indent + ln)
        return out

    # ── Function body (.adb) ──────────────────────────────────

    def _emit_function_body(self, fn: EMLFunction) -> list[str]:
        sig_head = self._function_head(fn)
        out: list[str] = [f"{sig_head} is"]
        out.append("begin")
        # Phase G: assume clauses.
        # GNAT pragma Assume (Boolean_Expr) is the natural Ada equivalent:
        # it tells SPARK GNATprove to treat the predicate as a known fact
        # without generating a runtime check.  If the predicate contains
        # transcendentals that Ada cannot evaluate at compile time, fall back
        # to a comment-only line so the body remains syntactically valid.
        for a in fn.assumes:
            try:
                pred = self._emit_expr(a)
                out.append(self.indent + f"pragma Assume ({pred});")
            except CompileError as e:
                out.append(self.indent + f"-- assume: unsupported ({e})")
            except Exception as e:
                out.append(self.indent + f"-- assume: unsupported ({e})")
        body = self._emit_block(fn.body, return_value=True)
        for ln in body:
            out.append(self.indent + ln)
        out.append(f"end {_ada_ident(fn.name)};")
        return out

    def _function_head(self, fn: EMLFunction) -> str:
        ret_type = _ada_type(fn.return_type or "Real")
        # Ada parameter list: each param is `Name : Type`.
        params = "; ".join(
            f"{_ada_ident(p.name)} : {_ada_type(p.type_name)}"
            for p in fn.params
        )
        if not params:
            return f"function {_ada_ident(fn.name)} return {ret_type}"
        return (
            f"function {_ada_ident(fn.name)}\n"
            f"{self.indent}({params}) return {ret_type}"
        )

    # ── Phase E.5: refinement obligations collector ───────────────────────────

    def _collect_refinement_pre_terms(
        self, fn: EMLFunction,
    ) -> tuple[list[str], list[str]]:
        """Collect Pre => terms from refined parameters.

        Returns (executable_terms, comment_obligations):
          - executable_terms: list of Ada predicate strings to AND-then into Pre =>
          - comment_obligations: cross-param refinements (comment-only)

        The Ada expression emitter already maps && -> and then, == -> =, ! -> not,
        abs(x) -> abs (x), so the predicates are natively Ada-syntactic.
        """
        param_names = {p.name for p in fn.params}
        executable: list[str] = []
        comments: list[str] = []
        for p in fn.params:
            if p.refinement is None:
                continue
            ref = p.refinement
            pred = _substitute_var(ref.predicate, ref.binder, p.name)
            pred_vars = _var_names(pred)
            other_params = (pred_vars - {p.name}) & param_names
            if other_params:
                try:
                    cond_str = self._emit_expr(pred)
                except CompileError as e:
                    cond_str = f"<unsupported: {e}>"
                comments.append(
                    f"-- refinement obligation: {fn.name}: {p.name}: {cond_str}"
                )
                continue
            try:
                term = self._emit_expr(pred)
                executable.append(term)
            except CompileError as e:
                comments.append(
                    f"-- refinement: unsupported ({e})"
                )
        return executable, comments

    # ── Pre/Post contract translation ─────────────────────────

    def _contract_lines(self, fn: EMLFunction) -> list[str]:
        out: list[str] = []

        # Phase E.5: collect refinement Pre terms.
        ref_terms, ref_comments = self._collect_refinement_pre_terms(fn)

        # Merge requires + refinement Pre terms.
        requires_terms: list[str] = []
        if fn.requires:
            try:
                requires_terms = [self._emit_expr(r) for r in fn.requires]
            except CompileError as e:
                requires_terms = [f"True  -- TODO: requires unsupported ({e})"]

        all_pre_terms = ref_terms + requires_terms
        if all_pre_terms:
            pre = " and then ".join(all_pre_terms)
            out.append(f"Pre  => {pre}")
        elif ref_comments:
            # Only cross-param obligations: emit as comments (not a Pre =>)
            pass

        # Add cross-param refinement comments after the Pre => line.
        out.extend(ref_comments)

        if fn.ensures:
            try:
                # In Ada, the result attribute is `Function_Name'Result`.
                # Substitute the EML `result` identifier for that.
                post = " and then ".join(
                    self._emit_expr(r, result_attr=f"{_ada_ident(fn.name)}'Result")
                    for r in fn.ensures
                )
                out.append(f"Post => {post}")
            except CompileError as e:
                out.append(f"Post => True  -- TODO: ensures unsupported ({e})")
        # @verify(lean) cross-link as a comment-aspect (no semantic
        # effect; just helps a human navigating between artefacts).
        for a in fn.annotations:
            if a.kind == "verify":
                tname = a.args.get("theorem", fn.name)
                out.append(
                    f"-- @verify(lean, theorem => \"{tname}\")"
                )
        return out

    # ── Statements ────────────────────────────────────────────

    def _emit_block(
        self,
        block: ASTNode | None,
        *,
        return_value: bool,
    ) -> list[str]:
        if block is None or block.kind != NodeKind.BLOCK:
            return ["null;  -- empty block"]

        # Collect leading LET / LET_MUT into a `declare` section,
        # then the remaining statements form the begin/end body.
        decls: list[str] = []
        stmts: list[ASTNode] = []
        seen_non_let = False
        for stmt in block.children:
            if not seen_non_let and stmt.kind in (NodeKind.LET, NodeKind.LET_MUT):
                ada_type = _ada_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                kw = "constant" if stmt.kind == NodeKind.LET else ""
                if kw:
                    decls.append(
                        f"{_ada_ident(stmt.value)} : {kw} {ada_type} := {rhs};"
                    )
                else:
                    decls.append(
                        f"{_ada_ident(stmt.value)} : {ada_type} := {rhs};"
                    )
            else:
                seen_non_let = True
                stmts.append(stmt)

        body_lines: list[str] = []
        for i, stmt in enumerate(stmts):
            is_last = (i == len(stmts) - 1)
            if stmt.kind in (NodeKind.LET, NodeKind.LET_MUT):
                # LET buried mid-body -- emit as nested declare.
                ada_type = _ada_type(stmt.type_annotation or "Real")
                rhs = self._emit_expr(stmt.children[0])
                kw = "constant" if stmt.kind == NodeKind.LET else ""
                if kw:
                    body_lines.append(
                        f"declare {_ada_ident(stmt.value)} : {kw} {ada_type} := {rhs}; begin null; end;"
                    )
                else:
                    body_lines.append(
                        f"declare {_ada_ident(stmt.value)} : {ada_type} := {rhs}; begin null; end;"
                    )
            elif stmt.kind == NodeKind.ASSIGN:
                rhs = self._emit_expr(stmt.children[0])
                body_lines.append(f"{_ada_ident(stmt.value)} := {rhs};")
            elif stmt.kind == NodeKind.WHILE:
                cond = self._emit_expr(stmt.children[0])
                inner = self._emit_block(stmt.children[1], return_value=False)
                body_lines.append(f"while {cond} loop")
                for ln in inner:
                    body_lines.append(self.indent + ln)
                body_lines.append("end loop;")
            elif stmt.kind == NodeKind.EXPR_STMT:
                body_lines.append(f"{self._emit_expr(stmt.children[0])};")
            elif is_last and return_value:
                body_lines.append(f"return {self._emit_expr(stmt)};")
            else:
                body_lines.append(f"{self._emit_expr(stmt)};")

        if decls:
            out = ["declare"]
            for d in decls:
                out.append(self.indent + d)
            out.append("begin")
            for ln in body_lines:
                out.append(self.indent + ln)
            out.append("end;")
            return out
        return body_lines or ["null;"]

    # ── Expressions ───────────────────────────────────────────

    def _emit_expr(
        self,
        node: ASTNode,
        *,
        result_attr: str | None = None,
    ) -> str:
        """Render a single AST expression as Ada source.

        ``result_attr`` is only used when emitting an `ensures`
        clause: every ``result`` VAR reference is rewritten to
        the supplied attribute string (e.g. ``autopilot_step'Result``).
        """
        kind = node.kind

        if kind == NodeKind.LITERAL:
            v = node.value
            if isinstance(v, bool):
                return "True" if v else "False"
            if isinstance(v, int):
                return str(v)
            if isinstance(v, float):
                # Ada float literals require a digit on each side
                # of the point (e.g. 1.0, not 1.).
                s = repr(v)
                if "." not in s and "e" not in s and "E" not in s:
                    s += ".0"
                return s
            raise CompileError(f"unsupported literal: {v!r}")

        if kind == NodeKind.VAR:
            name = str(node.value)
            if result_attr is not None and name == "result":
                return result_attr
            return _ada_ident(name)

        if kind == NodeKind.UNARYOP:
            sub = self._emit_expr(node.children[0], result_attr=result_attr)
            if node.value == "-":
                return f"(- {sub})"
            if node.value == "!":
                return f"(not {sub})"
            raise CompileError(f"unsupported unary op: {node.value!r}")

        if kind == NodeKind.BINOP:
            left = self._emit_expr(node.children[0], result_attr=result_attr)
            right = self._emit_expr(node.children[1], result_attr=result_attr)
            op = node.value
            if op == "&&":
                op = "and then"
            elif op == "||":
                op = "or else"
            elif op == "==":
                op = "="
            elif op == "!=":
                op = "/="
            return f"({left} {op} {right})"

        if kind == NodeKind.TUPLE:
            # Ada has no first-class tuples; emit as aggregate.
            elems = ", ".join(
                self._emit_expr(c, result_attr=result_attr) for c in node.children
            )
            return f"({elems})"

        if kind == NodeKind.ABS:
            sub = self._emit_expr(node.children[0], result_attr=result_attr)
            # Ada's `abs` is a unary operator -- not a function call.
            return f"abs ({sub})"

        if kind == NodeKind.CLAMP:
            x, lo, hi = (
                self._emit_expr(c, result_attr=result_attr) for c in node.children
            )
            return f"Long_Float'Min ({hi}, Long_Float'Max ({lo}, {x}))"

        if kind == NodeKind.POW:
            base, exp = (
                self._emit_expr(c, result_attr=result_attr) for c in node.children
            )
            return f"({base}) ** ({exp})"

        if kind in _BUILTIN_TO_ADA:
            ada_fn = _BUILTIN_TO_ADA[kind]
            args = ", ".join(
                self._emit_expr(c, result_attr=result_attr) for c in node.children
            )
            return f"{ada_fn} ({args})"

        if kind == NodeKind.CALL:
            args = ", ".join(
                self._emit_expr(c, result_attr=result_attr) for c in node.children
            )
            return f"{_ada_ident(str(node.value))} ({args})"

        raise CompileError(
            f"Ada backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )

    # ── Profile comment ───────────────────────────────────────

    def _profile_comment(self, fn: EMLFunction) -> list[str]:
        if fn.profile is None:
            return [f"-- {fn.name}: profile unavailable"]
        p = fn.profile
        if p.get("status") == "complex_body":
            return [
                f"-- {fn.name} -- COMPLEX BODY",
                f"-- note: {p.get('note', '')}",
            ]
        cc = p.get("cost_class", "?")
        co = p.get("chain_order", "?")
        depth = p.get("eml_depth", "?")
        drift = p.get("fp16_drift_risk", "?")
        out = [
            f"-- {fn.name}",
            f"-- Chain order: {co}    Cost class: {cc}",
            f"-- EML depth:   {depth}    Drift risk: {drift}",
        ]
        return out
