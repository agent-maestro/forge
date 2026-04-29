"""`eml-compile --explain` -- show what the optimizer did.

Renders a per-function diff comparing the parser-output AST to
the post-optimizer AST. For each function it reports:

  - Node-count delta (before -> after)
  - Whether each pass fired (inline / fold / CSE / SuperBEST /
    tree-shake)
  - SuperBEST family + digits saved when applicable
  - CSE binding count

Emits no backend code; it's a developer-facing diagnostic.
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


def print_explain_report(mod: EMLModule) -> None:
    """Print the explain report for `mod` to stdout."""
    sys.stdout.write(_format_module(mod))


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
    out.append(f"## module-level passes")
    out.append(
        f"  - imports         : {n_imported_in} brought in, "
        f"{n_imported_in - n_imported_after} dropped by tree-shake"
    )
    n_inline_changes = _count_inlined_calls(mod, after_inline)
    out.append(
        f"  - inline_calls    : {n_inline_changes} CALL site(s) "
        f"replaced with callee body"
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
        return [f"  {before.name}: dropped by tree-shake"]
    nb = _node_count(before.body) if before.body else 0
    na = _node_count(after.body) if after.body else 0
    delta = na - nb
    sign = "+" if delta > 0 else ""
    lines = [
        f"  {before.name}",
        f"    nodes: {nb} -> {na} ({sign}{delta})",
    ]
    # CSE bindings introduced
    if after.body and after.body.kind == NodeKind.BLOCK:
        cse_lets = [
            c for c in after.body.children
            if c.kind == NodeKind.LET
            and isinstance(c.value, str)
            and c.value.startswith("_cse_")
        ]
        if cse_lets:
            lines.append(
                f"    cse bindings: {len(cse_lets)} hoisted "
                f"({', '.join(c.value for c in cse_lets)})"
            )
    # SuperBEST hit
    if after.profile and after.profile.get("superbest_family"):
        lines.append(
            f"    superbest: rewrote to {after.profile['superbest_family']}"
            f" canonical form (saved "
            f"{after.profile['superbest_digits_saved']:.2f} digits)"
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
