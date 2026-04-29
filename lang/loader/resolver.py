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
#
# The reserved root `"local"` does NOT appear here -- it resolves
# relative to the importing file's directory at load time.
DEFAULT_SEARCH_PATHS: dict[str, Path] = {
    "stdlib": _REPO_ROOT / "lang" / "spec" / "stdlib",
}

LOCAL_ROOT = "local"


class LoaderError(Exception):
    """Loader-level error: not-found, cycle, or symbol clash."""


@dataclass
class ModuleLoader:
    """Resolves + parses + caches imports.

    Construct one per parse session if you want test isolation;
    construct one and reuse it across many parse calls if you
    want maximum cache hit rate.

    Cache keys are RESOLVED file-paths (strings), not joined
    import paths -- so `local::helpers` from `/a/x.eml` and
    `/b/x.eml` correctly cache as two different modules even
    though they share a joined-path spelling."""
    search_paths: dict[str, Path] = field(
        default_factory=lambda: dict(DEFAULT_SEARCH_PATHS),
    )
    cache: dict[str, EMLModule] = field(default_factory=dict)
    _in_progress: set[str] = field(default_factory=set)

    def load(
        self,
        joined_path: str,
        *,
        source_dir: Path | None = None,
    ) -> EMLModule:
        """Load the module identified by `joined_path` (e.g.
        'stdlib::math' or 'local::helpers').

        `source_dir` is the directory of the file doing the import.
        Required when `joined_path` starts with `local::`; ignored
        otherwise.

        Raises LoaderError on:
          - unknown root segment (not in search_paths and not 'local')
          - missing `local::` source_dir
          - missing .eml file
          - import cycle (resolved file path already in progress)
        """
        file_path = self.resolve(joined_path, source_dir=source_dir)
        cache_key = str(file_path.resolve())

        if cache_key in self.cache:
            return self.cache[cache_key]

        if cache_key in self._in_progress:
            raise LoaderError(
                f"import cycle while loading {joined_path!r} "
                f"({file_path}) -- in progress: "
                f"{sorted(self._in_progress)}"
            )

        if not file_path.is_file():
            raise LoaderError(
                f"module {joined_path!r} not found "
                f"(looked for {file_path})"
            )

        # Local import to avoid a parser <-> loader cycle.
        from lang.parser.parser import parse_source

        self._in_progress.add(cache_key)
        try:
            text = file_path.read_text(encoding="utf-8")
            mod = parse_source(text, source_file=str(file_path))
            # Recursively resolve transitive imports BEFORE caching.
            mod = resolve_imports(mod, loader=self)
            self.cache[cache_key] = mod
            return mod
        finally:
            self._in_progress.discard(cache_key)

    def resolve(
        self,
        joined_path: str,
        *,
        source_dir: Path | None = None,
    ) -> Path:
        """Translate `<root>::<name>(::<sub>...)` into a file path
        without loading.

        `local::name` resolves against `source_dir`; every other
        root resolves against `self.search_paths`."""
        parts = joined_path.split("::")
        if len(parts) < 2:
            raise LoaderError(
                f"path {joined_path!r} must have at least 2 segments"
            )
        root, *rest = parts

        if root == LOCAL_ROOT:
            if source_dir is None:
                raise LoaderError(
                    f"`use local::{ '::'.join(rest) };` requires a "
                    f"source-file directory but none was supplied "
                    f"(use parse_file or pass source_dir=)"
                )
            base = source_dir
        else:
            if root not in self.search_paths:
                raise LoaderError(
                    f"unknown import root {root!r} "
                    f"(known: {sorted(self.search_paths) + [LOCAL_ROOT]})"
                )
            base = self.search_paths[root]

        # rest = ["math"]      -> math.eml
        # rest = ["foo", "bar"] -> foo/bar.eml
        rel = Path(*rest[:-1]) / f"{rest[-1]}.eml"
        return base / rel


def resolve_imports(
    mod: EMLModule,
    *,
    loader: ModuleLoader | None = None,
) -> EMLModule:
    """Return a new EMLModule with every `use ...;` import resolved
    and its constants/types/functions merged into `mod`'s namespace.

    `local::` imports are resolved against the directory of
    `mod.source_file`; if that is "<unknown>" or "<string>"
    (parsed from a string, not a file), local imports raise
    LoaderError -- callers wanting local imports must set the
    EMLModule.source_file before calling.

    Conflicts (an imported name collides with a local one, or two
    imports both define the same name) raise LoaderError.
    """
    if not mod.imports:
        return mod

    if loader is None:
        loader = ModuleLoader()

    # Compute the importing file's directory once so every
    # local::... lookup uses the same base.
    source_dir: Path | None = None
    src = mod.source_file
    if src and not src.startswith("<"):
        source_dir = Path(src).resolve().parent

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
        sub = loader.load(imp.joined, source_dir=source_dir)

        # Selective-import filter. When `imp.only` is set, only
        # names in that allowlist are merged. Names outside it are
        # NOT brought into the importing module's namespace; they
        # remain in the imported sub-module and the tree-shaker
        # later sees them as unreached.
        wanted = set(imp.only) if imp.only is not None else None

        # Validate the selective-import allowlist against what the
        # imported module actually exports -- a typo in the user's
        # `use ::{misspelled}` should surface as a clear error
        # rather than silently importing nothing.
        if wanted is not None:
            exported_names = (
                {c.name for c in sub.constants}
                | {t.name for t in sub.types}
                | {f.name for f in sub.functions}
            )
            unknown = sorted(wanted - exported_names)
            if unknown:
                raise LoaderError(
                    f"`use {imp.joined}::{{...}};` requested name(s) "
                    f"{unknown} not exported by {imp.joined!r} "
                    f"(available: {sorted(exported_names)[:20]})"
                )

        for c in sub.constants:
            if wanted is not None and c.name not in wanted:
                continue
            _check_clash(c.name, "constant", imp, provided_by,
                         local_names=const_names)
            out.constants.append(deepcopy(c))
            const_names.add(c.name)
            provided_by[c.name] = imp.joined

        for t in sub.types:
            if wanted is not None and t.name not in wanted:
                continue
            _check_clash(t.name, "type alias", imp, provided_by,
                         local_names=type_names)
            out.types.append(deepcopy(t))
            type_names.add(t.name)
            provided_by[t.name] = imp.joined

        for f in sub.functions:
            if wanted is not None and f.name not in wanted:
                continue
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
