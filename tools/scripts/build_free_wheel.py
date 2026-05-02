"""Build the Free-tier `monogate-forge` PyPI wheel.

The Free wheel is the Open-Core public artifact: parser + profiler +
optimizer + Free-tier code generators + LSP server + license verifier.
Pro backend source is *physically excluded* (not just license-gated),
so installing from PyPI never gives a user the Pro source code.

  Free targets:  c, cpp, rust, python, go, java, kotlin, lean, matlab
  Pro targets:   solidity, llvm, wasm, autosar, aadl, ros2, ada,
                 coq, isabelle, verilog, systemverilog, vhdl, chisel
                 ↑ source for these is excluded from the Free wheel.

How it works
------------
1. Stage a copy of the repo into a clean temp tree.
2. Delete every Pro source file / directory from the staged copy.
3. Run ``python -m build --wheel`` inside the staged tree.
4. Copy the resulting wheel into ``dist/`` of the live repo and
   print its contents for human review.

Usage
-----
::

    python tools/scripts/build_free_wheel.py
    twine upload dist/monogate_forge-*.whl --username __token__
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = REPO_ROOT / "dist"


# Paths to physically remove from the staged copy. Anything not
# listed here ships in the Free wheel.
_PRO_FILES: tuple[str, ...] = (
    "software/backends/solidity_backend.py",
    "software/backends/solidity_gas.py",
    "software/backends/solidity_spec.py",
    "software/backends/solidity_audit.py",
    "software/backends/llvm_backend.py",
    "software/backends/wasm_backend.py",
    "software/backends/autosar_backend.py",
    "software/backends/aadl_backend.py",
    "software/backends/ros2_backend.py",
    "software/backends/ada_backend.py",
    # Internal repo tools that import Pro backends at module level —
    # not user-facing entry points, no value to a Free install.
    "tools/scripts/audit_sweep.py",
    "tools/scripts/build_free_wheel.py",
)
_PRO_DIRS: tuple[str, ...] = (
    "hardware",
    "software/verification/coq",
    "software/verification/isabelle",
)

# Top-level paths to skip entirely while staging — keeps build output
# small and avoids leaking unrelated state into the wheel build env.
_SKIP_TOP_LEVEL: frozenset[str] = frozenset({
    ".git", ".github", ".vscode",
    "build", "dist", "industries",
    "demo", "final_check",
    ".pytest_cache", ".ruff_cache", ".mypy_cache",
    "node_modules", "__pycache__",
})


# Per-package data files to keep so the loader resolves stdlib + grammar.
# Mirrors pyproject's [tool.setuptools.package-data].


def _stage_repo(target: Path) -> None:
    """Copy the repo into ``target`` minus skip-listed top-level dirs."""
    target.mkdir(parents=True, exist_ok=True)
    for entry in REPO_ROOT.iterdir():
        if entry.name in _SKIP_TOP_LEVEL:
            continue
        dest = target / entry.name
        if entry.is_dir():
            shutil.copytree(
                entry, dest,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".pytest_cache",
                ),
            )
        else:
            shutil.copy2(entry, dest)


def _strip_pro(staged: Path) -> list[str]:
    """Delete Pro source from the staged tree. Returns paths removed."""
    removed: list[str] = []
    for rel in _PRO_FILES:
        p = staged / rel
        if p.is_file():
            p.unlink()
            removed.append(rel)
    for rel in _PRO_DIRS:
        p = staged / rel
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(rel + "/")
    return removed


def _patch_pyproject(staged: Path) -> None:
    """Tighten the pyproject description so the PyPI page is accurate
    for the Free build (no hardware / no Pro backends)."""
    pyproject = staged / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    free_desc = (
        "Programming language and compiler for verified mathematical "
        "computation (Free tier: parser, optimizer, LSP, and the C, "
        "C++, Rust, Python, Go, Java, Kotlin, Lean, MATLAB targets)."
    )
    text = text.replace(
        'description = "Programming language and compiler for verified '
        'mathematical computation, targeting both software and hardware"',
        f'description = "{free_desc}"',
    )
    pyproject.write_text(text, encoding="utf-8")


def _run_build(staged: Path) -> Path:
    """Invoke ``python -m build --wheel`` in ``staged``. Returns the
    path to the produced .whl inside the staged tree's dist/."""
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "build"],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation"],
        cwd=staged, check=True,
    )
    wheels = sorted((staged / "dist").glob("*.whl"))
    if not wheels:
        raise RuntimeError("python -m build produced no wheel")
    return wheels[-1]


def _audit_wheel(wheel_path: Path) -> tuple[list[str], list[str]]:
    """Open the wheel, return (every member, members that look like
    Pro leakage). The leakage check is paranoid — if it ever fires,
    something slipped past the staging step."""
    members: list[str] = []
    leaks: list[str] = []
    pro_keywords = (
        "solidity", "llvm_backend", "wasm_backend", "autosar",
        "aadl_backend", "ros2_backend", "ada_backend",
        "/coq/", "/isabelle/", "hardware/",
    )
    with zipfile.ZipFile(wheel_path) as zf:
        for name in zf.namelist():
            members.append(name)
            low = name.lower()
            if any(kw in low for kw in pro_keywords):
                leaks.append(name)
    return members, leaks


# ── Driver ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-free-wheel")
    parser.add_argument(
        "--keep-staging", action="store_true",
        help="Don't delete the staging tree after build (debug aid).",
    )
    args = parser.parse_args(argv)

    DIST_DIR.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="monogate-forge-free-"))
    try:
        print(f"staging into {staging}", file=sys.stderr)
        _stage_repo(staging)
        removed = _strip_pro(staging)
        print(
            f"removed {len(removed)} Pro path(s):",
            file=sys.stderr,
        )
        for r in removed:
            print(f"  - {r}", file=sys.stderr)
        _patch_pyproject(staging)
        wheel = _run_build(staging)
        # Move into the live repo's dist/ so twine can find it.
        out = DIST_DIR / wheel.name
        if out.exists():
            out.unlink()
        shutil.copy2(wheel, out)
        print(f"\nwrote {out}", file=sys.stderr)

        members, leaks = _audit_wheel(out)
        print(f"wheel contains {len(members)} files", file=sys.stderr)
        if leaks:
            print(
                f"\nERROR: Pro source leaked into the Free wheel "
                f"({len(leaks)} matches):",
                file=sys.stderr,
            )
            for ln in leaks:
                print(f"  - {ln}", file=sys.stderr)
            return 2
        print("Pro-leak audit: clean.", file=sys.stderr)
        return 0
    finally:
        if not args.keep_staging:
            shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
