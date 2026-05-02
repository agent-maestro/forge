"""EML-lang Language Server.

Capabilities provided in this version (v0.2):
- textDocument/didOpen, didChange, didClose
- textDocument/publishDiagnostics (lex / parse / type errors)
- textDocument/hover (chain order + cost class for fn names)
- textDocument/completion (builtins, stdlib symbols, in-scope decls)
- textDocument/definition (jump from a name to its declaration)
- textDocument/documentSymbol (outline view: fns, consts, types)

Planned for later:
- textDocument/formatting (delegate to `eml-compile --fmt`)
- workspace-aware cross-file goto-def / find-references

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


LSP_NAME = "eml-lsp"
LSP_VERSION = "0.2.0"

# Builtin math functions surfaced as completion items. Sourced from
# the parser's BUILTIN_TO_KIND dispatch table so the LSP and the
# compiler can never disagree about what's built in.
BUILTIN_NAMES: tuple[str, ...] = tuple(sorted(BUILTIN_TO_KIND.keys()))

# Stdlib symbol cache: { "math": ["sigmoid", "lerp", ...], ... }
# Populated lazily from the bundled .eml files at first completion.
_STDLIB_CACHE: dict[str, list[tuple[str, str]]] = {}  # name → kind ("fn"/"const")

server = LanguageServer(LSP_NAME, LSP_VERSION)


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

@server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def _did_open(params: lsp.DidOpenTextDocumentParams) -> None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    _publish_diagnostics(doc.uri, doc.source)


@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
def _did_change(params: lsp.DidChangeTextDocumentParams) -> None:
    doc = server.workspace.get_text_document(params.text_document.uri)
    _publish_diagnostics(doc.uri, doc.source)


@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
def _did_close(params: lsp.DidCloseTextDocumentParams) -> None:
    server.publish_diagnostics(params.text_document.uri, [])


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
    target = _find_decl(mod, word)
    if not target:
        return None
    line, col, length = target
    return lsp.Location(
        uri=doc.uri,
        range=lsp.Range(
            start=lsp.Position(line=max(0, line - 1), character=max(0, col - 1)),
            end=lsp.Position(line=max(0, line - 1), character=max(0, col - 1) + length),
        ),
    )


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
