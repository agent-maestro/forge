"""Drop imported functions that no local function calls.

The import resolver pulls EVERY function defined by an imported
module into the importing module's namespace. Most are unused;
some can even produce backend-side errors when their parameter
names collide with local module-level constants (Rust's
const-pattern shadowing rule, observed on `pid_integrate(... dt
...)` colliding with a local `const dt = ...`).

This pass walks the call graph starting from every LOCAL
(non-imported) function plus every annotated function (@target,
@verify), collects the set of reachable imports, and drops the
rest.

Local functions are NEVER dropped, even if unreferenced -- the
user wrote them on purpose. Imported functions are dropped
unless something local reaches them.

Idempotence: a second pass finds nothing more to drop.
"""

from __future__ import annotations

from copy import deepcopy

from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    EMLModule,
    NodeKind,
)


def shake_imports(mod: EMLModule) -> EMLModule:
    """Return a new module with unreachable imported functions
    removed. Local functions and constants/types are preserved."""
    out = deepcopy(mod)

    # Two name tables: imported vs local.
    name_to_fn: dict[str, EMLFunction] = {f.name: f for f in out.functions}

    # Roots: every local function. (Local = imported_from is None.)
    roots = {
        f.name for f in out.functions if f.imported_from is None
    }
    if not roots:
        # No local functions -- this is a pure library module being
        # parsed in isolation (e.g. one of the stdlib .eml files in
        # tests/stdlib/). Treat all of them as roots.
        roots = set(name_to_fn)

    # BFS along CALL edges.
    reachable: set[str] = set()
    work: list[str] = list(roots)
    while work:
        name = work.pop()
        if name in reachable:
            continue
        reachable.add(name)
        fn = name_to_fn.get(name)
        if fn is None or fn.body is None:
            continue
        for callee_name in _collect_calls(fn.body):
            if callee_name not in reachable:
                work.append(callee_name)

    # Keep every local function, plus every reached import.
    out.functions = [
        f for f in out.functions
        if f.imported_from is None or f.name in reachable
    ]
    return out


def _collect_calls(node: ASTNode) -> set[str]:
    """Return the set of CALL target names (user-function calls) at
    or beneath `node`. Builtin transcendentals (NodeKind.EXP etc.)
    don't count."""
    out: set[str] = set()
    _walk(node, out)
    return out


def _walk(node: ASTNode, out: set[str]) -> None:
    if node.kind == NodeKind.CALL:
        out.add(node.value)
    for c in node.children:
        _walk(c, out)
