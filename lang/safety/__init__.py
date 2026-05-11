"""Forge safety-check phase — runs after parse + profile, before
backend emission.

Provides the `check_module()` pipeline hook that runs the
SafetyBackend across an EML file and either ABORTS compilation
(on verified / static_analysis violations) or WARNS to stderr
(advisory / unsupported violations).

Wired in `tools/cli/main.py` between `profiler.profile_module()`
and the backend dispatch. See:
  monogate-research/roadmap/safety-verification-protocol.md
  monogate-engine/docs/forge-safety-backend-integration-status.md
"""
from .check import (
    SafetyError,
    SafetyCheckResult,
    check_module,
    check_source,
)

__all__ = [
    "SafetyError",
    "SafetyCheckResult",
    "check_module",
    "check_source",
]
