"""Import resolver -- finds, parses, caches, and merges modules."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from lang.parser.ast_nodes import (
    EMLConstant,
    EMLFunction,
    EMLImport,
    EMLModule,
    EMLTypeAlias,
)


# Repo root -- two levels up from this file (lang/loader/resolver.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]


# Search-path table mapping the FIRST path segment to a directory.
# When `use stdlib::math;` is parsed, the loader looks for
# `<DEFAULT_SEARCH_PATHS["stdlib"]>/math.eml`.
DEFAULT_SEARCH_PATHS: dict[str, Path] = {
    "stdlib": _REPO_ROOT / "lang" / "spec" / "stdlib",
}


class LoaderError(Exception):
    """Loader-level error: not-found, cycle, or symbol clash."""


@dataclass
class ModuleLoader:
    """Resolves + parses + caches imports.

    Construct one per parse session if you want test isolation;
    construct one and reuse it across many parse calls if you
    want maximum cache hit rate."""
    search_paths: dict[str, Path] = field(
        default_factory=lambda: dict(DEFAULT_SEARCH_PATHS),
    )
    cache: dict[str, EMLModule] = field(default_factory=dict)
    _in_progress: set[str] = field(default_factory=set)

    def load(self, joined_path: str) -> EMLModule:
        """Load the module identified by `joined_path` (e.g.
        'stdlib::math'). Returns the (cached) parsed EMLModule.

        Raises LoaderError on:
          - unknown root segment ('foo' not in search_paths)
          - missing .eml file
          - import cycle (path already in self._in_progress)
        """
        if joined_path in self.cache:
            return self.cache[joined_path]

        if joined_path in self._in_progress:
            raise LoaderError(
                f"import cycle while loading {joined_path!r} "
                f"(in-progress: {sorted(self._in_progress)})"
            )

        file_path = self.resolve(joined_path)
        if not file_path.is_file():
            raise LoaderError(
                f"module {joined_path!r} not found "
                f"(looked for {file_path})"
            )

        # Local import to avoid a parser <-> loader import cycle.
        from lang.parser.parser import parse_source

        self._in_progress.add(joined_path)
        try:
            text = file_path.read_text(encoding="utf-8")
            mod = parse_source(text, source_file=str(file_path))
            # Recursively resolve transitive imports BEFORE caching.
            mod = resolve_imports(mod, loader=self)
            self.cache[joined_path] = mod
            return mod
        finally:
            self._in_progress.discard(joined_path)

    def resolve(self, joined_path: str) -> Path:
        """Translate `<root>::<name>(::<sub>...)` into a file path
        without loading. Raises LoaderError on unknown root."""
        parts = joined_path.split("::")
        if len(parts) < 2:
            raise LoaderError(
                f"path {joined_path!r} must have at least 2 segments"
            )
        root, *rest = parts
        if root not in self.search_paths:
            raise LoaderError(
                f"unknown import root {root!r} "
                f"(known: {sorted(self.search_paths)})"
            )
        # rest = ["math"]      -> stdlib/math.eml
        # rest = ["foo", "bar"] -> stdlib/foo/bar.eml
        rel = Path(*rest[:-1]) / f"{rest[-1]}.eml"
        return self.search_paths[root] / rel


def resolve_imports(
    mod: EMLModule,
    *,
    loader: ModuleLoader | None = None,
) -> EMLModule:
    """Return a new EMLModule with every `use ...;` import resolved
    and its constants/types/functions merged into `mod`'s namespace.

    Conflicts (an imported name collides with a local one, or two
    imports both define the same name) raise LoaderError. Modules
    with no imports pass through untouched.
    """
    if not mod.imports:
        return mod

    if loader is None:
        loader = ModuleLoader()

    out = deepcopy(mod)

    # Build name tables seeded with the local module's own decls.
    # Imports CANNOT shadow a locally-defined name; the local
    # definition wins and the import is rejected as a clash so the
    # author sees the conflict explicitly.
    const_names = {c.name for c in out.constants}
    type_names = {t.name for t in out.types}
    func_names = {f.name for f in out.functions}

    # Track which import provided each name so error messages can
    # point at the offending source.
    provided_by: dict[str, str] = {}

    for imp in mod.imports:
        sub = loader.load(imp.joined)

        for c in sub.constants:
            _check_clash(c.name, "constant", imp, provided_by,
                         local_names=const_names)
            out.constants.append(deepcopy(c))
            const_names.add(c.name)
            provided_by[c.name] = imp.joined

        for t in sub.types:
            _check_clash(t.name, "type alias", imp, provided_by,
                         local_names=type_names)
            out.types.append(deepcopy(t))
            type_names.add(t.name)
            provided_by[t.name] = imp.joined

        for f in sub.functions:
            _check_clash(f.name, "function", imp, provided_by,
                         local_names=func_names)
            new_fn = deepcopy(f)
            # Tag for the tree-shaker: this function arrived via
            # `use ...;` and is droppable if no local function
            # ends up calling it.
            new_fn.imported_from = imp.joined
            out.functions.append(new_fn)
            func_names.add(f.name)
            provided_by[f.name] = imp.joined

    return out


def _check_clash(
    name: str, kind: str, imp: EMLImport,
    provided_by: dict[str, str],
    *,
    local_names: set[str],
) -> None:
    """Raise if `name` is already in scope, distinguishing local
    redefinitions from import conflicts in the message."""
    if name in local_names:
        # Was it locally-defined or imported earlier?
        if name in provided_by:
            raise LoaderError(
                f"`use {imp.joined};` brings in {kind} {name!r}, "
                f"but it was already imported via "
                f"`{provided_by[name]}`",
            )
        raise LoaderError(
            f"`use {imp.joined};` brings in {kind} {name!r}, "
            f"but the importing module already defines that name",
        )
