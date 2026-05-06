"""Lean target runner for the equivalence harness.

Lean doesn't produce numeric outputs the way C / Rust do -- the
"output" of compiling Lean is *successful type-checking*, which
is itself the proof of the @verify clause. So the Lean target
in the equivalence harness reports availability + a `compile_ok`
flag rather than ULP-comparable numbers.

Two operating modes:

  - Structural mode (always available): emit the Lean source via
    LeanBackend and verify it contains the expected `theorem
    <name>` declaration, an `import MachLib.*` line, and at
    least one proof tactic invocation.

  - Full-build mode (when `lake` is on PATH AND a MachLib project
    is available): scaffold a tiny lake project, write the
    generated source into it, and run `lake build`. The result
    reports compile_ok=True iff the build succeeds.

The harness orchestrator never penalises a structural-only run
relative to a full-build run; users that want hard verification
should set up the lake environment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lang.parser.ast_nodes import EMLModule
from software.verification.lean.LeanBackend import LeanBackend


def lean_available() -> bool:
    """True iff `lean` (the type-checker) is on PATH."""
    return shutil.which("lean") is not None


def lake_available() -> bool:
    """True iff `lake` (the package manager) is on PATH AND
    a working MachLib project is available for it to build
    against. Today we just check the binary; pointing at a real
    project is a follow-on for when the harness gains a Lake
    config."""
    return shutil.which("lake") is not None


# Path to the in-repo MachLib foundations, if it exists.
_MACHLIB_DIR = (
    Path(__file__).resolve().parents[2]
    / "software" / "verification" / "lean"
)


@dataclass(frozen=True)
class LeanCheckResult:
    """Outcome of one Lean equivalence check."""
    function_name: str
    available: bool
    """False when there's no @verify(lean) block in the source."""
    structural_ok: bool = False
    """The emitted source has the expected shape (import,
    theorem decl, proof tactic)."""
    full_build_attempted: bool = False
    """True when lake was available and a build was launched."""
    full_build_ok: bool = False
    """True iff the lake build succeeded."""
    structural_findings: tuple[str, ...] = field(default_factory=tuple)
    """One line per structural check that failed (empty when all
    pass)."""
    error: str = ""


class LeanRunnerError(RuntimeError):
    pass


class LeanRunner:
    """Generate + verify Lean source for the @verify(lean) blocks
    of an EMLModule."""

    def __init__(
        self,
        module: EMLModule,
        *,
        timeout_s: float = 300.0,
        full_build: bool = True,
    ) -> None:
        self.module = module
        self.timeout_s = timeout_s
        self.full_build = full_build

    def check(self, function_name: str) -> LeanCheckResult:
        """Verify the Lean source emitted for `function_name`.

        Returns LeanCheckResult with `available=False` when the
        function has no @verify(lean) annotation."""
        fn = next(
            (f for f in self.module.functions if f.name == function_name),
            None,
        )
        if fn is None:
            return LeanCheckResult(
                function_name=function_name,
                available=False,
                error=f"function {function_name!r} not in module",
            )

        has_verify = any(
            a.kind == "verify"
            and (a.args.get(0) == "lean" or a.args.get("0") == "lean")
            for a in fn.annotations
        )
        if not has_verify:
            return LeanCheckResult(
                function_name=function_name,
                available=False,
                error="no @verify(lean) annotation",
            )

        try:
            # compile_module(mod) (not compile(fn)) so module-level
            # constants the function references (`dt`, `ATT_LIMIT`,
            # etc.) are emitted as `noncomputable def`s ahead of the
            # function.  Otherwise `lean` fails on unresolved names.
            src = LeanBackend().compile_module(self.module)
        except Exception as e:
            return LeanCheckResult(
                function_name=function_name,
                available=True,
                error=f"LeanBackend.compile raised: {e}",
            )

        if not src.strip():
            return LeanCheckResult(
                function_name=function_name,
                available=True,
                error="LeanBackend produced empty source",
            )

        # ── Structural checks ────────────────────────────
        findings = list(_structural_findings(src, fn))
        structural_ok = not findings

        result = LeanCheckResult(
            function_name=function_name,
            available=True,
            structural_ok=structural_ok,
            structural_findings=tuple(findings),
        )

        # ── Optional full lake build ─────────────────────
        if (
            self.full_build
            and lake_available()
            and structural_ok
        ):
            ok, err = self._try_lake_build(src)
            result = LeanCheckResult(
                function_name=function_name,
                available=True,
                structural_ok=structural_ok,
                structural_findings=tuple(findings),
                full_build_attempted=True,
                full_build_ok=ok,
                error=err,
            )

        return result

    def _try_lake_build(self, src: str) -> tuple[bool, str]:
        """Scaffold a lake project, write `src` into it, and run
        `lake build`. Returns (ok, error_message).

        Today's MVP just runs `lean --check` against a single
        file. Catches syntax errors and import resolution; doesn't
        fully verify theorems whose proofs are `sorry`. The
        harness's structural check covers the no-toolchain case;
        this is the toolchain-present upgrade."""
        if shutil.which("lean") is None:
            return False, "lean binary not found alongside lake"

        with tempfile.TemporaryDirectory(prefix="forge_lean_") as tmp:
            tmp_path = Path(tmp)
            lean_file = tmp_path / "Generated.lean"
            lean_file.write_text(src, encoding="utf-8")
            try:
                # `--no-deps` was rejected by Lean 4.14.0 (and current
                # leanprover binaries -- the flag never existed on the
                # `lean` CLI; it was a `lake` flag).  Drop it.
                #
                # Generated Lean files import MachLib, which lives in a
                # sibling repo.  Discover its built olean directory and
                # add it to LEAN_PATH so `lean` can resolve `import
                # MachLib`.  When MachLib hasn't been built locally
                # (`lake build` in machlib/foundations) the import will
                # fail and the test will surface that explicitly.
                env = os.environ.copy()
                machlib_lib = (
                    Path(__file__).resolve().parents[3]
                    / "machlib" / "foundations" / ".lake" / "build" / "lib"
                )
                if machlib_lib.exists():
                    existing = env.get("LEAN_PATH", "")
                    env["LEAN_PATH"] = (
                        f"{machlib_lib}:{existing}" if existing else str(machlib_lib)
                    )
                r = subprocess.run(
                    ["lean", str(lean_file)],
                    cwd=str(tmp_path),
                    env=env,
                    capture_output=True, text=True,
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired:
                return False, f"lean check timed out after {self.timeout_s}s"
            if r.returncode != 0:
                return False, f"lean check failed:\n{r.stderr[:600]}"
            return True, ""


# ── Structural analysis ──────────────────────────────────────


_THEOREM_RE = re.compile(r"theorem\s+(\w+)")
_IMPORT_RE = re.compile(r"^\s*import\s+MachLib")


def _structural_findings(src: str, fn) -> list[str]:
    """Return one finding per structural problem in `src`. Empty
    list means everything looks well-formed."""
    findings: list[str] = []

    # Must import a MachLib foundations module so `Real`, `exp`,
    # `log`, etc. resolve.
    if not any(_IMPORT_RE.match(line) for line in src.splitlines()):
        findings.append(
            "missing `import MachLib.EML` (or sibling) from header"
        )

    # Must declare a theorem with the expected name.
    expected_thm = None
    for ann in fn.annotations:
        if ann.kind == "verify":
            expected_thm = ann.args.get("theorem")
            if expected_thm is not None:
                break
    if expected_thm is None:
        findings.append(
            "verify annotation missing `theorem = \"...\"` argument"
        )
    else:
        thms = _THEOREM_RE.findall(src)
        if expected_thm not in thms:
            findings.append(
                f"expected theorem {expected_thm!r} not declared "
                f"(found {thms})"
            )

    # Must include at least one proof-tactic invocation.
    if ":= by" not in src and ":=\n  by" not in src:
        findings.append(
            "no proof-tactic body found (expected `:= by ...`)"
        )

    return findings
