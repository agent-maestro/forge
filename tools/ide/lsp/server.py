"""EML-lang Language Server -- LSP MVP.

Capabilities provided in this version:
- textDocument/didOpen, didChange, didClose
- textDocument/publishDiagnostics (lex / parse / type errors)
- textDocument/hover (chain order + cost class for fn names)

Not yet implemented (planned for v0.2):
- textDocument/definition (goto-def for fn / const / use)
- textDocument/completion (stdlib symbols, builtin names)
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
from typing import Any

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer

from lang.parser.lexer import LexError, tokenize
from lang.parser.parser import ParseError, parse_source
from lang.parser.type_checker import type_check_program


LSP_NAME = "eml-lsp"
LSP_VERSION = "0.1.0"

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
