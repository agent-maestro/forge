"""Chisel/FIRRTL backend.

Emits Chisel 3 / Scala source from an EMLModule + AllocationPlan.
Each `@target(fpga)` function becomes a `Module` whose `IO` carries
clk/rst/valid_in + per-parameter `SInt(WIDTH.W)` ports + a registered
`result`. Transcendentals become instances of vendor-neutral `Module`
classes that ship in `hardware/modules/transcendental_chisel/`.

Why Chisel? It's the canonical hardware-DSL on top of FIRRTL, the
intermediate representation Berkeley uses for ASIC + FPGA flows
(SiFive, Chipyard, Rocket). Emitting Chisel keeps EML-lang's hardware
path open to teams that already use the SBT/Mill toolchain.

Reference: lang/spec/EML_LANG_DESIGN.md section 3.2 (cross-cutting
deliverable: Chisel backend, parameterized; emits FIRRTL via the
chisel3 toolchain when invoked).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hardware.allocator import AllocationPlan
from hardware.hdl_gen.qformat import QFormat, default_q, format_verilog_literal
from lang.parser.ast_nodes import (
    ASTNode,
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


_BINOP_CHISEL_PRED: dict[str, str] = {
    "+": "+", "-": "-", "*": "*", "/": "/",
    "<": "<", ">": ">", "<=": "<=", ">=": ">=",
    "==": "===", "!=": "=/=",
    "&&": "&&", "||": "||",
}


def _chisel_pred_expr(node: ASTNode) -> str:
    """Render a predicate AST node as a Chisel/Scala expression string.

    Used for chisel3.assert() guard predicates. ABS uses
    Mux(x < 0.S, -x, x) per Hard Contract #3 (Chisel 3.5 form).
    """
    kind = node.kind
    if kind == NodeKind.LITERAL:
        v = node.value
        if isinstance(v, bool):
            return "true.B" if v else "false.B"
        if isinstance(v, (int, float)):
            s = repr(v)
            if isinstance(v, float) and "." not in s and "e" not in s:
                s += ".0"
            # In Chisel predicates, use .S suffix for signed integers
            # but for floating-point comparisons we emit raw.
            return s
        return repr(v)
    if kind == NodeKind.VAR:
        return str(node.value)
    if kind == NodeKind.UNARYOP:
        sub = _chisel_pred_expr(node.children[0])
        return f"({node.value}{sub})"
    if kind == NodeKind.BINOP:
        left = _chisel_pred_expr(node.children[0])
        right = _chisel_pred_expr(node.children[1])
        op = _BINOP_CHISEL_PRED.get(node.value, node.value)
        return f"({left} {op} {right})"
    if kind == NodeKind.ABS:
        sub = _chisel_pred_expr(node.children[0])
        # Chisel 3.5+: Mux(x < 0.S, -x, x) per Hard Contract #3.
        return f"Mux({sub} < 0.S, -{sub}, {sub})"
    args = ", ".join(_chisel_pred_expr(c) for c in node.children)
    return f"{kind.name.lower()}({args})"


_BINOP_TO_CHISEL: dict[str, str] = {
    "+": "+", "-": "-", "*": "*", "/": "/",
    "<": "<", ">": ">", "<=": "<=", ">=": ">=",
    "==": "===", "!=": "=/=",
    "&&": "&&", "||": "||",
}


_TRANSCENDENTAL_TO_MODULE: dict[NodeKind, str] = {
    NodeKind.EXP:   "EmlExp",
    NodeKind.LN:    "EmlLn",
    NodeKind.SIN:   "EmlSin",
    NodeKind.COS:   "EmlCos",
    NodeKind.TAN:   "EmlTan",
    NodeKind.SQRT:  "EmlSqrt",
    NodeKind.SINH:  "EmlSinh",
    NodeKind.COSH:  "EmlCosh",
    NodeKind.TANH:  "EmlTanh",
    NodeKind.ASIN:  "EmlAsin",
    NodeKind.ACOS:  "EmlAcos",
    NodeKind.ATAN:  "EmlAtan",
}


class CompileError(Exception):
    """Raised on a NodeKind the Chisel backend doesn't recognize."""


@dataclass
class _Scope:
    width: int
    qformat: QFormat
    instance_counter: int = 0
    wire_counter: int = 0
    decls: list[str] = field(default_factory=list)
    """Indented Chisel statements: `val w1 = a + b` etc."""
    node_wires: dict[int, str] = field(default_factory=dict)

    def fresh_wire(self) -> str:
        self.wire_counter += 1
        return f"w{self.wire_counter}"

    def fresh_instance(self, prefix: str) -> str:
        self.instance_counter += 1
        return f"{prefix}_{self.instance_counter}"


class ChiselBackend:
    """Generate Chisel 3 / Scala source from a module + allocation plan."""

    name = "chisel"

    def __init__(
        self,
        *,
        optimize: bool = True,
        package_name: str = "monogate.gen",
    ) -> None:
        self.optimize = optimize
        self.package_name = package_name

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule, plan: AllocationPlan) -> str:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)
        fpga_funcs = self._collect_fpga_functions(mod)

        chunks: list[str] = [self._header(mod, plan)]
        for fn in fpga_funcs:
            chunks.append(self._emit_function(fn, plan))
        return "\n\n".join(chunks).rstrip() + "\n"

    # ── Helpers ───────────────────────────────────────────────

    def _collect_fpga_functions(
        self, mod: EMLModule,
    ) -> list[EMLFunction]:
        out: list[EMLFunction] = []
        for fn in mod.functions:
            for a in fn.annotations:
                if a.kind == "target" and a.args.get(0) == "fpga":
                    out.append(fn)
                    break
        return out

    def _header(self, mod: EMLModule, plan: AllocationPlan) -> str:
        return (
            f"// Generated by EML-lang Chisel backend\n"
            f"// Source module: {mod.name or '(unnamed)'}\n"
            f"// Source file:   {mod.source_file}\n"
            f"//\n"
            f"// Target device: {plan.target_device}\n"
            f"// Pipeline depth: {plan.pipeline_depth} stages\n"
            f"// Estimated:    {plan.estimated_luts} LUTs, "
            f"{plan.estimated_dsps} DSPs, "
            f"{plan.estimated_bram_kb} KB BRAM\n"
            f"// Throughput:   {plan.throughput_msps:.1f} Msamples/s "
            f"@ {plan.clock_mhz} MHz\n"
            f"\n"
            f"package {self.package_name}\n"
            f"\n"
            f"import chisel3._\n"
            f"import chisel3.util._"
        )

    def _emit_refinement_guards(self, fn: EMLFunction) -> str:
        """Return chisel3.assert() guard lines per refined parameter (Phase E.5).

        Idiom: chisel3.assert(cond, "msg")
        Cross-param refinements emit comment lines.
        ABS uses Mux(x < 0.S, -x, x) per Hard Contract #3.
        """
        param_names = {p.name for p in fn.params}
        lines: list[str] = []
        for p in fn.params:
            if p.refinement is None:
                continue
            ref = p.refinement
            pred = _substitute_var(ref.predicate, ref.binder, p.name)
            pred_vars = _var_names(pred)
            other_params = (pred_vars - {p.name}) & param_names
            if other_params:
                cond_str = _chisel_pred_expr(pred)
                lines.append(
                    f"  // refinement obligation: {fn.name}: {p.name}: {cond_str}"
                )
                continue
            cond = _chisel_pred_expr(pred)
            msg = f"{fn.name}: refinement violated on {p.name}: {cond}"
            lines.append(
                f'  chisel3.assert({cond}, "{msg}")'
            )
        if not lines:
            return ""
        return (
            "\n  // Refinement guards (Phase E.5)\n"
            + "\n".join(lines)
            + "\n"
        )

    def _emit_function(
        self, fn: EMLFunction, plan: AllocationPlan,
    ) -> str:
        width = self._design_precision(fn, plan)
        qfmt = default_q(width)
        scope = _Scope(width=width, qformat=qfmt)

        try:
            output_wire = self._emit_expr(self._final_expr(fn), scope)
        except CompileError as e:
            return (
                f"// {fn.name}: emission failed ({e})\n"
                f"// (function body has constructs the Chisel "
                f"backend doesn't yet support)"
            )

        param_pieces = [
            f"    val {p.name} = Input(SInt(width.W))"
            for p in fn.params
        ]
        param_block = "\n".join(param_pieces)

        co = (fn.profile or {}).get("chain_order", "?")
        cc = (fn.profile or {}).get("cost_class", "?")
        depth = (fn.profile or {}).get("eml_depth", "?")

        body_lines = "\n".join(scope.decls) if scope.decls else (
            "    // (constant body -- no intermediates)"
        )

        # Phase E.5: refinement guards.
        refinement_block = self._emit_refinement_guards(fn)

        klass = self._class_name(fn.name)
        return (
            f"// Pipeline: {fn.name}\n"
            f"// Chain order: {co}     Cost class: {cc}\n"
            f"// EML depth:   {depth}  Width: {width} bits\n"
            f"class {klass}(width: Int = {width}) extends Module {{\n"
            f"  val io = IO(new Bundle {{\n"
            f"    val validIn  = Input(Bool())\n"
            f"{param_block}\n"
            f"    val validOut = Output(Bool())\n"
            f"    val result   = Output(SInt(width.W))\n"
            f"  }})\n"
            f"\n"
            f"  // Bind every input parameter to a local val so the\n"
            f"  // expression tree below can reference plain names.\n"
            f"{self._bind_params(fn)}\n"
            f"{refinement_block}"
            f"\n"
            f"{body_lines}\n"
            f"\n"
            f"  // Registered output: one cycle latency between\n"
            f"  // validIn and validOut (combinational body).\n"
            f"  io.validOut := RegNext(io.validIn, init = false.B)\n"
            f"  io.result   := RegNext({output_wire}, init = 0.S(width.W))\n"
            f"}}\n"
        )

    def _bind_params(self, fn: EMLFunction) -> str:
        if not fn.params:
            return "  // (no parameters)"
        return "\n".join(
            f"  val {p.name} = io.{p.name}" for p in fn.params
        )

    @staticmethod
    def _class_name(fn_name: str) -> str:
        # snake_case -> CamelCase + Pipeline suffix
        return "".join(w.capitalize() for w in fn_name.split("_")) + "Pipeline"

    @staticmethod
    def _final_expr(fn: EMLFunction) -> ASTNode:
        if fn.body is None or fn.body.kind != NodeKind.BLOCK:
            raise CompileError(f"function {fn.name} has no parsed body")
        bindings: dict[str, ASTNode] = {}
        final: ASTNode | None = None
        for stmt in fn.body.children:
            if stmt.kind == NodeKind.LET:
                bindings[stmt.value] = stmt.children[0]
            elif stmt.kind in (NodeKind.LET_MUT, NodeKind.WHILE,
                               NodeKind.ASSIGN, NodeKind.EXPR_STMT):
                continue
            else:
                final = stmt
        if final is None:
            raise CompileError(
                f"function {fn.name} has no final expression"
            )
        if bindings:
            final = _inline(final, bindings)
        return final

    def _design_precision(
        self, fn: EMLFunction, plan: AllocationPlan,
    ) -> int:
        if plan.transcendental_units:
            return max(u.precision_bits for u in plan.transcendental_units)
        co = (fn.profile or {}).get("chain_order", 0)
        if co >= 3:
            return 64
        if co >= 1:
            return 32
        return 32

    # ── Expression emission ──────────────────────────────────

    def _emit_expr(self, node: ASTNode, scope: _Scope) -> str:
        cache_key = id(node)
        if cache_key in scope.node_wires:
            return scope.node_wires[cache_key]

        kind = node.kind
        out_name: str

        if kind == NodeKind.LITERAL:
            out_name = self._literal(node, scope)
        elif kind == NodeKind.VAR:
            out_name = str(node.value)
        elif kind == NodeKind.UNARYOP:
            sub = self._emit_expr(node.children[0], scope)
            out_name = scope.fresh_wire()
            if node.value == "-":
                scope.decls.append(f"  val {out_name} = -{sub}")
            elif node.value == "!":
                scope.decls.append(f"  val {out_name} = !{sub}")
            else:
                raise CompileError(f"unary {node.value!r}")
        elif kind == NodeKind.BINOP:
            left = self._emit_expr(node.children[0], scope)
            right = self._emit_expr(node.children[1], scope)
            op = _BINOP_TO_CHISEL.get(node.value)
            if op is None:
                raise CompileError(f"binop {node.value!r}")
            out_name = scope.fresh_wire()
            scope.decls.append(
                f"  val {out_name} = {left} {op} {right}"
            )
        elif kind in _TRANSCENDENTAL_TO_MODULE:
            out_name = self._instance(
                _TRANSCENDENTAL_TO_MODULE[kind],
                node.children, scope,
            )
        elif kind == NodeKind.EML:
            x_in = self._emit_expr(node.children[0], scope)
            y_in = self._emit_expr(node.children[1], scope)
            exp_out = self._instance_raw("EmlExp", [x_in], scope)
            ln_out = self._instance_raw("EmlLn", [y_in], scope)
            out_name = scope.fresh_wire()
            scope.decls.append(f"  val {out_name} = {exp_out} - {ln_out}")
        elif kind == NodeKind.CLAMP:
            x_w = self._emit_expr(node.children[0], scope)
            lo_w = self._emit_expr(node.children[1], scope)
            hi_w = self._emit_expr(node.children[2], scope)
            out_name = scope.fresh_wire()
            scope.decls.append(
                f"  val {out_name} = "
                f"Mux({x_w} < {lo_w}, {lo_w}, "
                f"Mux({x_w} > {hi_w}, {hi_w}, {x_w}))"
            )
        elif kind == NodeKind.ABS:
            sub = self._emit_expr(node.children[0], scope)
            out_name = scope.fresh_wire()
            scope.decls.append(
                f"  val {out_name} = Mux({sub} < 0.S, -{sub}, {sub})"
            )
        elif kind == NodeKind.POW:
            out_name = self._instance("EmlPow", node.children, scope)
        elif kind == NodeKind.CALL:
            arg_wires = [self._emit_expr(c, scope) for c in node.children]
            mod_class = self._class_name(str(node.value))
            out_name = self._instance_raw(mod_class, arg_wires, scope)
        else:
            raise CompileError(
                f"NodeKind {kind} (line {node.line}:{node.col})"
            )

        scope.node_wires[cache_key] = out_name
        return out_name

    def _literal(self, node: ASTNode, scope: _Scope) -> str:
        v = node.value
        out = scope.fresh_wire()
        if isinstance(v, bool):
            scope.decls.append(
                f"  val {out} = ({1 if v else 0}).S(width.W)"
            )
            return out
        if isinstance(v, (int, float)):
            verilog_lit = format_verilog_literal(v, scope.qformat)
            int_part = _extract_signed_int(verilog_lit)
            scope.decls.append(
                f"  val {out} = ({int_part}).S(width.W) // {v}"
            )
            return out
        raise CompileError(f"literal {v!r}")

    def _instance(
        self, module_class: str, arg_nodes: list[ASTNode], scope: _Scope,
    ) -> str:
        arg_wires = [self._emit_expr(c, scope) for c in arg_nodes]
        return self._instance_raw(module_class, arg_wires, scope)

    def _instance_raw(
        self, module_class: str, arg_wires: list[str], scope: _Scope,
    ) -> str:
        out = scope.fresh_wire()
        inst_name = scope.fresh_instance(module_class.lower())
        scope.decls.append(f"  val {inst_name} = Module(new {module_class}(width))")
        scope.decls.append(f"  {inst_name}.io.validIn := io.validIn")
        for i, w in enumerate(arg_wires):
            scope.decls.append(f"  {inst_name}.io.x{i} := {w}")
        scope.decls.append(f"  val {out} = {inst_name}.io.result")
        return out


def _inline(node: ASTNode, bindings: dict[str, ASTNode]) -> ASTNode:
    if node.kind == NodeKind.VAR and node.value in bindings:
        return _inline(bindings[node.value], bindings)
    new_children = [_inline(c, bindings) for c in node.children]
    return ASTNode(
        kind=node.kind,
        value=node.value,
        children=new_children,
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line,
        col=node.col,
    )


def _extract_signed_int(verilog_literal: str) -> str:
    """Recover the integer portion of a Q-format Verilog literal so
    we can re-emit it as a Scala literal."""
    s = verilog_literal.strip()
    sign = ""
    if s.startswith("-"):
        sign = "-"
        s = s[1:]
    if "'sd" in s:
        return sign + s.split("'sd", 1)[1]
    if "'sh" in s:
        hex_part = s.split("'sh", 1)[1]
        try:
            return sign + str(int(hex_part, 16))
        except ValueError:
            return "0"
    return sign + "0"
