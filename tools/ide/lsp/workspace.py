"""Workspace symbol index for cross-file goto-definition.

The MVP indexes the bundled stdlib (math, ml, signal, linalg,
control, constants) by parsing each .eml at server startup.
Workspace folders containing user .eml files are added on
demand as the user opens them.

Lookup model:
- An EMLImport `use stdlib::math::{lerp};` registers the symbol
  `lerp` as imported from the (`stdlib`, `math`) module.
- A goto-def request on a name first checks local decls, then
  walks the open document's imports to find a matching cross-
  module symbol, and returns its `(file, line, col)`.
- documentLink walks the open document's imports and emits one
  link per `use stdlib::*` clause pointing at the resolved .eml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from lang.parser.ast_nodes import EMLImport, EMLModule
from lang.parser.parser import parse_source


@dataclass(frozen=True)
class SymbolLoc:
    """Where a symbol is declared. Line/col are 1-indexed."""
    file_path: str
    line: int
    col: int
    kind: str       # "fn" | "const" | "type"
    name_length: int


@dataclass
class ModuleIndex:
    """One indexed .eml module."""
    file_path: str
    module_name: str
    symbols: dict[str, SymbolLoc] = field(default_factory=dict)


class WorkspaceIndex:
    """Cross-module symbol index. Built once at server startup
    for the bundled stdlib, refreshed for user files on save."""

    def __init__(self) -> None:
        # Key is the dotted import path tuple (e.g. ("stdlib", "math"))
        # so lookups match the EMLImport.path representation directly.
        self._modules: dict[tuple[str, ...], ModuleIndex] = {}

    def index_stdlib(self) -> None:
        """Discover and index every bundled stdlib .eml. Called
        once at server startup. Idempotent."""
        try:
            from lang.loader.resolver import DEFAULT_SEARCH_PATHS
            stdlib_root: Path = DEFAULT_SEARCH_PATHS["stdlib"]
        except Exception:
            return
        if not stdlib_root.is_dir():
            return
        for eml in sorted(stdlib_root.glob("*.eml")):
            self._index_file(("stdlib", eml.stem), eml)

    def _index_file(self, path_key: tuple[str, ...], eml: Path) -> None:
        """Parse ``eml`` and record its top-level decls under
        ``path_key`` (e.g. ("stdlib", "math"))."""
        try:
            text = eml.read_text(encoding="utf-8")
            mod = parse_source(text, str(eml), resolve=False)
        except Exception:
            return
        idx = ModuleIndex(file_path=str(eml), module_name=mod.name or eml.stem)
        for fn in mod.functions:
            idx.symbols[fn.name] = SymbolLoc(
                file_path=str(eml), line=fn.line, col=fn.col,
                kind="fn", name_length=len(fn.name),
            )
        for c in mod.constants:
            idx.symbols[c.name] = SymbolLoc(
                file_path=str(eml), line=c.line, col=c.col,
                kind="const", name_length=len(c.name),
            )
        for t in mod.types:
            idx.symbols[t.name] = SymbolLoc(
                file_path=str(eml), line=t.line, col=t.col,
                kind="type", name_length=len(t.name),
            )
        self._modules[path_key] = idx

    def lookup_via_imports(
        self, name: str, imports: Iterable[EMLImport],
    ) -> SymbolLoc | None:
        """Resolve a name to its decl location by walking ``imports``.
        Returns None when no import resolves to a module that exports
        the name."""
        for imp in imports:
            key = tuple(imp.path)
            mod = self._modules.get(key)
            if mod is None:
                continue
            # Selective imports: respect `only` and `aliases` so that
            # `use stdlib::math::{lerp as interp};` makes `interp`
            # (not `lerp`) the visible name in the importing module.
            target_name = name
            if imp.aliases:
                # Reverse lookup: alias → original
                for orig, alias in imp.aliases.items():
                    if alias == name:
                        target_name = orig
                        break
            if imp.only is not None and target_name not in imp.only:
                continue
            sym = mod.symbols.get(target_name)
            if sym:
                return sym
        return None

    def resolve_module_file(self, path_key: tuple[str, ...]) -> str | None:
        """Return the .eml file path for an import path key, or None."""
        mod = self._modules.get(path_key)
        return mod.file_path if mod else None

    def stats(self) -> str:
        """Compact one-line summary -- handy in the LSP output channel."""
        n_mods = len(self._modules)
        n_syms = sum(len(m.symbols) for m in self._modules.values())
        return f"{n_mods} modules, {n_syms} symbols"
