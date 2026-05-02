"""EML-lang Language Server Protocol implementation.

Wraps the existing forge parser/lexer/type-checker and exposes
their errors as LSP diagnostics, hovers, and (planned) goto-def
+ completion. Speaks JSON-RPC over stdin/stdout per the LSP
spec. Built on pygls.
"""
