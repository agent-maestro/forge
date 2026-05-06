"""Verilog backend -- emits parametric synthesizable Verilog.

Consumes (EMLModule + AllocationPlan) from Phase 3.1's allocator
and produces a Verilog source file suitable for `verilator
--lint-only` and Vivado/yosys synthesis.

Approach
========

Combinational AST translation (no manual pipelining for the first
cut). Each function becomes one module with:

  - clk, rst, valid_in inputs
  - one input port per parameter (signed [WIDTH-1:0])
  - intermediate `wire` declarations for every binop / call result
  - `assign` chain expressing the function body
  - registered output (one cycle latency)

Transcendental ops (exp/ln/sin/cos/tan/sqrt) become instantiations
of `eml_<op>` modules from `hardware/modules/transcendental/`.
Those module bodies (CORDIC implementations) live in the runtime
HDL library; Phase 3.3 wires them in and Verilator simulates the
combination.

Reference: lang/spec/EML_LANG_DESIGN.md section 3.2.
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


# Verilog operator string per BINOP value (reused for predicate rendering).
_BINOP_PRED: dict[str, str] = {
    "+": "+", "-": "-", "*": "*", "/": "/",
    "<": "<", ">": ">", "<=": "<=", ">=": ">=",
    "==": "==", "!=": "!=",
    "&&": "&&", "||": "||",
}


def _verilog_pred_expr(node: ASTNode) -> str:
    """Render a predicate AST node as a Verilog expression string.

    Used for sim-time $display guards (not synthesizable; inside
    pragma translate_off blocks). ABS uses inline ternary per
    Hard Contract #3: (x < 0 ? -x : x).
    """
    kind = node.kind
    if kind == NodeKind.LITERAL:
        v = node.value
        if isinstance(v, bool):
            return "1'b1" if v else "1'b0"
        if isinstance(v, (int, float)):
            # Emit as a plain decimal for readability in sim messages.
            return repr(v)
        return repr(v)
    if kind == NodeKind.VAR:
        return str(node.value)
    if kind == NodeKind.UNARYOP:
        sub = _verilog_pred_expr(node.children[0])
        return f"({node.value}{sub})"
    if kind == NodeKind.BINOP:
        left = _verilog_pred_expr(node.children[0])
        right = _verilog_pred_expr(node.children[1])
        op = _BINOP_PRED.get(node.value, node.value)
        return f"({left} {op} {right})"
    if kind == NodeKind.ABS:
        sub = _verilog_pred_expr(node.children[0])
        # Verilog: no abs primitive; inline ternary per Hard Contract #3.
        return f"({sub} < 0 ? -{sub} : {sub})"
    # Fallback: function-call style
    args = ", ".join(_verilog_pred_expr(c) for c in node.children)
    return f"{kind.name.lower()}({args})"


# Verilog operator string per BINOP value.
_BINOP_TO_VERILOG: dict[str, str] = {
    "+": "+", "-": "-", "*": "*", "/": "/",
    "<": "<", ">": ">", "<=": "<=", ">=": ">=",
    "==": "==", "!=": "!=",
    "&&": "&&", "||": "||",
}


# NodeKind -> module name in hardware/modules/transcendental/
_TRANSCENDENTAL_TO_MODULE: dict[NodeKind, str] = {
    NodeKind.EXP:   "eml_exp",
    NodeKind.LN:    "eml_ln",
    NodeKind.SIN:   "eml_sin",
    NodeKind.COS:   "eml_cos",
    NodeKind.TAN:   "eml_tan",
    NodeKind.SQRT:  "eml_sqrt",
    NodeKind.SINH:  "eml_sinh",
    NodeKind.COSH:  "eml_cosh",
    NodeKind.TANH:  "eml_tanh",
    NodeKind.ASIN:  "eml_asin",
    NodeKind.ACOS:  "eml_acos",
    NodeKind.ATAN:  "eml_atan",
}


class CompileError(Exception):
    """Raised on a NodeKind the Verilog backend doesn't recognize."""


@dataclass
class _ModuleScope:
    """Per-function emission scope -- accumulates wire decls,
    assigns, instances as we walk the AST."""
    width: int
    qformat: QFormat
    instance_counter: int = 0
    wire_counter: int = 0
    wire_decls: list[str] = field(default_factory=list)
    assigns: list[str] = field(default_factory=list)
    instances: list[str] = field(default_factory=list)
    # Map AST node id -> wire name (so we can reuse intermediate
    # results when the same subexpression appears multiple times).
    node_wires: dict[int, str] = field(default_factory=dict)

    def fresh_wire(self) -> str:
        self.wire_counter += 1
        name = f"_w{self.wire_counter}"
        self.wire_decls.append(
            f"    wire signed [WIDTH-1:0] {name};"
        )
        return name

    def fresh_instance(self, prefix: str) -> str:
        self.instance_counter += 1
        return f"{prefix}_{self.instance_counter}"


class VerilogBackend:
    """Generate synthesizable Verilog from a module + allocation plan."""

    name = "verilog"

    def __init__(self, *, optimize: bool = True) -> None:
        self.optimize = optimize

    # ── Public API ────────────────────────────────────────────

    def compile(
        self,
        mod: EMLModule,
        plan: AllocationPlan,
    ) -> str:
        """Emit Verilog source covering every @target(fpga) function
        plus a header comment with the allocation summary."""
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)
        fpga_funcs = self._collect_fpga_functions(mod)

        chunks: list[str] = [self._header(mod, plan)]

        # Emit a forward declaration for every transcendental module
        # the design references. Bodies live in
        # hardware/modules/transcendental/.
        decls = self._transcendental_decls(plan)
        if decls:
            chunks.append(decls)

        # Per-function pipeline modules.
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
            f"// Generated by EML-lang Verilog backend\n"
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
            f"`default_nettype none"
        )

    def _transcendental_decls(self, plan: AllocationPlan) -> str:
        """Emit a comment block listing the transcendental modules
        the design references. Real bodies live in
        hardware/modules/transcendental/<module>.v."""
        if not plan.transcendental_units:
            return ""
        lines = [
            "// Transcendental modules referenced by this design",
            "// (bodies live in hardware/modules/transcendental/):",
        ]
        for u in plan.transcendental_units:
            lines.append(
                f"//   {u.op:<5}  count={u.count}  sharing={u.sharing}  "
                f"precision={u.precision_bits}-bit"
            )
        return "\n".join(lines)

    def _emit_refinement_guards(self, fn: EMLFunction) -> str:
        """Return pragma translate_off / sim-time $display guards (Phase E.5).

        Idiom: synth-tool-friendly sim-time check inside a translate_off block.
          `pragma translate_off
          always @(posedge clk) begin
              if (!(cond)) $display("...");
          end
          `pragma translate_on

        ABS uses inline ternary (x < 0 ? -x : x) per Hard Contract #3.
        Cross-param refinements emit a comment-only line.
        """
        param_names = {p.name for p in fn.params}
        guard_lines: list[str] = []
        for p in fn.params:
            if p.refinement is None:
                continue
            ref = p.refinement
            pred = _substitute_var(ref.predicate, ref.binder, p.name)
            pred_vars = _var_names(pred)
            other_params = (pred_vars - {p.name}) & param_names
            if other_params:
                cond_str = _verilog_pred_expr(pred)
                guard_lines.append(
                    f"    // refinement obligation: {fn.name}: {p.name}: {cond_str}"
                )
                continue
            cond = _verilog_pred_expr(pred)
            msg = f"{fn.name}: refinement violated on {p.name}: {cond}"
            guard_lines.append(
                f"    `pragma translate_off\n"
                f"    always @(posedge clk) begin\n"
                f'        if (!({cond})) $display("{msg}");\n'
                f"    end\n"
                f"    `pragma translate_on"
            )
        if not guard_lines:
            return ""
        return "\n" + "\n".join(guard_lines) + "\n"

    def _emit_function(
        self, fn: EMLFunction, plan: AllocationPlan,
    ) -> str:
        """One pipeline module per @target(fpga) function."""
        # WIDTH from the plan's design precision (worst case across
        # the design; safe upper bound for any single function).
        width = self._design_precision(fn, plan)
        qfmt = default_q(width)
        scope = _ModuleScope(width=width, qformat=qfmt)

        # Walk the AST; final wire is the output.
        try:
            output_wire = self._emit_expr(self._final_expr(fn), scope)
        except CompileError as e:
            return (
                f"// {fn.name}: emission failed ({e})\n"
                f"// (function body has constructs the Verilog "
                f"backend doesn't yet support)"
            )

        # Build the parameter port list.
        param_ports = ",\n    ".join(
            f"input  wire signed [WIDTH-1:0] {p.name}"
            for p in fn.params
        )

        # Stitch the module.
        co = (fn.profile or {}).get("chain_order", "?")
        cc = (fn.profile or {}).get("cost_class", "?")
        depth = (fn.profile or {}).get("eml_depth", "?")

        decls = "\n".join(scope.wire_decls)
        instances = "\n".join(scope.instances)
        assigns = "\n".join(scope.assigns)

        body_sections = [s for s in (decls, instances, assigns) if s]
        body_block = "\n\n".join(body_sections) if body_sections else (
            "    // (constant body -- no intermediates)"
        )

        # Phase E.5: sim-time refinement guards (synth-tool-safe).
        refinement_block = self._emit_refinement_guards(fn)

        # Phase G: assume clauses -- comment-only (no sim-time guard).
        assume_comments = ""
        for a in fn.assumes:
            try:
                pred_str = _verilog_pred_expr(a)
                assume_comments += f"    // assume: {pred_str}\n"
            except Exception as e:
                assume_comments += f"    // assume: unsupported ({e})\n"

        return (
            f"// Pipeline: {fn.name}\n"
            f"// Chain order: {co}     Cost class: {cc}\n"
            f"// EML depth:   {depth}  Width: {width} bits\n"
            f"module {fn.name}_pipeline #(\n"
            f"    parameter WIDTH = {width}\n"
            f") (\n"
            f"    input  wire             clk,\n"
            f"    input  wire             rst,\n"
            f"    input  wire             valid_in,\n"
            f"    {param_ports},\n"
            f"    output reg              valid_out,\n"
            f"    output reg signed [WIDTH-1:0] result\n"
            f");\n"
            f"\n"
            f"{body_block}\n"
            f"{refinement_block}"
            f"{assume_comments}"
            f"\n"
            f"    // Registered output: one cycle latency between\n"
            f"    // valid_in and valid_out (combinational body).\n"
            f"    always @(posedge clk) begin\n"
            f"        if (rst) begin\n"
            f"            valid_out <= 1'b0;\n"
            f"            result    <= '0;\n"
            f"        end else begin\n"
            f"            valid_out <= valid_in;\n"
            f"            result    <= {output_wire};\n"
            f"        end\n"
            f"    end\n"
            f"\n"
            f"endmodule\n"
        )

    @staticmethod
    def _final_expr(fn: EMLFunction) -> ASTNode:
        """Reduce the function body to its return expression. For
        single-expression bodies (no let/while), this is just the
        last child of the BLOCK node."""
        if fn.body is None or fn.body.kind != NodeKind.BLOCK:
            raise CompileError(f"function {fn.name} has no parsed body")
        # Walk children in order, inlining LETs into a substitution
        # map (so the final expression sees the let-bound names).
        # WHILE / ASSIGN / EXPR_STMT are silently dropped; this
        # backend doesn't yet handle iterative bodies.
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
                f"function {fn.name} has no final expression "
                f"(maybe it's a complex iterative body?)"
            )
        if bindings:
            final = _inline(final, bindings)
        return final

    def _design_precision(
        self, fn: EMLFunction, plan: AllocationPlan,
    ) -> int:
        """Use the plan's per-unit precision when available, else
        fall back to the function's chain-order rule."""
        if plan.transcendental_units:
            return max(u.precision_bits for u in plan.transcendental_units)
        co = (fn.profile or {}).get("chain_order", 0)
        if co >= 3:
            return 64
        if co >= 1:
            return 32
        return 32  # default for polynomial bodies

    # ── Expression emission to wire chains ────────────────────

    def _emit_expr(
        self, node: ASTNode, scope: _ModuleScope,
    ) -> str:
        """Walk an AST expression bottom-up; emit `wire` decls and
        `assign` statements; return the wire name carrying the
        expression's value. Caches results so a subexpression
        appearing twice only computes once."""
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
                scope.assigns.append(f"    assign {out_name} = -{sub};")
            elif node.value == "!":
                scope.assigns.append(f"    assign {out_name} = !{sub};")
            else:
                raise CompileError(f"unary {node.value!r}")
        elif kind == NodeKind.BINOP:
            left = self._emit_expr(node.children[0], scope)
            right = self._emit_expr(node.children[1], scope)
            op = _BINOP_TO_VERILOG.get(node.value)
            if op is None:
                raise CompileError(f"binop {node.value!r}")
            out_name = scope.fresh_wire()
            scope.assigns.append(
                f"    assign {out_name} = {left} {op} {right};"
            )
        elif kind in _TRANSCENDENTAL_TO_MODULE:
            out_name = self._instance(
                _TRANSCENDENTAL_TO_MODULE[kind],
                node.children, scope,
            )
        elif kind == NodeKind.EML:
            # EML(x, y) = exp(x) - ln(y)
            x_in = self._emit_expr(node.children[0], scope)
            y_in = self._emit_expr(node.children[1], scope)
            exp_out = self._instance_raw("eml_exp", [x_in], scope)
            ln_out = self._instance_raw("eml_ln", [y_in], scope)
            out_name = scope.fresh_wire()
            scope.assigns.append(
                f"    assign {out_name} = {exp_out} - {ln_out};"
            )
        elif kind == NodeKind.CLAMP:
            # clamp(x, lo, hi) -> (x < lo) ? lo : (x > hi) ? hi : x
            x_w = self._emit_expr(node.children[0], scope)
            lo_w = self._emit_expr(node.children[1], scope)
            hi_w = self._emit_expr(node.children[2], scope)
            out_name = scope.fresh_wire()
            scope.assigns.append(
                f"    assign {out_name} = "
                f"({x_w} < {lo_w}) ? {lo_w} : "
                f"(({x_w} > {hi_w}) ? {hi_w} : {x_w});"
            )
        elif kind == NodeKind.ABS:
            sub = self._emit_expr(node.children[0], scope)
            out_name = scope.fresh_wire()
            scope.assigns.append(
                f"    assign {out_name} = ({sub} < 0) ? -{sub} : {sub};"
            )
        elif kind == NodeKind.POW:
            # POW lowers to a sub-instance like other transcendentals.
            out_name = self._instance("eml_pow", node.children, scope)
        elif kind == NodeKind.CALL:
            # User function calls -- emit as a sub-pipeline
            # instance. Phase 3.3 hooks the actual interconnect.
            arg_wires = [
                self._emit_expr(c, scope) for c in node.children
            ]
            out_name = self._instance_raw(
                f"{node.value}_pipeline", arg_wires, scope,
            )
        else:
            raise CompileError(
                f"NodeKind {kind} (line {node.line}:{node.col})"
            )

        scope.node_wires[cache_key] = out_name
        return out_name

    def _literal(
        self, node: ASTNode, scope: _ModuleScope,
    ) -> str:
        """Emit a numeric literal. Floats + ints get Q-format encoded
        per the function's WIDTH/FRAC; the Verilog literal is a
        sized signed-decimal integer with the original value in a
        comment for traceability."""
        v = node.value
        out = scope.fresh_wire()
        if isinstance(v, bool):
            scope.assigns.append(
                f"    assign {out} = {1 if v else 0};"
            )
            return out
        if isinstance(v, (int, float)):
            literal = format_verilog_literal(v, scope.qformat)
            scope.assigns.append(
                f"    assign {out} = {literal};  // {v}"
            )
            return out
        raise CompileError(f"literal {v!r}")

    def _instance(
        self, module_name: str, arg_nodes: list[ASTNode],
        scope: _ModuleScope,
    ) -> str:
        arg_wires = [self._emit_expr(c, scope) for c in arg_nodes]
        return self._instance_raw(module_name, arg_wires, scope)

    def _instance_raw(
        self, module_name: str, arg_wires: list[str],
        scope: _ModuleScope,
    ) -> str:
        """Emit a sub-module instantiation; return the result wire."""
        out = scope.fresh_wire()
        inst_name = scope.fresh_instance(module_name)
        # Standard port convention: clk, rst, valid_in, then arg
        # wires by position, then valid_out + result.
        ports = ", ".join(f".x{i}({w})" for i, w in enumerate(arg_wires))
        scope.instances.append(
            f"    {module_name} #(.WIDTH(WIDTH)) {inst_name} (\n"
            f"        .clk(clk), .rst(rst), .valid_in(valid_in),\n"
            f"        {ports},\n"
            f"        .valid_out(/* unused */), .result({out})\n"
            f"    );"
        )
        return out


def _inline(node: ASTNode, bindings: dict[str, ASTNode]) -> ASTNode:
    """Substitute let-bound vars with their RHS subtrees."""
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
