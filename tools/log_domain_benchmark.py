#!/usr/bin/env python
"""Benchmark log-domain candidate detection over Forge examples/stdlib."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lang.optimizer.log_domain import LOG_DOMAIN_SCHEMA, apply_log_domain_optimizer_module
from lang.parser import parse_source
from lang.profiler import Profiler


DEFAULT_GLOBS = [
    "lang/spec/grammar/examples/*.eml",
    "lang/spec/stdlib/*.eml",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/log_domain_candidate_benchmark_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/log_domain_candidate_benchmark_2026_05_26.md"))
    return parser.parse_args()


def discover_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in DEFAULT_GLOBS:
        files.extend(root.glob(pattern))
    return sorted({path for path in files if path.is_file()})


def run(root: Path) -> dict:
    rows = []
    parse_failures = []
    profiler = Profiler()
    for path in discover_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            mod = parse_source(path.read_text(encoding="utf-8"), rel)
            profiler.profile_module(mod)
            _, packet = apply_log_domain_optimizer_module(mod)
        except Exception as exc:  # pragma: no cover - surfaced in strict mode
            parse_failures.append({"path": rel, "error": str(exc)})
            continue
        for fn in packet["functions"]:
            rows.append({"path": rel, **fn})

    reason_counts: dict[str, int] = {}
    for row in rows:
        if row["candidate"]:
            reason_counts[row["reason"]] = reason_counts.get(row["reason"], 0) + 1

    return {
        "schema_version": "forge.optimizer.log_domain_candidate_benchmark.v1",
        "source_trace_schema": LOG_DOMAIN_SCHEMA,
        "file_count": len(discover_files(root)),
        "function_count": len(rows),
        "candidate_count": sum(1 for row in rows if row["candidate"]),
        "reason_counts": reason_counts,
        "rows": rows,
        "parse_failures": parse_failures,
        "boundaries": {
            "analysis_only": True,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
        },
    }


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Log-Domain Candidate Benchmark",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Files: `{packet['file_count']}`",
        f"Functions: `{packet['function_count']}`",
        f"Candidates: `{packet['candidate_count']}`",
        "",
        "| path | function | candidate | reason | exp/log depth | transcendentals | drift |",
        "|---|---|---:|---|---:|---:|---|",
    ]
    for row in packet["rows"]:
        if not row["candidate"]:
            continue
        lines.append(
            f"| `{row['path']}` | `{row['function']}` | yes | {row['reason']} | "
            f"{row['max_exp_ln_depth']} | {row['transcendental_count']} | {row['drift_risk']} |"
        )
    if packet["parse_failures"]:
        lines.extend(["", "## Parse Failures", ""])
        for failure in packet["parse_failures"]:
            lines.append(f"- `{failure['path']}`: {failure['error']}")
    lines.extend([
        "",
        "This benchmark is analysis-only. It marks functions for log-domain search-coordinate",
        "consideration; it does not claim a semantic rewrite or optimizer release.",
        "",
    ])
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    packet = run(root)
    write_outputs(packet, args.json, args.markdown)
    if args.strict:
        if packet["function_count"] == 0:
            raise SystemExit("no functions analyzed")
        if packet["boundaries"]["semantic_rewrite_claim"]:
            raise SystemExit("semantic rewrite boundary must remain false")
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("LOG_DOMAIN_CANDIDATE_BENCHMARK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
