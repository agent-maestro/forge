"""Module loader for `use` declarations.

Resolves `use <root>::<name>(...);` paths to `.eml` source files
on disk, parses them once, and caches the results so a function
imported by ten different modules is parsed only once per
process.

Search-path table:

  stdlib    -> lang/spec/stdlib/<name>.eml

(More roots will land as the import system grows -- e.g.
`local::X` for sibling files relative to the importing file.)

Cycles are detected by tracking the in-progress load set; when a
module already on that set is requested again, ImportError is
raised with the cycle path.
"""

from lang.loader.resolver import (
    LoaderError,
    ModuleLoader,
    resolve_imports,
)

__all__ = ["LoaderError", "ModuleLoader", "resolve_imports"]
