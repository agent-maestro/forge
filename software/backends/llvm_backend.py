"""LLVM IR backend.

Emits portable LLVM IR text. Each EML transcendental becomes an
external `declare`-d call into `libmonogate` (same naming as the
C backend); arithmetic and control flow lower to native LLVM
instructions.

The body emitter uses `alloca`/`load`/`store` for mutable bindings
and `while`-loops -- this avoids the SSA phi-node bookkeeping at
the cost of a few extra loads (mem2reg cleans them up). LLVM's
own `opt` pass is expected to follow ours.

Reference: lang/spec/EML_LANG_DESIGN.md section 2.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
)


_BUILTIN_TO_LLVM: dict[NodeKind, str] = {
    NodeKind.EXP:   "mg_exp",
    NodeKind.LN:    "mg_ln",
    NodeKind.SIN:   "mg_sin",
    NodeKind.COS:   "mg_cos",
    NodeKind.TAN:   "mg_tan",
    NodeKind.SQRT:  "mg_sqrt",
    NodeKind.ASIN:  "mg_asin",
    NodeKind.ACOS:  "mg_acos",
    NodeKind.ATAN:  "mg_atan",
    NodeKind.SINH:  "mg_sinh",
    NodeKind.COSH:  "mg_cosh",
    NodeKind.TANH:  "mg_tanh",
    NodeKind.POW:   "mg_pow",
    NodeKind.EML:   "mg_eml",
    NodeKind.CLAMP: "mg_clamp",
    NodeKind.ABS:   "mg_abs",
}


_BUILTIN_ARITY: dict[NodeKind, int] = {
    NodeKind.EXP: 1,   NodeKind.LN: 1,   NodeKind.SIN: 1, NodeKind.COS: 1,
    NodeKind.TAN: 1,   NodeKind.SQRT: 1, NodeKind.ASIN: 1, NodeKind.ACOS: 1,
    NodeKind.ATAN: 1,  NodeKind.SINH: 1, NodeKind.COSH: 1, NodeKind.TANH: 1,
    NodeKind.ABS:  1,
    NodeKind.POW:  2,  NodeKind.EML:  2,
    NodeKind.CLAMP: 3,
}


_TYPE_TO_LLVM: dict[str, str] = {
    "Real": "double", "f64": "double",
    "f32":  "float",  "f16":  "half",   "bf16": "bfloat",
    "u8":   "i8",   "u16": "i16", "u32": "i32", "u64": "i64",
    "i8":   "i8",   "i16": "i16", "i32": "i32", "i64": "i64",
    "bool": "i1",   "void": "void",
}


def _llvm_type(eml_type: str) -> str:
    """Translate an EML-lang type name to an LLVM IR type."""
    return _TYPE_TO_LLVM.get(eml_type, "double")


class CompileError(Exception):
    """Raised when the LLVM backend can't translate a node."""


@dataclass
class _EmitState:
    """Per-function emit state -- SSA register counter + locals map."""
    next_reg: int = 0
    """Counter for `%1`, `%2`, ... `%entry` is reserved as block label."""
    locals: dict = None
    """Map binding-name -> (alloca slot, llvm type)."""
    consts: dict = None
    """Map module-level constant name -> (literal_value, llvm type) so
    free `VAR` references that miss the locals map still resolve."""

    def __post_init__(self):
        if self.locals is None:
            self.locals = {}
        if self.consts is None:
            self.consts = {}

    def fresh(self) -> str:
        self.next_reg += 1
        return f"%{self.next_reg}"

    def fresh_label(self, hint: str) -> str:
        self.next_reg += 1
        return f"{hint}.{self.next_reg}"


class LLVMBackend:
    """Compile an EMLModule to LLVM IR text."""

    name = "llvm"

    def __init__(self, *, optimize: bool = True, target_triple: str | None = None):
        self.optimize = optimize
        self.target_triple = target_triple

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        # Resolve module-level constants to literal values where we
        # can -- the body emitter substitutes them inline so `VAR R`
        # in `arrhenius` becomes the literal 8.314.
        from lang.optimizer.constant_folding import fold_constants
        consts: dict[str, tuple[object, str]] = {}
        for c in mod.constants:
            ty = _llvm_type(c.type_name)
            folded = fold_constants(c.value)
            if folded.kind == NodeKind.LITERAL:
                consts[c.name] = (folded.value, ty)

        self._consts = consts

        lines: list[str] = [
            f"; ModuleID = '{mod.name or 'unnamed'}'",
            f"source_filename = \"{str(mod.source_file).replace(chr(92), '/')}\"",
        ]
        if self.target_triple:
            lines.append(f'target triple = "{self.target_triple}"')
        lines.append("")
        lines.extend(self._emit_externs(mod.functions))
        lines.append("")

        # Tuple-return struct types -- LLVM uses anonymous literal
        # structs at call sites, so we declare named types for clarity
        # of the generated IR.
        for fn in mod.functions:
            if fn.return_tuple_types:
                tname = self._tuple_type_name(fn.name)
                fields = ", ".join(_llvm_type(t) for t in fn.return_tuple_types)
                lines.append(f"%{tname} = type {{ {fields} }}")
        if any(fn.return_tuple_types for fn in mod.functions):
            lines.append("")

        # Module-level constants -> @globals.
        for c in mod.constants:
            lines.extend(self._emit_constant(c))
        if mod.constants:
            lines.append("")

        # Functions.
        for fn in mod.functions:
            lines.extend(self._emit_function(fn))
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    # ── Externs ──────────────────────────────────────────────

    def _emit_externs(self, funcs: Iterable[EMLFunction]) -> list[str]:
        """Emit a `declare double @mg_*(double, ...)` for every
        libmonogate symbol any function in the module references.
        Plus user CALLs into peers (we forward-declare every defined
        function to allow any-order references)."""
        used: set[NodeKind] = set()

        def walk(n: ASTNode | None):
            if n is None:
                return
            if n.kind in _BUILTIN_TO_LLVM:
                used.add(n.kind)
            for c in n.children:
                walk(c)

        for fn in funcs:
            for r in fn.requires:
                walk(r)
            for e in fn.ensures:
                walk(e)
            walk(fn.body)

        out: list[str] = []
        for kind in sorted(used, key=lambda k: k.name):
            sym = _BUILTIN_TO_LLVM[kind]
            arity = _BUILTIN_ARITY[kind]
            args = ", ".join(["double"] * arity)
            out.append(f"declare double @{sym}({args})")
        return out

    # ── Tuple struct names ───────────────────────────────────

    @staticmethod
    def _tuple_type_name(fn_name: str) -> str:
        return f"{fn_name}.result_t"

    # ── Constants ────────────────────────────────────────────

    def _emit_constant(self, c: EMLConstant) -> list[str]:
        """Emit a global constant. Only literal-folded values supported
        at this layer; anything else is emitted as zero-init with a
        comment explaining why a constructor would be needed."""
        ty = _llvm_type(c.type_name)
        if c.value.kind == NodeKind.LITERAL:
            v = c.value.value
            return [f"@{c.name} = constant {ty} {self._lit(v, ty)}"]
        # Fallback: zero-init with note.
        return [f"@{c.name} = constant {ty} 0.0  ; non-literal init dropped"]

    @staticmethod
    def _lit(v, ty: str) -> str:
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, int):
            if ty in ("double", "float", "half", "bfloat"):
                return f"{float(v):.17e}"
            return str(v)
        if isinstance(v, float):
            return f"{v:.17e}"
        raise CompileError(f"unsupported literal: {v!r}")

    # ── Function emit ────────────────────────────────────────

    def _emit_function(self, fn: EMLFunction) -> list[str]:
        out: list[str] = []
        out.extend(self._profile_comment(fn))

        if fn.return_tuple_types:
            ret_ty = f"%{self._tuple_type_name(fn.name)}"
        else:
            ret_ty = _llvm_type(fn.return_type or "Real")

        # IMPORTANT: LLVM requires unnamed values to be sequentially
        # numbered starting at %0 across the entry block. Name our
        # parameters so we can mix in named locals freely.
        param_pieces = []
        for p in fn.params:
            param_pieces.append(f"{_llvm_type(p.type_name)} %{p.name}")
        params_ll = ", ".join(param_pieces)

        out.append(f"define {ret_ty} @{fn.name}({params_ll}) {{")
        out.append("entry:")

        st = _EmitState(consts=getattr(self, "_consts", {}))
        body_lines: list[str] = []

        # Allocate and store every parameter into a stack slot so the
        # body can reference them through the same load path as let
        # bindings -- simpler emitter, mem2reg handles it later.
        for p in fn.params:
            ty = _llvm_type(p.type_name)
            slot = f"%{p.name}.addr"
            body_lines.append(f"  {slot} = alloca {ty}")
            body_lines.append(f"  store {ty} %{p.name}, {ty}* {slot}")
            st.locals[p.name] = (slot, ty)

        struct_name = (
            self._tuple_type_name(fn.name) if fn.return_tuple_types else None
        )
        body_lines.extend(
            self._emit_block(
                fn.body,
                st=st,
                return_value=True,
                tuple_struct=struct_name,
                tuple_types=fn.return_tuple_types,
                ret_type=ret_ty,
            )
        )
        out.extend(body_lines)
        out.append("}")
        return out

    def _profile_comment(self, fn: EMLFunction) -> list[str]:
        if fn.profile is None:
            return [f"; {fn.name}: no profile available"]
        p = fn.profile
        if p.get("status") == "complex_body":
            return [f"; {fn.name} -- COMPLEX BODY"]
        cc = p.get("cost_class", "?")
        co = p.get("chain_order", "?")
        depth = p.get("eml_depth", "?")
        return [f"; {fn.name}: chain_order={co} cost_class={cc} eml_depth={depth}"]

    # ── Block / statement emit ───────────────────────────────

    def _emit_block(
        self,
        block: ASTNode | None,
        *,
        st: _EmitState,
        return_value: bool,
        tuple_struct: str | None = None,
        tuple_types: list[str] | None = None,
        ret_type: str = "double",
    ) -> list[str]:
        if block is None or block.kind != NodeKind.BLOCK:
            return ["  ret double 0.0  ; empty block"] if return_value else []
        out: list[str] = []
        for i, stmt in enumerate(block.children):
            is_last = (i == len(block.children) - 1)

            if stmt.kind in (NodeKind.LET, NodeKind.LET_MUT):
                ty = _llvm_type(stmt.type_annotation or "Real")
                rhs_reg, lns = self._emit_expr(stmt.children[0], st)
                out.extend(lns)
                slot = f"%{stmt.value}.addr"
                out.append(f"  {slot} = alloca {ty}")
                out.append(f"  store {ty} {rhs_reg}, {ty}* {slot}")
                st.locals[stmt.value] = (slot, ty)
            elif stmt.kind == NodeKind.ASSIGN:
                slot, ty = st.locals[stmt.value]
                rhs_reg, lns = self._emit_expr(stmt.children[0], st)
                out.extend(lns)
                out.append(f"  store {ty} {rhs_reg}, {ty}* {slot}")
            elif stmt.kind == NodeKind.WHILE:
                out.extend(self._emit_while(stmt, st))
            elif stmt.kind == NodeKind.EXPR_STMT:
                _, lns = self._emit_expr(stmt.children[0], st)
                out.extend(lns)
            elif is_last:
                if (
                    return_value
                    and stmt.kind == NodeKind.TUPLE
                    and tuple_struct is not None
                    and tuple_types is not None
                ):
                    out.extend(
                        self._emit_tuple_return(
                            stmt, tuple_struct, tuple_types, st,
                        )
                    )
                elif return_value:
                    reg, lns = self._emit_expr(stmt, st)
                    out.extend(lns)
                    out.append(f"  ret {ret_type} {reg}")
                else:
                    _, lns = self._emit_expr(stmt, st)
                    out.extend(lns)
            else:
                _, lns = self._emit_expr(stmt, st)
                out.extend(lns)
        return out

    def _emit_while(self, stmt: ASTNode, st: _EmitState) -> list[str]:
        head = st.fresh_label("while.head")
        body = st.fresh_label("while.body")
        end  = st.fresh_label("while.end")
        out: list[str] = []
        out.append(f"  br label %{head}")
        out.append(f"{head}:")
        cond_reg, lns = self._emit_expr(stmt.children[0], st)
        out.extend(lns)
        out.append(f"  br i1 {cond_reg}, label %{body}, label %{end}")
        out.append(f"{body}:")
        body_lns = self._emit_block(stmt.children[1], st=st, return_value=False)
        out.extend(body_lns)
        out.append(f"  br label %{head}")
        out.append(f"{end}:")
        return out

    def _emit_tuple_return(
        self,
        node: ASTNode,
        struct_name: str,
        tuple_types: list[str],
        st: _EmitState,
    ) -> list[str]:
        """Build a struct value field-by-field and `ret` it."""
        out: list[str] = []
        cur = "undef"
        struct_ty = f"%{struct_name}"
        for i, child in enumerate(node.children):
            reg, lns = self._emit_expr(child, st)
            out.extend(lns)
            field_ty = _llvm_type(tuple_types[i])
            new = st.fresh()
            out.append(
                f"  {new} = insertvalue {struct_ty} {cur}, "
                f"{field_ty} {reg}, {i}"
            )
            cur = new
        out.append(f"  ret {struct_ty} {cur}")
        return out

    # ── Expression emit ──────────────────────────────────────

    def _emit_expr(
        self, node: ASTNode, st: _EmitState,
    ) -> tuple[str, list[str]]:
        """Lower `node` to (result_register, code_lines).

        For expressions whose value is a constant literal, the
        register is the literal text itself and code_lines is empty.
        """
        kind = node.kind

        if kind == NodeKind.LITERAL:
            v = node.value
            if isinstance(v, bool):
                return ("1" if v else "0"), []
            if isinstance(v, int):
                return f"{float(v):.17e}", []
            if isinstance(v, float):
                return f"{v:.17e}", []
            raise CompileError(f"unsupported literal: {v!r}")

        if kind == NodeKind.VAR:
            name = node.value
            if name in st.locals:
                slot, ty = st.locals[name]
                r = st.fresh()
                return r, [f"  {r} = load {ty}, {ty}* {slot}"]
            if name in st.consts:
                v, ty = st.consts[name]
                return self._lit(v, ty), []
            raise CompileError(f"LLVM backend: unbound name {name!r}")

        if kind == NodeKind.UNARYOP:
            sub_reg, lns = self._emit_expr(node.children[0], st)
            r = st.fresh()
            if node.value == "-":
                return r, lns + [f"  {r} = fneg double {sub_reg}"]
            if node.value == "!":
                return r, lns + [f"  {r} = xor i1 {sub_reg}, true"]
            raise CompileError(f"unsupported unary: {node.value!r}")

        if kind == NodeKind.BINOP:
            return self._emit_binop(node, st)

        if kind in _BUILTIN_TO_LLVM:
            sym = _BUILTIN_TO_LLVM[kind]
            arg_regs: list[str] = []
            lns: list[str] = []
            for c in node.children:
                reg, l = self._emit_expr(c, st)
                lns.extend(l)
                arg_regs.append(reg)
            args_ll = ", ".join(f"double {r}" for r in arg_regs)
            r = st.fresh()
            lns.append(f"  {r} = call double @{sym}({args_ll})")
            return r, lns

        if kind == NodeKind.CALL:
            arg_regs: list[str] = []
            lns: list[str] = []
            for c in node.children:
                reg, l = self._emit_expr(c, st)
                lns.extend(l)
                arg_regs.append(reg)
            args_ll = ", ".join(f"double {r}" for r in arg_regs)
            r = st.fresh()
            lns.append(f"  {r} = call double @{node.value}({args_ll})")
            return r, lns

        if kind == NodeKind.TUPLE:
            # Bare TUPLE outside return position is unusual -- emit
            # an aggregate built field by field with no enclosing
            # struct type known. Caller is expected to wrap.
            raise CompileError(
                "TUPLE outside return position not supported by LLVM backend"
            )

        raise CompileError(
            f"LLVM backend: unsupported NodeKind {kind} "
            f"(at line {node.line}:{node.col})"
        )

    _ARITH = {"+", "-", "*", "/"}
    _CMP_F = {"==": "oeq", "!=": "one", "<": "olt", "<=": "ole", ">": "ogt", ">=": "oge"}
    _BOOL = {"&&", "||"}

    def _emit_binop(
        self, node: ASTNode, st: _EmitState,
    ) -> tuple[str, list[str]]:
        op = node.value
        l_reg, l_lns = self._emit_expr(node.children[0], st)
        r_reg, r_lns = self._emit_expr(node.children[1], st)
        lns = l_lns + r_lns
        r = st.fresh()
        if op == "+":
            lns.append(f"  {r} = fadd double {l_reg}, {r_reg}")
        elif op == "-":
            lns.append(f"  {r} = fsub double {l_reg}, {r_reg}")
        elif op == "*":
            lns.append(f"  {r} = fmul double {l_reg}, {r_reg}")
        elif op == "/":
            lns.append(f"  {r} = fdiv double {l_reg}, {r_reg}")
        elif op in self._CMP_F:
            cmp = self._CMP_F[op]
            lns.append(f"  {r} = fcmp {cmp} double {l_reg}, {r_reg}")
        elif op == "&&":
            lns.append(f"  {r} = and i1 {l_reg}, {r_reg}")
        elif op == "||":
            lns.append(f"  {r} = or i1 {l_reg}, {r_reg}")
        else:
            raise CompileError(f"LLVM backend: unsupported binop {op!r}")
        return r, lns
