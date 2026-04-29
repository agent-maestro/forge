"""Cross-target equivalence harness orchestrator.

Public entry: `cross_target_check()`. Profiles + lambdifies the
function as the Python reference, then runs every requested
backend's compiled output on the same vectors and compares.

Skipping policy: a backend whose toolchain isn't available
(cargo / gcc / verilator missing) is reported with `available=False`
rather than failing the whole run -- callers can decide whether
to treat partial coverage as a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lang.parser.ast_nodes import EMLFunction, EMLModule
from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler
from tools.equivalence.python_runner import (
    PythonReferenceError,
    constants_from_module,
    run_python_reference,
)
from tools.equivalence.rust_runner import (
    RustRunner,
    RustRunnerError,
    cargo_available,
)
from tools.equivalence.c_runner import (
    CRunner,
    CRunnerError,
    gcc_available,
)


@dataclass(frozen=True)
class TargetResult:
    target: str
    available: bool
    outputs: tuple = field(default_factory=tuple)
    """Either tuple[float, ...] for single-output fns, or
    tuple[tuple[float, ...], ...] for tuple-output fns."""
    max_abs_err: float = 0.0
    max_rel_err: float = 0.0
    error: str = ""
    """Set when the backend ran but mis-matched, errored out, or
    couldn't be compared (e.g. tuple vs scalar shape mismatch)."""


@dataclass(frozen=True)
class EquivalenceReport:
    function_name: str
    n_vectors: int
    targets: dict[str, TargetResult]
    overall_match: bool
    """True iff every available target's max_abs_err <= tolerance.
    Unavailable targets are not penalized."""

    def render(self) -> str:
        lines = [
            f"Equivalence report for {self.function_name!r}"
            f" ({self.n_vectors} vectors):"
        ]
        for name, r in self.targets.items():
            if not r.available:
                lines.append(f"  {name:8s}: [skipped -- toolchain missing]")
                continue
            if r.error:
                lines.append(f"  {name:8s}: ERROR {r.error[:200]}")
                continue
            lines.append(
                f"  {name:8s}: max abs err {r.max_abs_err:.3g}, "
                f"max rel err {r.max_rel_err:.3g}"
            )
        lines.append(
            f"  overall:  {'MATCH' if self.overall_match else 'DIVERGED'}"
        )
        return "\n".join(lines)


def cross_target_check(
    eml_path: str | Path,
    function_name: str,
    vectors: list[tuple[float, ...]],
    *,
    tolerance: float = 1e-9,
    targets: tuple[str, ...] = ("python", "rust", "c"),
) -> EquivalenceReport:
    """Run `function_name` from the .eml at `eml_path` through every
    requested backend and report agreement with the Python reference."""
    mod = parse_file(str(eml_path))
    Profiler().profile_module(mod)
    fn = _find_function(mod, function_name)

    # Always compute the Python reference first. Pull module-level
    # const values into the bridge so they substitute into the
    # lambdified body (without this, vertical functions that
    # reference e.g. GRAVITY_GAIN would leak as free symbols).
    consts = constants_from_module(mod)
    try:
        ref_outputs = run_python_reference(fn, vectors, constants=consts)
    except PythonReferenceError as e:
        # No reference -> can't compare anything. Mark Python as
        # unavailable + return early.
        return EquivalenceReport(
            function_name=function_name,
            n_vectors=len(vectors),
            targets={
                "python": TargetResult(
                    target="python", available=False,
                    error=str(e),
                ),
            },
            overall_match=False,
        )

    results: dict[str, TargetResult] = {
        "python": TargetResult(
            target="python", available=True,
            outputs=tuple(ref_outputs),
            max_abs_err=0.0, max_rel_err=0.0,
        ),
    }

    if "rust" in targets:
        results["rust"] = _run_rust(mod, function_name, vectors, ref_outputs)
    if "c" in targets:
        results["c"] = _run_c(mod, function_name, vectors, ref_outputs)

    overall_match = all(
        (not r.available) or (r.error == "" and r.max_abs_err <= tolerance)
        for r in results.values()
    )
    return EquivalenceReport(
        function_name=function_name,
        n_vectors=len(vectors),
        targets=results,
        overall_match=overall_match,
    )


# ── Internal helpers ─────────────────────────────────────────


def _find_function(mod: EMLModule, name: str) -> EMLFunction:
    for fn in mod.functions:
        if fn.name == name:
            return fn
    raise KeyError(
        f"function {name!r} not found in module "
        f"{mod.name!r} (have: {[f.name for f in mod.functions]})"
    )


def _run_rust(
    mod: EMLModule, name: str,
    vectors: list[tuple[float, ...]],
    reference: list,
) -> TargetResult:
    if not cargo_available():
        return TargetResult(target="rust", available=False)
    try:
        with RustRunner(mod) as runner:
            outputs = runner.call(name, vectors)
    except RustRunnerError as e:
        return TargetResult(target="rust", available=True, error=str(e))
    return _compare_outputs("rust", outputs, reference)


def _run_c(
    mod: EMLModule, name: str,
    vectors: list[tuple[float, ...]],
    reference: list,
) -> TargetResult:
    if not gcc_available():
        return TargetResult(target="c", available=False)
    try:
        with CRunner(mod) as runner:
            outputs = runner.call(name, vectors)
    except CRunnerError as e:
        return TargetResult(target="c", available=True, error=str(e))
    return _compare_outputs("c", outputs, reference)


def _compare_outputs(
    target: str,
    outputs: list,
    reference: list,
) -> TargetResult:
    if len(outputs) != len(reference):
        return TargetResult(
            target=target, available=True,
            error=(f"output count mismatch: {len(outputs)} vs"
                   f" {len(reference)}"),
        )
    max_abs = 0.0
    max_rel = 0.0
    for got, ref in zip(outputs, reference):
        # Both either scalar or same-arity tuple.
        if isinstance(ref, tuple):
            if not isinstance(got, tuple) or len(got) != len(ref):
                return TargetResult(
                    target=target, available=True,
                    outputs=tuple(outputs),
                    error="tuple shape mismatch",
                )
            for g, r in zip(got, ref):
                err = abs(g - r)
                max_abs = max(max_abs, err)
                denom = max(abs(r), 1e-12)
                max_rel = max(max_rel, err / denom)
        else:
            err = abs(float(got) - float(ref))
            max_abs = max(max_abs, err)
            denom = max(abs(ref), 1e-12)
            max_rel = max(max_rel, err / denom)
    return TargetResult(
        target=target, available=True,
        outputs=tuple(outputs),
        max_abs_err=max_abs, max_rel_err=max_rel,
    )
