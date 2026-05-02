"""EML-lang Language Server.

Capabilities provided in this version (v0.4):
- textDocument/didOpen, didChange, didSave, didClose
- textDocument/publishDiagnostics (lex / parse / type errors)
- textDocument/hover (chain order + cost class for fn names,
  EML semantics + FPGA cost for builtin transcendentals)
- textDocument/completion (builtins, stdlib symbols, in-scope decls)
- textDocument/definition (jump from a name to its declaration --
  resolves cross-file via the workspace index for stdlib + local
  user .eml modules)
- textDocument/references (find all usages across the workspace)
- textDocument/prepareRename + textDocument/rename (workspace-wide
  rename via WorkspaceEdit)
- textDocument/documentSymbol (outline view: fns, consts, types)
- textDocument/documentLink (ctrl-click `use stdlib::*` clauses)

Workspace folders are indexed at initialize; saves refresh the
per-file index. Builtin transcendentals (exp, ln, ...) are NOT
renameable -- prepareRename returns null so VS Code suppresses
the input box.

Planned for later:
- textDocument/formatting (delegate to `eml-compile --fmt`)

Architectural notes:

The server runs the same parser/lexer/type-checker the CLI uses,
not a separate TypeScript reimplementation. This guarantees the
LSP and the CLI agree on errors. The parse runs on every
didChange but is cheap (~2-10 ms for the typical .eml; the
profiler is not invoked).

`resolve=False` in parse_source(): the LSP doesn't follow
`use stdlib::*` because the resolver hits the filesystem and
introduces a dependency on cwd. A user editing a .eml file with
stdlib imports still gets per-file syntax + type checking;
cross-file diagnostics need the project-aware build.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from lang.parser.ast_nodes import (
    BUILTIN_TO_KIND, EMLConstant, EMLFunction, EMLModule, EMLTypeAlias,
)
from lang.parser.lexer import KEYWORDS, LexError
from lang.parser.parser import ParseError, parse_source
from lang.parser.type_checker import type_check_program
from tools.ide.lsp.workspace import (
    RefHit, WorkspaceIndex, collect_refs_in_module, is_renameable,
)


LSP_NAME = "eml-lsp"
LSP_VERSION = "0.4.0"

# Builtin math functions surfaced as completion items. Sourced from
# the parser's BUILTIN_TO_KIND dispatch table so the LSP and the
# compiler can never disagree about what's built in.
BUILTIN_NAMES: tuple[str, ...] = tuple(sorted(BUILTIN_TO_KIND.keys()))


# Per-builtin metadata for hover. The chain_delta column is what
# the profiler adds to chain_order when this op appears in an
# expression. cycles is the FPGA latency from the default 32-bit
# allocator. Numbers come from the published Pfaffian-cost table
# in lang/spec/EML_LANG_DESIGN.md; the LSP reads them statically
# rather than calling the profiler so hovers stay sub-ms.
BUILTIN_DOCS: dict[str, dict[str, object]] = {
    "exp":   {"sig": "exp(x)",    "delta": 1, "cycles": 8,
              "kind": "exponential", "note": "EML-native"},
    "ln":    {"sig": "ln(x)",     "delta": 1, "cycles": 8,
              "kind": "exponential", "note": "EML-native; x > 0"},
    "sqrt":  {"sig": "sqrt(x)",   "delta": 0, "cycles": 5,
              "kind": "polynomial-ish", "note": "EML-native; x ≥ 0"},
    "pow":   {"sig": "pow(x, y)", "delta": 2, "cycles": 16,
              "kind": "exponential", "note": "x^y; lifts to chain≥2"},
    "abs":   {"sig": "abs(x)",    "delta": 0, "cycles": 1,
              "kind": "polynomial", "note": "EML-native; piecewise"},
    "clamp": {"sig": "clamp(x, lo, hi)", "delta": 0, "cycles": 2,
              "kind": "polynomial", "note": "EML-native"},
    "eml":   {"sig": "eml(x)",    "delta": 1, "cycles": 8,
              "kind": "exponential",
              "note": "the canonical EML operator (Patent #01)"},
    "sin":   {"sig": "sin(x)",    "delta": 2, "cycles": 12,
              "kind": "oscillatory", "note": "EML-native"},
    "cos":   {"sig": "cos(x)",    "delta": 2, "cycles": 12,
              "kind": "oscillatory", "note": "EML-native"},
    "tan":   {"sig": "tan(x)",    "delta": 2, "cycles": 14,
              "kind": "oscillatory", "note": "EML-native; sin/cos"},
    "asin":  {"sig": "asin(x)",   "delta": 2, "cycles": 16,
              "kind": "oscillatory", "note": "x ∈ [-1, 1]"},
    "acos":  {"sig": "acos(x)",   "delta": 2, "cycles": 16,
              "kind": "oscillatory", "note": "x ∈ [-1, 1]"},
    "atan":  {"sig": "atan(x)",   "delta": 2, "cycles": 14,
              "kind": "oscillatory", "note": "EML-native"},
    "sinh":  {"sig": "sinh(x)",   "delta": 1, "cycles": 10,
              "kind": "exponential", "note": "(exp(x)-exp(-x))/2"},
    "cosh":  {"sig": "cosh(x)",   "delta": 1, "cycles": 10,
              "kind": "exponential", "note": "(exp(x)+exp(-x))/2"},
    "tanh":  {"sig": "tanh(x)",   "delta": 1, "cycles": 12,
              "kind": "exponential", "note": "EML-native; bounded"},
}

# Stdlib symbol cache: { "math": ["sigmoid", "lerp", ...], ... }
# Populated lazily from the bundled .eml files at first completion.
_STDLIB_CACHE: dict[str, list[tuple[str, str]]] = {}  # name → kind ("fn"/"const")

server = LanguageServer(LSP_NAME, LSP_VERSION)

# Workspace symbol index. Built lazily at first use so server
# startup stays fast (~10ms). Indexes the bundled stdlib so
# cross-module goto-def resolves into math.eml / ml.eml / etc.
_WORKSPACE: WorkspaceIndex | None = None


def _workspace() -> WorkspaceIndex:
    global _WORKSPACE
    if _WORKSPACE is None:
        wi = WorkspaceIndex()
        wi.index_stdlib()
        _WORKSPACE = wi
    return _WORKSPACE


# ─── diagnostics ──────────────────────────────────────────────────

def _publish_diagnostics(uri: str, source: str) -> None:
    """Re-parse the document and publish lex / parse / type
    diagnostics. Called on every didOpen and didChange."""
    diagnostics: list[lsp.Diagnostic] = []

    # 1) Try to lex + parse. The first error stops the parse, so
    #    we only get one parse-stage diagnostic per pass.
    mod = None
    try:
        mod = parse_source(source, uri, resolve=False)
    except LexError as e:
        diagnostics.append(_diag_from_line_col(
            e.line, e.col, str(e), severity="error", code="LEX",
        ))
    except ParseError as e:
        line = getattr(e.token, "line", 1)
        col = getattr(e.token, "col", 1)
        # ParseError stringifies as "<file>:<line>:<col>: <msg>".
        # The LSP range already conveys position so strip everything
        # before the actual message to avoid duplication in the
        # editor hover.
        msg = str(e)
        marker = f":{line}:{col}: "
        if marker in msg:
            msg = msg.split(marker, 1)[1]
        diagnostics.append(_diag_from_line_col(
            line, col, msg, severity="error", code="PARSE",
        ))
    except Exception as e:  # pragma: no cover -- defensive
        diagnostics.append(_diag_from_line_col(
            1, 1, f"internal: {e!r}", severity="error", code="INTERNAL",
        ))

    # 2) If parse succeeded, run the chain-order type checker.
    if mod is not None:
        try:
            type_errors = type_check_program(mod.functions)
            for te in type_errors:
                diagnostics.append(_diag_from_line_col(
                    te.line, te.col,
                    f"{te.function_name}: {te.declared_op} {te.declared_value}"
                    f" violates inferred chain order {te.inferred_value}",
                    severity="error", code="CHAIN",
                ))
        except Exception as e:  # pragma: no cover
            diagnostics.append(_diag_from_line_col(
                1, 1, f"type checker: {e!r}",
                severity="warning", code="TYPECHECK",
            ))

    server.publish_diagnostics(uri, diagnostics)


def _diag_from_line_col(
    line: int, col: int, message: str,
    *, severity: str = "error", code: str = "EML",
) -> lsp.Diagnostic:
    """Build an LSP Diagnostic from a 1-indexed line/col pair.
    The LSP wire format is 0-indexed so we subtract one. We aim
    a 1-character marker by default; the editor will widen it
    visually as makes sense."""
    sev = {
        "error": lsp.DiagnosticSeverity.Error,
        "warning": lsp.DiagnosticSeverity.Warning,
        "info": lsp.DiagnosticSeverity.Information,
    }.get(severity, lsp.DiagnosticSeverity.Error)
    line0 = max(0, line - 1)
    col0 = max(0, col - 1)
    return lsp.Diagnostic(
        range=lsp.Range(
            start=lsp.Position(line=line0, character=col0),
            end=lsp.Position(line=line0, character=col0 + 1),
        ),
        message=message,
        severity=sev,
        code=code,
        source="eml-lsp",
    )


# ─── document lifecycle ───────────────────────────────────────────

@server.feature(lsp.INITIALIZED)
def _initialized(_params: lsp.InitializedParams) -> None:
    """Crawl every workspace folder for .eml files and add them
    to the symbol index. Called once after the LSP handshake."""
    wi = _workspace()
    folders = server.workspace.folders or {}
    total = 0
    for f in folders.values():
        try:
            folder_path = Path(_uri_to_path(f.uri))
            total += wi.index_workspace_folder(folder_path)
        except Exception:
            continue
    if total:
        # Stats line lands in the "EML Language Server" output
        # channel via the client's stderr handler.
        logging.warning("indexed %d workspace .eml files (%s)",
                        total, wi.stats())


@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def _did_open(params: lsp.DidOpenTextDocumentParams) -> None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    _workspace().refresh_file(_uri_to_path(doc.uri))
    _publish_diagnostics(doc.uri, doc.source)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def _did_change(params: lsp.DidChangeTextDocumentParams) -> None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    _publish_diagnostics(doc.uri, doc.source)


@server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def _did_save(params: lsp.DidSaveTextDocumentParams) -> None:
    """Refresh the symbol index when a file is saved -- so
    cross-file goto-def + references see the latest decls."""
    _workspace().refresh_file(_uri_to_path(params.text_document.uri))


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def _did_close(params: lsp.DidCloseTextDocumentParams) -> None:
    server.publish_diagnostics(params.text_document.uri, [])


def _uri_to_path(uri: str) -> str:
    """Strip the file:// prefix -- pygls's wide range of clients
    (VS Code on Windows, vim plugins on POSIX) all send file://
    URIs that need decoding before pathlib can use them."""
    from urllib.parse import unquote, urlparse
    p = urlparse(uri)
    if p.scheme != "file":
        return uri
    path = unquote(p.path)
    # On Windows file:///C:/foo → /C:/foo; strip the leading /
    if path.startswith("/") and len(path) >= 3 and path[2] == ":":
        path = path[1:]
    return path


# ─── hover (chain order + cost class for fn names) ─────────────────

@server.feature(
    lsp.TEXT_DOCUMENT_HOVER,
    lsp.HoverOptions(),
)
def _hover(params: lsp.HoverParams) -> lsp.Hover | None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    word = _word_at(doc.source, params.position)
    if not word:
        return None

    # Builtins win first -- they're the most common hover target
    # and BUILTIN_DOCS is sub-ms even without a parse.
    if word in BUILTIN_DOCS:
        d = BUILTIN_DOCS[word]
        md = (
            f"**`{d['sig']}`** — *builtin transcendental*\n\n"
            f"- structural class: **{d['kind']}**\n"
            f"- chain-order delta: **+{d['delta']}**\n"
            f"- FPGA cost: ~{d['cycles']} cycles @ 32-bit\n"
            f"- {d['note']}"
        )
        return lsp.Hover(contents=lsp.MarkupContent(
            kind=lsp.MarkupKind.Markdown, value=md,
        ))

    try:
        mod = parse_source(doc.source, doc.uri, resolve=False)
    except Exception:
        return None

    # Match against function names first.
    for fn in mod.functions:
        if fn.name == word:
            prof = fn.profile or {}
            chain = prof.get("chain_order", "?")
            cost = prof.get("cost_class", "?")
            depth = prof.get("eml_depth", "?")
            drift = prof.get("fp16_drift_risk", "?")
            md = (
                f"**`{fn.name}`** -- chain order {chain}, cost class {cost}\n\n"
                f"- depth: {depth}\n"
                f"- fp16 drift risk: {drift}\n"
                f"- locally defined function in module `{mod.name}`"
            )
            return lsp.Hover(contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown, value=md,
            ))

    # Fall through to constants.
    for c in mod.constants:
        if c.name == word:
            md = (
                f"**`{c.name}`** -- module constant\n\n"
                f"- type: `{c.type_annot}`\n"
                f"- in module: `{mod.name}`"
            )
            return lsp.Hover(contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown, value=md,
            ))

    return None


# ─── completion (builtins + stdlib + in-scope decls) ───────────────

def _stdlib_symbols() -> dict[str, list[tuple[str, str]]]:
    """Return { module_name: [(symbol, kind), ...] } for every
    bundled stdlib .eml file. Cached after the first call.

    Loads via the same `lang.loader.resolver.DEFAULT_SEARCH_PATHS`
    the compiler uses, so the LSP sees exactly what `use stdlib::*;`
    will resolve to.
    """
    if _STDLIB_CACHE:
        return _STDLIB_CACHE
    try:
        from lang.loader.resolver import DEFAULT_SEARCH_PATHS
        stdlib_root: Path = DEFAULT_SEARCH_PATHS["stdlib"]
    except Exception:
        return _STDLIB_CACHE
    if not stdlib_root.is_dir():
        return _STDLIB_CACHE
    for eml in sorted(stdlib_root.glob("*.eml")):
        try:
            mod = parse_source(
                eml.read_text(encoding="utf-8"),
                str(eml), resolve=False,
            )
        except Exception:
            continue
        symbols: list[tuple[str, str]] = []
        for fn in mod.functions:
            symbols.append((fn.name, "fn"))
        for c in mod.constants:
            symbols.append((c.name, "const"))
        _STDLIB_CACHE[eml.stem] = symbols
    return _STDLIB_CACHE


def _completion_items_for(
    mod: EMLModule | None,
) -> list[lsp.CompletionItem]:
    """Build the full completion list. The client (VS Code) does
    its own fuzzy matching on the labels, so we don't filter
    server-side -- cheaper UX and better matching."""
    items: list[lsp.CompletionItem] = []
    seen: set[str] = set()

    def add(label: str, kind: lsp.CompletionItemKind, detail: str) -> None:
        if label in seen:
            return
        seen.add(label)
        items.append(lsp.CompletionItem(
            label=label, kind=kind, detail=detail,
        ))

    # 1) Builtins (exp, ln, sin, ...)
    for name in BUILTIN_NAMES:
        add(name, lsp.CompletionItemKind.Function, "builtin")

    # 2) Keywords (module, fn, where, requires, ...)
    for kw in sorted(KEYWORDS):
        add(kw, lsp.CompletionItemKind.Keyword, "keyword")

    # 3) Stdlib symbols. Show every bundled module's exports,
    #    surfaced as `module::symbol` so they're easy to spot.
    for stdmod, syms in _stdlib_symbols().items():
        for name, kind in syms:
            label = f"{stdmod}::{name}"
            ck = (lsp.CompletionItemKind.Function if kind == "fn"
                  else lsp.CompletionItemKind.Constant)
            add(label, ck, f"stdlib::{stdmod}")

    # 4) In-scope decls from the open document.
    if mod is not None:
        for fn in mod.functions:
            add(fn.name, lsp.CompletionItemKind.Function,
                f"fn in {mod.name}")
        for c in mod.constants:
            add(c.name, lsp.CompletionItemKind.Constant,
                f"const in {mod.name}")
        for t in mod.types:
            add(t.name, lsp.CompletionItemKind.TypeParameter,
                f"type in {mod.name}")

    return items


@server.feature(
    lsp.TEXT_DOCUMENT_COMPLETION,
    lsp.CompletionOptions(trigger_characters=[":"]),
)
def _completion(params: lsp.CompletionParams) -> lsp.CompletionList:
    doc = server.workspace.get_text_document(params.text_document.uri)
    try:
        mod = parse_source(doc.source, doc.uri, resolve=False)
    except Exception:
        mod = None
    items = _completion_items_for(mod)
    return lsp.CompletionList(is_incomplete=False, items=items)


# ─── goto-definition (within the open file) ───────────────────────

@server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
def _definition(params: lsp.DefinitionParams) -> lsp.Location | None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    word = _word_at(doc.source, params.position)
    if not word:
        return None
    try:
        mod = parse_source(doc.source, doc.uri, resolve=False)
    except Exception:
        return None

    # 1) Local decls first -- a fn / const / type defined in the
    #    open file shadows any imported symbol of the same name.
    target = _find_decl(mod, word)
    if target:
        line, col, length = target
        return _location_for(doc.uri, line, col, length)

    # 2) Cross-module: walk imports and look up via workspace index.
    sym = _workspace().lookup_via_imports(word, mod.imports)
    if sym:
        return _location_for(
            Path(sym.file_path).as_uri(),
            sym.line, sym.col, sym.name_length,
        )
    return None


def _location_for(
    uri: str, line: int, col: int, length: int,
) -> lsp.Location:
    line0 = max(0, line - 1)
    col0 = max(0, col - 1)
    return lsp.Location(
        uri=uri,
        range=lsp.Range(
            start=lsp.Position(line=line0, character=col0),
            end=lsp.Position(line=line0, character=col0 + length),
        ),
    )


# ─── references + rename (workspace-wide) ─────────────────────────

@server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
def _references(params: lsp.ReferenceParams) -> list[lsp.Location]:
    doc = server.workspace.get_text_document(params.text_document.uri)
    word = _word_at(doc.source, params.position)
    if not word:
        return []
    return _gather_references(doc.uri, doc.source, word)


def _gather_references(
    open_uri: str, open_source: str, word: str,
) -> list[lsp.Location]:
    """Walk the open document + every indexed module and collect
    every position the name appears as a VAR or CALL."""
    locs: list[lsp.Location] = []
    open_path = _uri_to_path(open_uri)

    # 1) Open document
    try:
        mod = parse_source(open_source, open_uri, resolve=False)
        for hit in collect_refs_in_module(mod, word, open_path):
            locs.append(_location_for(
                open_uri, hit.line, hit.col, hit.length,
            ))
    except Exception:
        pass

    # 2) Other indexed files. Skip the open file -- already counted.
    for path in _workspace().all_indexed_files():
        if Path(path).resolve() == Path(open_path).resolve():
            continue
        try:
            text = Path(path).read_text(encoding="utf-8")
            other_mod = parse_source(text, path, resolve=False)
        except Exception:
            continue
        uri = Path(path).as_uri()
        for hit in collect_refs_in_module(other_mod, word, path):
            locs.append(_location_for(
                uri, hit.line, hit.col, hit.length,
            ))
    return locs


@server.feature(lsp.TEXT_DOCUMENT_PREPARE_RENAME)
def _prepare_rename(
    params: lsp.PrepareRenameParams,
) -> lsp.Range | None:
    """Confirm the symbol at the cursor can be renamed.
    Returning None makes VS Code suppress the rename input box --
    used to block renames on builtins (exp/ln/sin/...) and
    keywords (which aren't even valid identifiers in this slot)."""
    doc = server.workspace.get_text_document(params.text_document.uri)
    word = _word_at(doc.source, params.position)
    if not word or not is_renameable(word):
        return None
    # Find the actual range of the word at the cursor so VS Code
    # can highlight what's being renamed.
    line_text = doc.source.splitlines()[params.position.line]
    start = params.position.character
    end = params.position.character
    word_chars = _WORD_CHARS
    while start > 0 and line_text[start - 1] in word_chars:
        start -= 1
    while end < len(line_text) and line_text[end] in word_chars:
        end += 1
    return lsp.Range(
        start=lsp.Position(line=params.position.line, character=start),
        end=lsp.Position(line=params.position.line, character=end),
    )


@server.feature(lsp.TEXT_DOCUMENT_RENAME)
def _rename(params: lsp.RenameParams) -> lsp.WorkspaceEdit | None:
    """Build a WorkspaceEdit replacing every occurrence of the
    symbol with the new name. Reuses _gather_references so the
    rename touches exactly the same positions goto-references
    surfaces -- no risk of editing a position the LSP wouldn't
    have shown the user."""
    doc = server.workspace.get_text_document(params.text_document.uri)
    word = _word_at(doc.source, params.position)
    if not word or not is_renameable(word):
        return None
    new_name = params.new_name
    if not new_name or not _is_valid_ident(new_name):
        return None

    locs = _gather_references(doc.uri, doc.source, word)
    if not locs:
        return None

    # Group edits by URI -- the LSP wire protocol expects
    # changes: { uri: [TextEdit, ...] }
    changes: dict[str, list[lsp.TextEdit]] = {}
    for loc in locs:
        edit = lsp.TextEdit(range=loc.range, new_text=new_name)
        changes.setdefault(loc.uri, []).append(edit)
    return lsp.WorkspaceEdit(changes=changes)


def _is_valid_ident(name: str) -> bool:
    """Identifier predicate: starts with [A-Za-z_], rest in
    _WORD_CHARS. Mirrors the lexer's IDENT regex."""
    if not name:
        return False
    if not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(c in _WORD_CHARS for c in name)


def _find_decl(
    mod: EMLModule, name: str,
) -> tuple[int, int, int] | None:
    """Return (line, col, name_length) of the declaration of ``name``
    in ``mod``, or None. Scans functions, constants, and types."""
    for fn in mod.functions:
        if fn.name == name:
            return (fn.line, fn.col, len(fn.name))
    for c in mod.constants:
        if c.name == name:
            return (c.line, c.col, len(c.name))
    for t in mod.types:
        if t.name == name:
            return (t.line, t.col, len(t.name))
    return None


# ─── document links (ctrl-click on `use stdlib::*` clauses) ───────

@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_LINK)
def _document_links(
    params: lsp.DocumentLinkParams,
) -> list[lsp.DocumentLink]:
    """Emit one DocumentLink per `use stdlib::*;` clause whose
    target module is in the workspace index. Ctrl-clicking the
    link opens the target .eml file."""
    doc = server.workspace.get_text_document(params.text_document.uri)
    try:
        mod = parse_source(doc.source, doc.uri, resolve=False)
    except Exception:
        return []
    out: list[lsp.DocumentLink] = []
    wi = _workspace()
    lines = doc.source.splitlines()
    for imp in mod.imports:
        target_file = wi.resolve_module_file(tuple(imp.path))
        if not target_file:
            continue
        if imp.line < 1 or imp.line > len(lines):
            continue
        line_text = lines[imp.line - 1]
        # Highlight the joined path (e.g. `stdlib::math`) inside
        # the `use ...` clause. Falls back to the whole line.
        joined = imp.joined
        col = line_text.find(joined)
        if col < 0:
            col = max(0, imp.col - 1)
            length = len(line_text) - col
        else:
            length = len(joined)
        out.append(lsp.DocumentLink(
            range=lsp.Range(
                start=lsp.Position(line=imp.line - 1, character=col),
                end=lsp.Position(line=imp.line - 1, character=col + length),
            ),
            target=Path(target_file).as_uri(),
            tooltip=f"open {Path(target_file).name}",
        ))
    return out


# ─── document symbols (outline view) ──────────────────────────────

@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def _document_symbol(
    params: lsp.DocumentSymbolParams,
) -> list[lsp.DocumentSymbol]:
    doc = server.workspace.get_text_document(params.text_document.uri)
    try:
        mod = parse_source(doc.source, doc.uri, resolve=False)
    except Exception:
        return []
    out: list[lsp.DocumentSymbol] = []
    for c in mod.constants:
        out.append(_decl_symbol(
            c.name, c.line, c.col,
            kind=lsp.SymbolKind.Constant,
            detail=c.type_name,
        ))
    for t in mod.types:
        out.append(_decl_symbol(
            t.name, t.line, t.col,
            kind=lsp.SymbolKind.TypeParameter,
            detail=t.base_type,
        ))
    for fn in mod.functions:
        params_str = ", ".join(f"{p.name}: {p.type_name}" for p in fn.params)
        ret = (
            ", ".join(fn.return_tuple_types) if fn.return_tuple_types
            else fn.return_type
        )
        out.append(_decl_symbol(
            fn.name, fn.line, fn.col,
            kind=lsp.SymbolKind.Function,
            detail=f"({params_str}) -> {ret}",
        ))
    return out


def _decl_symbol(
    name: str, line: int, col: int,
    *, kind: lsp.SymbolKind, detail: str,
) -> lsp.DocumentSymbol:
    line0 = max(0, line - 1)
    col0 = max(0, col - 1)
    rng = lsp.Range(
        start=lsp.Position(line=line0, character=col0),
        end=lsp.Position(line=line0, character=col0 + len(name)),
    )
    return lsp.DocumentSymbol(
        name=name, kind=kind, detail=detail,
        range=rng, selection_range=rng,
    )


_WORD_CHARS = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789_"
)


def _word_at(source: str, pos: lsp.Position) -> str | None:
    """Return the identifier-ish word at the cursor, or None."""
    lines = source.splitlines()
    if pos.line >= len(lines):
        return None
    line = lines[pos.line]
    if pos.character > len(line):
        return None
    start = pos.character
    while start > 0 and line[start - 1] in _WORD_CHARS:
        start -= 1
    end = pos.character
    while end < len(line) and line[end] in _WORD_CHARS:
        end += 1
    word = line[start:end]
    return word or None


# ─── entry point ──────────────────────────────────────────────────

def main() -> None:
    """CLI entry point: speak LSP over stdin/stdout."""
    logging.basicConfig(level=logging.WARNING)
    server.start_io()


if __name__ == "__main__":
    main()
