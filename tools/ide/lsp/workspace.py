"""Workspace symbol index for cross-file goto-definition,
references, and rename.

Indexes:
- The bundled stdlib (math, ml, signal, linalg, control,
  constants) at server startup.
- User .eml files under each workspace folder, crawled on
  initialize and refreshed when files are saved.

Lookup model:
- An EMLImport `use stdlib::math::{lerp};` registers `lerp` as
  imported from the (`stdlib`, `math`) module.
- A goto-def request on a name first checks local decls, then
  walks the open document's imports to find a matching cross-
  module symbol, and returns its `(file, line, col)`.
- documentLink walks the open document's imports and emits one
  link per `use stdlib::*` clause pointing at the resolved .eml.
- find-references walks every indexed module's AST collecting
  VAR + CALL nodes that match the name. Builtin function names
  (exp/ln/sin/...) are excluded -- they are language constructs,
  not symbols.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from lang.parser.ast_nodes import (
    ASTNode, BUILTIN_NAMES, EMLImport, EMLModule, NodeKind,
)
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

    def index_workspace_folder(self, folder: Path) -> int:
        """Crawl ``folder`` for .eml files and index each one
        under ``("local", module_name)``. Returns the file count.
        Skips files under stdlib/ to avoid double-indexing."""
        if not folder.is_dir():
            return 0
        count = 0
        for eml in folder.rglob("*.eml"):
            # Skip files that are part of an in-tree forge clone's
            # bundled stdlib; we already indexed those.
            if "spec" in eml.parts and "stdlib" in eml.parts:
                continue
            module_name = self._read_module_name(eml) or eml.stem
            self._index_file(("local", module_name), eml)
            count += 1
        return count

    def refresh_file(self, file_path: str) -> None:
        """Re-parse a single file and update its index entry.
        Called from textDocument/didSave + didOpen."""
        eml = Path(file_path)
        if not eml.is_file():
            return
        # Find which path key this file is registered under, or
        # derive a new one if it's brand new.
        for key, mod in list(self._modules.items()):
            if Path(mod.file_path) == eml:
                self._index_file(key, eml)
                return
        module_name = self._read_module_name(eml) or eml.stem
        self._index_file(("local", module_name), eml)

    @staticmethod
    def _read_module_name(eml: Path) -> str | None:
        """Cheap module-name lookup: scan the first ~4 KB for
        `module foo;` so we don't pay the parse cost twice."""
        import re
        try:
            head = eml.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            return None
        m = re.search(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_]*)\s*;",
                      head, re.MULTILINE)
        return m.group(1) if m else None

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

    def all_indexed_files(self) -> list[str]:
        """Every indexed file path. Used by find-references to
        scan beyond the open document."""
        return [m.file_path for m in self._modules.values()]


# ─── reference + rename helpers ────────────────────────────────────

@dataclass(frozen=True)
class RefHit:
    """One occurrence of a name in a file's AST."""
    file_path: str
    line: int
    col: int
    length: int


def collect_refs_in_module(
    mod: EMLModule, name: str, file_path: str,
) -> list[RefHit]:
    """Walk every fn body in ``mod`` collecting VAR + CALL nodes
    whose value matches ``name``. Also yields the position of any
    matching top-level decl (so callers can include the decl in
    the reference set when LSP `includeDeclaration=True`)."""
    hits: list[RefHit] = []

    def add(line: int, col: int) -> None:
        hits.append(RefHit(file_path=file_path, line=line, col=col,
                           length=len(name)))

    # Top-level decl positions
    for fn in mod.functions:
        if fn.name == name:
            add(fn.line, fn.col)
    for c in mod.constants:
        if c.name == name:
            add(c.line, c.col)
    for t in mod.types:
        if t.name == name:
            add(t.line, t.col)

    # Body usages
    for fn in mod.functions:
        if fn.body is not None:
            _walk_node(fn.body, name, add)
    return hits


def _walk_node(node: ASTNode, name: str, add) -> None:
    """Recursive AST walk emitting matches. Inlined hot path so
    the LSP doesn't pay a generator's overhead per node."""
    if (node.kind in (NodeKind.VAR, NodeKind.CALL)
            and node.value == name):
        add(node.line, node.col)
    for child in node.children:
        _walk_node(child, name, add)


def is_renameable(name: str) -> bool:
    """Builtin transcendentals (exp, ln, sin, ...) and language
    keywords are not renameable -- they're language constructs.
    Checked by prepareRename so VS Code suppresses the input box
    instead of letting the user type a doomed rename."""
    if name in BUILTIN_NAMES:
        return False
    return True
