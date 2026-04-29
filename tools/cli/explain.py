"""`eml-compile --explain` -- show what the optimizer did.

Renders a per-function diff comparing the parser-output AST to
the post-optimizer AST. For each function it reports:

  - Node-count delta (before -> after)
  - Whether each pass fired (inline / fold / CSE / SuperBEST /
    tree-shake)
  - SuperBEST family + digits saved when applicable
  - CSE binding count

Emits no backend code; it's a developer-facing diagnostic.

Multi-target mode (--backend-stats): also reports per-backend
artifact sizes (C source LOC, Rust source LOC, Verilog module
count when @target(fpga) functions exist) so users can compare
codegen footprints across targets.
"""

from __future__ import annotations

import sys

from lang.optimizer import (
    apply_cse,
    fold_constants,
    inline_calls,
    shake_imports,
    superbest_module,
)
from lang.optimizer.constant_folding import fold_in_place
from lang.parser.ast_nodes import ASTNode, EMLFunction, EMLModule, NodeKind


def print_explain_report(
    mod: EMLModule,
    *,
    include_backend_stats: bool = False,
) -> None:
    """Print the explain report for `mod` to stdout.

    `include_backend_stats=True` adds a section that compiles to
    each available backend (C / Rust / Verilog when an FPGA
    function exists) and reports the emitted-source LOC + struct
    counts. Useful for comparing codegen footprint across targets."""
    sys.stdout.write(_format_module(mod))
    if include_backend_stats:
        sys.stdout.write(_format_backend_stats(mod))


def _format_backend_stats(mod: EMLModule) -> str:
    """Compile to each backend (C, Rust, Verilog when applicable)
    and report emitted-source size metrics."""
    out: list[str] = ["", "## backend codegen footprints"]

    # C
    try:
        from software.backends.c_backend import CBackend
        c_src = CBackend().compile(mod)
        out.append(_size_line("c (gcc)", c_src))
    except Exception as e:
        out.append(f"  c (gcc)         : ERROR -- {e}")

    # Rust
    try:
        from software.backends.rust_backend import RustBackend
        rs_src = RustBackend().compile(mod)
        out.append(_size_line("rust (cargo)", rs_src))
    except Exception as e:
        out.append(f"  rust (cargo)    : ERROR -- {e}")

    # Lean (only when @verify(lean) blocks exist)
    try:
        from software.verification.lean.LeanBackend import LeanBackend
        lean_src = LeanBackend().compile_module(mod)
        if lean_src:
            out.append(_size_line("lean", lean_src))
        else:
            out.append("  lean            : skipped -- no @verify(lean) blocks")
    except Exception as e:
        out.append(f"  lean            : ERROR -- {e}")

    # Verilog (only when @target(fpga) blocks exist)
    fpga_fns = [
        f for f in mod.functions
        if any(
            a.kind == "target"
            and (a.args.get(0) == "fpga" or a.args.get("0") == "fpga")
            for a in f.annotations
        )
    ]
    if fpga_fns:
        try:
            from hardware.allocator import FPGAAllocator
            from hardware.hdl_gen.verilog_backend import VerilogBackend
            plan = FPGAAllocator().allocate(mod)
            v_src = VerilogBackend().compile(mod, plan)
            out.append(_size_line("verilog", v_src))
            n_modules = v_src.count("\nmodule ") + (
                1 if v_src.startswith("module ") else 0
            )
            out.append(
                f"  verilog modules : {n_modules}"
            )
        except Exception as e:
            out.append(f"  verilog         : ERROR -- {e}")
    else:
        out.append(
            "  verilog         : skipped -- no @target(fpga) blocks"
        )
    return "\n".join(out) + "\n"


def _size_line(label: str, source: str) -> str:
    n_lines = source.count("\n") + (0 if source.endswith("\n") else 1)
    n_chars = len(source)
    return (
        f"  {label:16s}: {n_lines:5d} LOC, "
        f"{n_chars:6d} chars"
    )


def _format_module(mod: EMLModule) -> str:
    out: list[str] = [
        f"# eml-compile --explain  module {mod.name or '(unnamed)'}",
        f"# source {mod.source_file}",
        "",
    ]

    # Snapshot the input.
    n_local_in = sum(
        1 for f in mod.functions if f.imported_from is None
    )
    n_imported_in = sum(
        1 for f in mod.functions if f.imported_from is not None
    )

    # Run each pass in isolation so we can count its effect.
    after_inline = inline_calls(mod)
    after_fold_cse = _fold_then_cse_module(after_inline)
    after_superbest = superbest_module(after_fold_cse)
    after_shake = shake_imports(after_superbest)

    n_imported_after = sum(
        1 for f in after_shake.functions if f.imported_from is not None
    )
    out.append("## module-level passes")
    out.append(
        f"  imports         : {n_imported_in} brought in -> "
        f"{n_imported_after} kept "
        f"({n_imported_in - n_imported_after} dropped by tree-shake)"
    )
    n_inline_changes = _count_inlined_calls(mod, after_inline)
    out.append(
        f"  inline_calls    : {n_inline_changes} CALL site(s) "
        f"replaced with callee body"
    )

    # SuperBEST module-wide rollup: how many functions matched a
    # family + total digits saved across the module.
    n_sb_hits = sum(
        1 for f in after_shake.functions
        if (f.profile or {}).get("superbest_family")
    )
    if n_sb_hits:
        total_digits = sum(
            (f.profile or {}).get("superbest_digits_saved", 0.0)
            for f in after_shake.functions
        )
        out.append(
            f"  superbest       : {n_sb_hits} function(s) rewrote "
            f"to canonical form ({total_digits:.2f} total digits saved)"
        )

    # CSE rollup: count hoisted bindings across all functions.
    n_cse_total = 0
    for fn in after_shake.functions:
        if fn.body and fn.body.kind == NodeKind.BLOCK:
            n_cse_total += sum(
                1 for c in fn.body.children
                if c.kind == NodeKind.LET
                and isinstance(c.value, str)
                and c.value.startswith("_cse_")
            )
    if n_cse_total:
        out.append(
            f"  cse             : {n_cse_total} duplicate sub-tree(s) "
            f"hoisted into let-bindings"
        )

    out.append("")

    # Per-function diff.
    out.append("## per-function effects")
    for fn_in in mod.functions:
        if fn_in.imported_from is not None:
            continue  # focus on local functions
        fn_out = next(
            (f for f in after_shake.functions if f.name == fn_in.name),
            None,
        )
        out.extend(_format_function(fn_in, fn_out))
    return "\n".join(out) + "\n"


def _format_function(
    before: EMLFunction, after: EMLFunction | None,
) -> list[str]:
    if after is None:
        return [f"  {before.name}  [dropped by tree-shake]"]
    nb = _node_count(before.body) if before.body else 0
    na = _node_count(after.body) if after.body else 0
    delta = na - nb
    if delta == 0:
        delta_label = "no net change"
    elif delta > 0:
        delta_label = f"+{delta} nodes (inlined work)"
    else:
        delta_label = f"{delta} nodes (folded / hoisted)"

    lines = [
        f"  {before.name}",
        f"    nodes:     {nb} -> {na}  ({delta_label})",
    ]

    # CSE bindings introduced. Count first, name list parenthesized
    # only when it fits without crowding (>= 1 binding).
    if after.body and after.body.kind == NodeKind.BLOCK:
        cse_lets = [
            c for c in after.body.children
            if c.kind == NodeKind.LET
            and isinstance(c.value, str)
            and c.value.startswith("_cse_")
        ]
        if cse_lets:
            n = len(cse_lets)
            names = ", ".join(c.value for c in cse_lets)
            plural = "binding" if n == 1 else "bindings"
            lines.append(
                f"    cse:       {n} {plural} hoisted -- {names}"
            )

    # SuperBEST hit -- digits saved is the headline number.
    if after.profile and after.profile.get("superbest_family"):
        family = after.profile["superbest_family"]
        digits = after.profile["superbest_digits_saved"]
        lines.append(
            f"    superbest: matched {family!r} family, "
            f"saved {digits:.2f} digits of precision"
        )
    return lines


# ── Helpers ──────────────────────────────────────────────────


def _node_count(node: ASTNode) -> int:
    return 1 + sum(_node_count(c) for c in node.children)


def _fold_then_cse_module(mod: EMLModule) -> EMLModule:
    """Run fold + CSE on every function body. Mirrors
    optimize_function but at module scope, returning a new module."""
    from copy import deepcopy
    out = deepcopy(mod)
    new_funcs = []
    for fn in out.functions:
        if fn.body is None:
            new_funcs.append(fn)
            continue
        fn.body = fold_in_place(fn.body)
        fn = apply_cse(fn)
        new_funcs.append(fn)
    out.functions = new_funcs
    return out


def _count_inlined_calls(
    before: EMLModule, after: EMLModule,
) -> int:
    """Count user-CALL nodes that disappeared between `before` and
    `after`. Builtin calls (NodeKind.EXP etc.) don't count."""
    def n_calls(node: ASTNode) -> int:
        c = 1 if node.kind == NodeKind.CALL else 0
        return c + sum(n_calls(ch) for ch in node.children)

    before_total = sum(
        n_calls(f.body) for f in before.functions if f.body
    )
    after_total = sum(
        n_calls(f.body) for f in after.functions if f.body
    )
    return max(0, before_total - after_total)
