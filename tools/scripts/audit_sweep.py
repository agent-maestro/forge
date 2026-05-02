"""Weekly Solidity audit-bundle sweep over industries/ kernels.

For each `.eml` under ``industries/`` that defines at least one
function, this script:

  1. Compiles `--target solidity --audit-bundle` into
     ``build/audit_sweep/<rel>_audit/``.
  2. Compares the new ``manifest.json`` against the prior baseline
     stored at ``industries/.audit_baselines/<rel>.manifest.json``.
  3. Updates the baseline file (or creates it on first run).
  4. Writes a Markdown report at
     ``build/audit_sweep_report.md`` listing kernels whose manifest
     hashes changed, kernels with new MISSING-proof gaps, and
     kernels that failed to compile.

Exit code:
  0 — sweep completed (with or without baseline diffs).
  1 — at least one kernel failed to compile.

Designed for the ``audit-sweep`` GitHub Action — the workflow opens
a PR carrying the updated baselines + the report whenever the diff
is non-empty.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable

from lang.parser import parse_file
from lang.profiler import Profiler

from software.backends.solidity_audit import write_audit_bundle
from software.backends.solidity_backend import SolidityBackend


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDUSTRIES = REPO_ROOT / "industries"
DEFAULT_BUILD = REPO_ROOT / "build" / "audit_sweep"
DEFAULT_BASELINES = DEFAULT_INDUSTRIES / ".audit_baselines"
DEFAULT_REPORT = REPO_ROOT / "build" / "audit_sweep_report.md"


# ── Discovery ───────────────────────────────────────────────────────


def _iter_kernels(root: Path) -> Iterable[Path]:
    """Yield every .eml under ``root`` whose contents declare at
    least one ``fn``. Skips empty stubs and the baseline cache dir."""
    for p in sorted(root.rglob("*.eml")):
        if ".audit_baselines" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        # Cheap pre-filter -- a real fn declaration starts with `fn `
        # or `pub fn ` after optional whitespace at the head of a line.
        # Cuts the parse cost for stub files (constants / imports only).
        if not any(
            line.lstrip().startswith(("fn ", "pub fn "))
            for line in text.splitlines()
        ):
            continue
        yield p


# ── Per-kernel sweep ────────────────────────────────────────────────


def _sweep_one(
    eml_path: Path, *, build_root: Path, machlib_root: Path | None,
) -> dict:
    """Compile one kernel; return a dict describing the outcome."""
    rel = eml_path.relative_to(REPO_ROOT)
    try:
        mod = parse_file(eml_path)
    except Exception as e:  # noqa: BLE001 -- surface every failure mode
        return {
            "kernel": str(rel).replace("\\", "/"),
            "status": "parse_error",
            "error": str(e),
        }
    if not mod.functions:
        return {
            "kernel": str(rel).replace("\\", "/"),
            "status": "no_functions",
        }
    Profiler().profile_module(mod)
    out_dir = build_root / rel.with_suffix("").as_posix()
    try:
        bundle = write_audit_bundle(
            mod,
            eml_source_path=eml_path,
            out_root=out_dir,
            backend=SolidityBackend(),
            machlib_root=machlib_root,
        )
    except Exception as e:  # noqa: BLE001 -- compile failure shouldn't crash the sweep
        return {
            "kernel": str(rel).replace("\\", "/"),
            "status": "compile_error",
            "error": str(e),
        }
    missing = [
        p.name for p in (bundle.root / "proofs").iterdir()
        if p.name.endswith(".MISSING.txt")
    ]
    return {
        "kernel": str(rel).replace("\\", "/"),
        "status": "ok",
        "manifest": bundle.manifest,
        "missing_proofs": sorted(missing),
        "bundle_dir": str(bundle.root),
    }


# ── Baseline diffing ────────────────────────────────────────────────


def _baseline_path(kernel_rel: str, baseline_root: Path) -> Path:
    """Map ``industries/foo/bar.eml`` → ``<baselines>/foo/bar.manifest.json``."""
    rel = Path(kernel_rel)
    rel = rel.relative_to("industries") if rel.parts and rel.parts[0] == "industries" else rel
    return (baseline_root / rel).with_suffix(".manifest.json")


def _diff_against_baseline(
    new_manifest: dict, baseline_path: Path,
) -> dict:
    """Return a structured per-artifact diff. Status values:
    ``new`` — no baseline existed; ``unchanged`` — manifests equal;
    ``changed`` — at least one artifact hash differs."""
    if not baseline_path.is_file():
        return {"status": "new", "changed_artifacts": []}
    try:
        prior = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "baseline_unreadable", "error": str(e)}
    prior_hashes = {
        a["path"]: a["sha256"] for a in prior.get("artifacts", [])
    }
    new_hashes = {
        a["path"]: a["sha256"] for a in new_manifest.get("artifacts", [])
    }
    changed: list[str] = []
    for path in sorted(set(prior_hashes) | set(new_hashes)):
        if prior_hashes.get(path) != new_hashes.get(path):
            changed.append(path)
    return {
        "status": "unchanged" if not changed else "changed",
        "changed_artifacts": changed,
    }


def _write_baseline(manifest: dict, baseline_path: Path) -> None:
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


# ── Report rendering ────────────────────────────────────────────────


def _render_report(results: list[dict]) -> str:
    swept = sum(1 for r in results if r["status"] == "ok")
    failed = [r for r in results if r["status"] == "compile_error"]
    parse_err = [r for r in results if r["status"] == "parse_error"]
    new_baselines = [
        r for r in results
        if r["status"] == "ok" and r["diff"]["status"] == "new"
    ]
    changed = [
        r for r in results
        if r["status"] == "ok" and r["diff"]["status"] == "changed"
    ]
    new_gaps = [
        r for r in results
        if r["status"] == "ok"
        and r["missing_proofs"]
        and r["diff"]["status"] in ("changed", "new")
    ]
    lines: list[str] = ["# Solidity audit-bundle sweep", ""]
    lines.append(f"- kernels swept: **{swept}**")
    lines.append(f"- new baselines: **{len(new_baselines)}**")
    lines.append(f"- baselines with hash drift: **{len(changed)}**")
    lines.append(f"- compile errors: **{len(failed)}**")
    lines.append(f"- parse errors: **{len(parse_err)}**")
    lines.append("")
    if changed:
        lines.append("## Changed manifests")
        for r in changed:
            lines.append(
                f"- `{r['kernel']}` — "
                + ", ".join(f"`{a}`" for a in r["diff"]["changed_artifacts"])
            )
        lines.append("")
    if new_gaps:
        lines.append("## New / outstanding MISSING proof stubs")
        for r in new_gaps:
            lines.append(
                f"- `{r['kernel']}` — " +
                ", ".join(f"`{p}`" for p in r["missing_proofs"])
            )
        lines.append("")
    if failed:
        lines.append("## Compile errors")
        for r in failed:
            lines.append(f"- `{r['kernel']}` — {r['error']}")
        lines.append("")
    if parse_err:
        lines.append("## Parse errors")
        for r in parse_err:
            lines.append(f"- `{r['kernel']}` — {r['error']}")
        lines.append("")
    if not (changed or new_gaps or failed or parse_err):
        lines.append("All kernels swept clean — no manifest drift, "
                     "no new proof gaps, no failures.")
    return "\n".join(lines) + "\n"


# ── Driver ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge-audit-sweep",
        description=__doc__.split("\n\n")[0],
    )
    parser.add_argument(
        "--industries", type=Path, default=DEFAULT_INDUSTRIES,
        help="Root containing kernels to sweep.",
    )
    parser.add_argument(
        "--build", type=Path, default=DEFAULT_BUILD,
        help="Where to write per-kernel audit bundles.",
    )
    parser.add_argument(
        "--baselines", type=Path, default=DEFAULT_BASELINES,
        help="Where to read/write per-kernel manifest baselines.",
    )
    parser.add_argument(
        "--report", type=Path, default=DEFAULT_REPORT,
        help="Where to write the Markdown report.",
    )
    parser.add_argument(
        "--machlib-root", type=Path, default=None,
        help="Optional MachLib Discovered/ root. Falls back to "
             "MACHLIB_ROOT env var, then to sibling-repo convention.",
    )
    parser.add_argument(
        "--no-update-baselines", action="store_true",
        help="Compute the diff but do not overwrite baselines. "
             "Useful for dry-run mode.",
    )
    args = parser.parse_args(argv)

    if args.build.exists():
        shutil.rmtree(args.build)
    args.build.mkdir(parents=True)

    results: list[dict] = []
    for eml in _iter_kernels(args.industries):
        outcome = _sweep_one(
            eml, build_root=args.build, machlib_root=args.machlib_root,
        )
        if outcome["status"] == "ok":
            baseline = _baseline_path(outcome["kernel"], args.baselines)
            outcome["diff"] = _diff_against_baseline(
                outcome["manifest"], baseline,
            )
            if not args.no_update_baselines:
                _write_baseline(outcome["manifest"], baseline)
        results.append(outcome)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(_render_report(results), encoding="utf-8")
    print(f"wrote {args.report}", file=sys.stderr)

    n_failed = sum(
        1 for r in results
        if r["status"] in ("compile_error", "parse_error")
    )
    return 1 if n_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
