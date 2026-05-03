"""Lean 4 verification backend.

Compiles `@verify(lean, theorem = "<name>")` blocks into Lean 4
theorem files. Each verified function produces:

  1. A Lean function definition mirroring the EML body (when the
     body is a single expression without mut/while; complex bodies
     are declared as `opaque` placeholders).
  2. A theorem statement built from `requires` (hypotheses) +
     `ensures` (conclusion), with `result` rewritten to refer to
     the function's return value.
  3. A proof body of `sorry` (the proof obligation is left for
     the agent / human downstream).

Output imports the MachLib foundations only — zero Mathlib
dependency. After `open MachLib` and `open MachLib.Real`, bare
`Real`, `exp`, `log`, `sin`, `cos`, `eml`, `min`, `max`, `abs`
all resolve through MachLib.

Reference: lang/spec/EML_LANG_DESIGN.md section 2.4.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Builtin NodeKind -> Lean function call. Lean uses Real.foo for
# real-valued versions of transcendentals.
_BUILTIN_TO_LEAN: dict[NodeKind, str] = {
    NodeKind.EXP:   "Real.exp",
    NodeKind.LN:    "Real.log",
    NodeKind.SIN:   "Real.sin",
    NodeKind.COS:   "Real.cos",
    NodeKind.TAN:   "Real.tan",
    NodeKind.SQRT:  "Real.sqrt",
    NodeKind.ABS:   "abs",
    NodeKind.ASIN:  "Real.arcsin",
    NodeKind.ACOS:  "Real.arccos",
    NodeKind.ATAN:  "Real.arctan",
    NodeKind.SINH:  "Real.sinh",
    NodeKind.COSH:  "Real.cosh",
    NodeKind.TANH:  "Real.tanh",
}


# Stdlib activation / EML-family function names that get a 1:1
# pass-through to Lean (no runtime-namespace rewrite). The downstream
# verifier provides their definitions; this list documents the set
# that MachLib's stdlib emitter is expected to recognise.
_STDLIB_PASSTHROUGH: frozenset[str] = frozenset({
    "sigmoid", "softplus", "relu", "logistic", "gompertz",
    "eml", "eal", "exl", "edl", "lediv", "elsb", "elad", "deml",
})


# Map EML-lang type names to Lean type names. Aliases default to
# `Real` since chain-order constraints don't change the underlying
# numeric domain.
_TYPE_TO_LEAN: dict[str, str] = {
    "Real": "Real",
    "f64":  "Real",
    "f32":  "Real",
    "f16":  "Real",
    "bf16": "Real",
    "Int":  "Int",
    "Nat":  "Nat",
    "Byte": "Nat",
    "u8":   "Nat",
    "u16":  "Nat",
    "u32":  "Nat",
    "u64":  "Nat",
    "i8":   "Int",
    "i16":  "Int",
    "i32":  "Int",
    "i64":  "Int",
    "bool": "Bool",
    "Bool": "Bool",
}


# Identifiers reserved by Lean 4. EML allows these as function /
# parameter names, but Lean rejects them as identifiers (they're
# keywords). We rename collisions to ``<name>_`` on emission so the
# Lean kernel accepts the file.
_LEAN_RESERVED: frozenset[str] = frozenset({
    "abbrev", "as", "attribute", "axiom", "begin", "by", "class",
    "constant", "decreasing_by", "def", "deriving", "do", "else",
    "end", "example", "export", "extends", "extern", "final", "for",
    "from", "fun", "have", "if", "import", "in", "inductive",
    "infix", "infixl", "infixr", "instance", "lemma", "let",
    "macro", "macro_rules", "match", "mut", "mutual", "namespace",
    "noncomputable", "notation", "open", "opaque", "partial",
    "postfix", "prefix", "private", "protected", "public", "rec",
    "return", "scoped", "section", "set_option", "show",
    "structure", "suffices", "syntax", "term", "then", "theorem",
    "this", "true", "false", "try", "universe", "unsafe",
    "variable", "where", "while", "with",
})


def _lean_type(eml_type: str) -> str:
    return _TYPE_TO_LEAN.get(eml_type, "Real")


def _safe_id(name: str) -> str:
    """Append ``_`` to any name that collides with a Lean keyword."""
    return f"{name}_" if name in _LEAN_RESERVED else name


def _to_prop(expr: str) -> str:
    """Normalise a Bool-literal-only expression into a Prop.

    `requires (true)` and `ensures (true)` parse as Bool literals
    that emit lowercase `true` / `false`; in a hypothesis or
    conclusion position those are values, not Props, so Lean
    rejects them. We rewrite them to capitalised `True` / `False`
    here. Compound expressions (e.g. `a >= 0 && b <= 1`) pass
    through unchanged — they're already Prop-valued via the >=
    / <= / && operators that `_emit_expr` renders.
    """
    s = expr.strip()
    if s == "true":
        return "True"
    if s == "false":
        return "False"
    return expr


class LeanBackend:
    """Generate Lean 4 theorems from `@verify` blocks."""

    name = "lean"

    def __init__(self, *, optimize: bool = True) -> None:
        self.optimize = optimize

    # ── Public API ────────────────────────────────────────────

    def compile_module(self, mod: EMLModule) -> str:
        """Emit a full .lean file for every @verify-annotated
        function in the module. Returns the empty string if no
        function carries a Lean verification annotation."""
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)
        verified = [
            f for f in mod.functions
            if any(self._is_lean_verify(a) for a in f.annotations)
        ]
        if not verified:
            return ""

        # Header + imports.
        lines = [
            "-- Generated by the EML-lang Lean backend",
            f"-- Source module: {mod.name or '(unnamed)'}",
            f"-- Source file:   {mod.source_file}",
            f"-- Verified fns:  {', '.join(f.name for f in verified)}",
            "",
            "import MachLib.EML",
            "import MachLib.Trig",
            "import MachLib.Forge",
            "",
            "open MachLib",
            "open MachLib.Real",
            "",
        ]
        # Emit module-level constants. Without this, kernel bodies
        # that reference module constants (G_GRAVITY, VEL_MAX, ...)
        # fail Lean elaboration with `unknown identifier`.
        if mod.constants:
            for const in mod.constants:
                lean_type = _lean_type(const.type_name)
                # `_emit_expr` always wraps integer/float literals as
                # `(N : Real)` because that's the right cast for the
                # body of a Real-valued kernel function. For Int/Nat
                # constants that's a type error: we want the literal
                # at its declared type, not Real. Special-case the
                # bare-integer literal when the declared type is Int
                # or Nat.
                value_node = const.value
                is_int_lit = (
                    value_node.kind == NodeKind.LITERAL
                    and isinstance(value_node.value, int)
                    and not isinstance(value_node.value, bool)
                )
                try:
                    if lean_type in ("Int", "Nat") and is_int_lit:
                        val = str(value_node.value)
                    else:
                        val = self._emit_expr(value_node)
                except _UnsupportedNode as e:
                    val = f"sorry  -- TODO: const value unsupported ({e})"
                lines.append(
                    f"noncomputable def {const.name} : {lean_type} := {val}"
                )
            lines.append("")
        # Emit signatures for every non-verified function as `axiom`.
        # We deliberately don't emit their bodies even when they're
        # well-formed: Lean requires every used identifier to be
        # in-scope at use site, so a helper that calls a verified
        # function would force us to either reorder declarations
        # (hard with mutual recursion) or wrap everything in a
        # `mutual` block. Treating helpers as axioms is the same
        # approach we already use for `extern` functions, and it
        # gives the verified theorems the symbols they need with
        # zero ordering constraint. The cost: we lose the helper's
        # body in the discovered file. The auto_prove driver knows
        # this is a scaffold pass — actual helper bodies live in
        # the .eml source, not in MachLib.
        verified_names = {f.name for f in verified}
        for fn in mod.functions:
            if fn.name in verified_names:
                continue
            params_lean = " ".join(
                f"({_safe_id(p.name)} : {_lean_type(p.type_name)})"
                for p in fn.params
            )
            ret_type = (
                "Real" if fn.return_tuple_types
                else _lean_type(fn.return_type or "Real")
            )
            note = ("extern" if fn.is_extern else "helper")
            lines.append(
                f"axiom {_safe_id(fn.name)} {params_lean} : {ret_type}"
                f"  -- {note} (axiomatised in MachLib/Discovered)"
            )
            lines.append("")
        for fn in verified:
            lines.extend(self._compile_one(fn, mod))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def compile(self, func: EMLFunction) -> str:
        """Emit Lean for a single @verify-annotated function.
        Returns empty string when the function has no @verify."""
        if not any(self._is_lean_verify(a) for a in func.annotations):
            return ""
        # Synthesize a wrapper module so compile_module's header runs.
        mod = EMLModule(name="_single", functions=[func])
        return self.compile_module(mod)

    # ── Internal: per-function render ─────────────────────────

    def _compile_one(self, func: EMLFunction, mod: EMLModule) -> list[str]:
        verify_annot = next(
            a for a in func.annotations if self._is_lean_verify(a)
        )
        theorem_name = verify_annot.args.get("theorem", func.name)

        out: list[str] = []
        out.append(f"-- ── {func.name} ──")
        out.append("")
        out.extend(self._render_function_def(func))
        out.append("")
        out.extend(self._render_theorem(func, theorem_name))
        return out

    def _render_function_def(self, func: EMLFunction) -> list[str]:
        """Emit a Lean `def` matching the EML function. For complex
        bodies (mut / while), emit `opaque` instead so the theorem
        can still talk about the function symbolically."""
        safe_name = _safe_id(func.name)
        params_lean = " ".join(
            f"({_safe_id(p.name)} : {_lean_type(p.type_name)})"
            for p in func.params
        )
        ret_type = (
            "Real" if func.return_tuple_types
            else _lean_type(func.return_type or "Real")
        )

        # Extern fns are axiom declarations -- the implementation
        # lives outside EML-lang's reach. We use `axiom` rather than
        # `opaque` because Lean 4's `opaque` requires an executable
        # default, and our `Real` is noncomputable so no such
        # default exists.
        if func.is_extern:
            return [
                f"axiom {safe_name} {params_lean} : {ret_type}"
                f"  -- extern declaration",
            ]

        # Tuple returns and complex bodies become axiom declarations
        # so the theorem can still refer to them by name.
        complex_body = self._has_complex_body(func.body)
        if func.return_tuple_types or complex_body:
            tuple_note = (" -- tuple-return; axiomatised for now"
                          if func.return_tuple_types else "")
            complex_note = ("\n-- (body has mut / while -- axiomatised "
                            "until Phase 2.5 control-flow analyzer)"
                            if complex_body else "")
            return [
                f"axiom {safe_name} {params_lean} : {ret_type}"
                f"{tuple_note}{complex_note}",
            ]

        # Single-expression body -- inline the AST.
        body_expr = self._extract_body_expression(func.body)
        if body_expr is None:
            return [f"axiom {safe_name} {params_lean} : {ret_type}"
                    f"  -- empty body"]
        try:
            lean_body = self._emit_expr(body_expr)
        except _UnsupportedNode as e:
            return [
                f"axiom {safe_name} {params_lean} : {ret_type}"
                f"  -- unsupported AST: {e}",
            ]
        # `noncomputable` is required because every body uses the
        # opaque `Real` arithmetic instances (`instMul`, `instAdd`,
        # `instDiv`, ...) which MachLib.Basic marks `noncomputable`.
        # Without this marker `lake build` rejects the file with
        # "failed to compile definition, consider marking it as
        # 'noncomputable'".
        return [
            f"noncomputable def {safe_name} {params_lean} : {ret_type} :=",
            f"  {lean_body}",
        ]

    def _render_theorem(self, func: EMLFunction,
                        theorem_name: str) -> list[str]:
        safe_func = _safe_id(func.name)
        params_lean = " ".join(
            f"({_safe_id(p.name)} : {_lean_type(p.type_name)})"
            for p in func.params
        )
        # Hypotheses. Bool literals (`true` / `false`) coming from
        # `requires (true)` are normalised to Prop `True` / `False` —
        # otherwise Lean rejects them as values, not hypotheses.
        hyp_clauses: list[str] = []
        for i, req in enumerate(func.requires):
            try:
                hyp = self._emit_expr(req)
                hyp_clauses.append(f"(h{i+1} : {_to_prop(hyp)})")
            except _UnsupportedNode as e:
                hyp_clauses.append(f"-- TODO: requires #{i+1} ({e})")
        # Conclusion
        if func.ensures:
            ens = func.ensures[0]
            # `result` in ensures refers to the function's output.
            param_names = [_safe_id(p.name) for p in func.params]
            call = f"{safe_func} {' '.join(param_names)}"
            try:
                conclusion = _to_prop(self._emit_expr(ens, result_subst=call))
            except _UnsupportedNode as e:
                conclusion = f"True  -- TODO: ensures unsupported ({e})"
        else:
            conclusion = "True"

        hyp_block = "\n    ".join(hyp_clauses) if hyp_clauses else ""

        proof_lines = [
            f"theorem {theorem_name} {params_lean}",
        ]
        if hyp_block:
            proof_lines.append(f"    {hyp_block} :")
        else:
            proof_lines[-1] += " :"
        proof_lines.append(f"    {conclusion} := by")
        # Proof body. When the kernel has no `ensures`, the goal
        # reduces to `True` -- `unfold` cannot reduce `True`, so we
        # close it with `trivial`. Otherwise we leave a `sorry` after
        # an `unfold` that exposes the body, deferring the actual
        # proof to the downstream agent / human. MachLib intentionally
        # ships without `eml_auto`-style omnibus tactics so the corpus
        # contains real proofs, not auto-closures.
        if conclusion == "True":
            proof_lines.append(f"  trivial")
        else:
            proof_lines.extend([
                f"  unfold {safe_func}",
                f"  sorry  -- TODO: prove against MachLib foundations",
            ])
        return proof_lines

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _is_lean_verify(annot: Annotation) -> bool:
        if annot.kind != "verify":
            return False
        # The first positional arg should be 'lean'.
        return annot.args.get(0) == "lean"

    @staticmethod
    def _has_complex_body(body: ASTNode | None) -> bool:
        if body is None or body.kind != NodeKind.BLOCK:
            return True
        return any(
            c.kind in {NodeKind.LET_MUT, NodeKind.WHILE, NodeKind.ASSIGN}
            for c in body.children
        )

    @staticmethod
    def _extract_body_expression(body: ASTNode | None) -> ASTNode | None:
        """Try to reduce the body to a single expression by inlining
        `let` bindings via substitution. Returns None when the body
        has no final expression."""
        if body is None or body.kind != NodeKind.BLOCK:
            return body
        # If the only non-LET stmt is the final expression, inline lets.
        bindings: dict[str, ASTNode] = {}
        final: ASTNode | None = None
        for stmt in body.children:
            if stmt.kind == NodeKind.LET:
                bindings[stmt.value] = stmt.children[0]
            elif stmt.kind == NodeKind.EXPR_STMT:
                continue
            else:
                final = stmt
        if final is None:
            return None
        if not bindings:
            return final
        return _inline_bindings(final, bindings)

    # ── Expression emission to Lean syntax ────────────────────

    def _emit_expr(self, node: ASTNode, *,
                   result_subst: str | None = None) -> str:
        """Render an EML AST expression as a Lean expression string."""
        kind = node.kind

        if kind == NodeKind.LITERAL:
            v = node.value
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, int):
                return f"({v} : Real)"
            if isinstance(v, float):
                # MachLib core only provides ``OfNat Real`` for 0 and 1
                # (``MachLib/Basic.lean:38-39``); anything else must
                # use the ``OfScientific Real`` instance (line 60).
                # We bridge ``0.0`` / ``1.0`` to OfNat so the
                # codegen-emitted goal `f x ≥ (0 : Real)` unifies
                # directly with MachLib lemmas like `0 ≤ exp x` and
                # `-1 < tanh x`. Other integer-valued floats (e.g.
                # 200.0, 10000.0) and genuinely fractional floats
                # (0.5, 0.398…) keep the OfScientific form.
                # C-239 root-cause fix; see
                # ``monogate-research/exploration/C239_bfs_proof_sweep/NOTES.md``
                # §3.
                if v == 0.0 or v == 1.0:
                    return f"({int(v)} : Real)"
                return f"({v} : Real)"
            raise _UnsupportedNode(f"literal {v!r}")

        if kind == NodeKind.VAR:
            name = str(node.value)
            if name == "result" and result_subst is not None:
                return f"({result_subst})"
            return _safe_id(name)

        if kind == NodeKind.UNARYOP:
            sub = self._emit_expr(node.children[0],
                                  result_subst=result_subst)
            if node.value == "-":
                return f"(-{sub})"
            if node.value == "!":
                return f"(¬ {sub})"
            raise _UnsupportedNode(f"unary {node.value!r}")

        if kind == NodeKind.BINOP:
            left = self._emit_expr(node.children[0],
                                   result_subst=result_subst)
            right = self._emit_expr(node.children[1],
                                    result_subst=result_subst)
            op = node.value
            # Lean binop spelling differs for boolean and inequality
            # operators. EML uses C-style `!=`; Lean wants `≠`.
            lean_op = {
                "&&": "∧",
                "||": "∨",
                "!=": "≠",
                "==": "=",
            }.get(op, op)
            return f"({left} {lean_op} {right})"

        if kind in _BUILTIN_TO_LEAN:
            args = " ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"({_BUILTIN_TO_LEAN[kind]} {args})"

        if kind == NodeKind.POW:
            base = self._emit_expr(node.children[0],
                                   result_subst=result_subst)
            exp = self._emit_expr(node.children[1],
                                  result_subst=result_subst)
            return f"({base} ^ {exp})"

        if kind == NodeKind.EML:
            x = self._emit_expr(node.children[0],
                                result_subst=result_subst)
            y = self._emit_expr(node.children[1],
                                result_subst=result_subst)
            return f"((Real.exp {x}) - (Real.log {y}))"

        if kind == NodeKind.CLAMP:
            x = self._emit_expr(node.children[0],
                                result_subst=result_subst)
            lo = self._emit_expr(node.children[1],
                                 result_subst=result_subst)
            hi = self._emit_expr(node.children[2],
                                 result_subst=result_subst)
            return f"(min (max {x} {lo}) {hi})"

        if kind == NodeKind.CALL:
            args = " ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            # Stdlib activation / EML-family calls pass through
            # by their EML name; the downstream MachLib stdlib
            # provides their definitions. Sanitise Lean-keyword
            # collisions on the call site too so they match the
            # `_safe_id`-renamed declaration.
            name = _safe_id(str(node.value))
            return f"({name} {args})"

        if kind == NodeKind.TUPLE:
            elems = ", ".join(
                self._emit_expr(c, result_subst=result_subst)
                for c in node.children
            )
            return f"({elems})"

        raise _UnsupportedNode(
            f"NodeKind {kind} (line {node.line}:{node.col})"
        )


class _UnsupportedNode(Exception):
    """Internal: a node the Lean backend doesn't know how to render."""


def _inline_bindings(
    node: ASTNode, bindings: dict[str, ASTNode],
) -> ASTNode:
    """Substitute let-binding variables with their RHS expressions.
    Returns a new ASTNode tree (the original is not mutated)."""
    if node.kind == NodeKind.VAR and node.value in bindings:
        return _inline_bindings(bindings[node.value], bindings)
    new_children = [_inline_bindings(c, bindings) for c in node.children]
    return ASTNode(
        kind=node.kind,
        value=node.value,
        children=new_children,
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line,
        col=node.col,
    )
