"""lang.lint -- v0.5 deprecation lint passes for EML-lang.

Public API
----------
    from lang.lint import lint_module, LintWarning

``LintWarning``
    Dataclass carrying ``message``, ``line``, ``col``, ``fn_name``, and
    ``transcendental_name`` for a single lint finding.

``lint_module(mod, lint_enabled=True) -> list[LintWarning]``
    Run all enabled lint passes on a parsed ``EMLModule``.  Returns an empty
    list when ``lint_enabled=False`` -- this is the default-OFF gate that
    the CLI enforces when ``--lint`` is absent.

This module is default-OFF at the CLI level (gated by ``--lint``).  The
``lint_module`` function itself is always-on when called; callers are
responsible for the ``lint_enabled`` gate.
"""

from __future__ import annotations

from lang.lint.transcendental import LintWarning, lint_transcendental_requires
from lang.parser.ast_nodes import EMLModule


def lint_module(
    mod: EMLModule,
    lint_enabled: bool = True,
) -> list[LintWarning]:
    """Run all lint passes on *mod* and return the collected warnings.

    Parameters
    ----------
    mod : EMLModule
        The parsed (and already unit-checked) module.
    lint_enabled : bool
        When ``False`` (the default at CLI level without ``--lint``), this
        function is a no-op and returns an empty list -- preserving
        byte-identical behaviour to pre-v0.5.  When ``True``, all lint
        passes run.

    Returns
    -------
    list[LintWarning]
        Warnings from all enabled lint passes, in source order.
    """
    if not lint_enabled:
        return []

    warnings: list[LintWarning] = []
    warnings.extend(lint_transcendental_requires(mod))
    return warnings


__all__ = [
    "LintWarning",
    "lint_module",
]
