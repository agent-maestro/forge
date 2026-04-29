"""Canonical EML-lang formatter (eml-fmt).

Public entry: `format_source(text)` parses .eml source and re-emits
it in canonical form -- think `gofmt` for `.eml`. Idempotent:
`format_source(format_source(x)) == format_source(x)` is enforced
by the test suite.

The formatter operates on the parsed AST so it cannot preserve
non-semantic details (extra blank lines between statements, exact
whitespace inside expressions). What it preserves:

  - Original declaration order
  - Constant / type / function partitioning
  - Annotations + their argument order
  - where-clause order (chain_order, then domain, then precision)

What it canonicalises:

  - 4-space indentation
  - Single space around binary operators
  - Parenthesisation: minimal, parser-precedence-driven
  - Line endings: LF (the file is written with `\\n`)
  - Trailing newline at end-of-file
"""

from tools.fmt.formatter import format_source, format_file

__all__ = ["format_source", "format_file"]
