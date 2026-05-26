#!/usr/bin/env python
"""Generate Optimization Boundary Lab benchmark packets.

The packet mirrors the Monogate Electronics simulator contract while staying
Forge-side and reproducible. It is an experiment harness, not an optimizer
release claim or a hardware claim.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


BoundaryMode = Literal["raw", "guarded", "log-domain candidate"]
SCHEMA_VERSION = "forge.optimizer.boundary_run_benchmark.v1"
ELECTRONICS_PACKET_SCHEMA = "monogate-electronics.boundary-run.v0"


@dataclass(frozen=True)
class BoundaryRunConfig:
    dimension: int
    tree_depth: int
    sample_count: int
    mode: BoundaryMode
    seed: int


def run_boundary_experiment(config: BoundaryRunConfig) -> dict:
    rng = random.Random(config.seed)
    frames: list[dict] = []
    for sample_index in range(config.sample_count):
        coords = [rng.random() * 2 - 1 for _ in range(config.dimension)]
        max_abs = max(abs(coord) for coord in coords)
        normalized_radius = math.sqrt(sum(coord * coord for coord in coords) / config.dimension)
        boundary_hit = max_abs >= 0.88
        center_hit = normalized_radius <= 0.33
        pressure = max_abs * math.log2(config.dimension + config.tree_depth)
        domain_draw = rng.random()

        if config.mode == "raw":
            domain_failure = pressure > 4.15 or domain_draw < config.dimension / 520
            saturation_event = max_abs > 0.96
        elif config.mode == "guarded":
            domain_failure = pressure > 5.8 and domain_draw < 0.08
            saturation_event = max_abs > 0.97
        else:
            domain_failure = False
            saturation_event = max_abs > 0.992

        frames.append(
            {
                "sample_index": sample_index,
                "max_abs_coordinate": round(max_abs, 4),
                "boundary_hit": boundary_hit,
                "center_hit": center_hit,
                "domain_failure": domain_failure,
                "saturation_event": saturation_event,
                "finite_survived": not domain_failure,
            }
        )

    center_hits = sum(1 for frame in frames if frame["center_hit"])
    boundary_hits = sum(1 for frame in frames if frame["boundary_hit"])
    domain_failures = sum(1 for frame in frames if frame["domain_failure"])
    saturation_events = sum(1 for frame in frames if frame["saturation_event"])

    return {
        "schema_version": ELECTRONICS_PACKET_SCHEMA,
        "course": "006-ee-math-kernels",
        "module": "optimization-boundary",
        "simulated": True,
        "hardware_observed": False,
        "dimension": config.dimension,
        "tree_depth": config.tree_depth,
        "sample_count": config.sample_count,
        "mode": config.mode,
        "seed": config.seed,
        "center_hits": center_hits,
        "boundary_hits": boundary_hits,
        "domain_failures": domain_failures,
        "saturation_events": saturation_events,
        "finite_survival_rate": round((config.sample_count - domain_failures) / config.sample_count, 4),
        "trace_preview": frames[:12],
        "boundary_flags": {
            "live_serial_capture_performed": False,
            "hardware_action_performed": False,
            "esp32_flash_performed": False,
            "fpga_programming_performed": False,
        },
    }


def benchmark(dimensions: list[int], modes: list[BoundaryMode], sample_count: int, tree_depth: int, seed: int) -> dict:
    runs = [
        run_boundary_experiment(
            BoundaryRunConfig(
                dimension=dimension,
                tree_depth=tree_depth,
                sample_count=sample_count,
                mode=mode,
                seed=seed + dimension * 17 + mode_index,
            )
        )
        for dimension in dimensions
        for mode_index, mode in enumerate(modes)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "electronics_packet_schema": ELECTRONICS_PACKET_SCHEMA,
        "run_count": len(runs),
        "dimensions": dimensions,
        "modes": modes,
        "sample_count": sample_count,
        "tree_depth": tree_depth,
        "seed": seed,
        "runs": runs,
        "boundaries": {
            "simulated": True,
            "hardware_observed": False,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dimensions", nargs="+", type=int, default=[2, 4, 8, 16, 32, 64])
    parser.add_argument("--sample-count", type=int, default=256)
    parser.add_argument("--tree-depth", type=int, default=8)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/boundary_optimizer_benchmark_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/boundary_optimizer_benchmark_2026_05_26.md"))
    return parser.parse_args()


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Boundary Optimizer Benchmark",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Electronics packet schema: `{packet['electronics_packet_schema']}`",
        f"Runs: `{packet['run_count']}`",
        "",
        "| dimension | mode | boundary hits | center hits | domain failures | saturation events | finite survival |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for run in packet["runs"]:
        lines.append(
            f"| {run['dimension']} | {run['mode']} | {run['boundary_hits']} | "
            f"{run['center_hits']} | {run['domain_failures']} | {run['saturation_events']} | "
            f"{run['finite_survival_rate']:.4f} |"
        )
    lines.extend(
        [
            "",
            "This benchmark is simulated and analysis-only. It backs the Course 006",
            "Optimization Boundary Lab contract; it does not claim a semantic rewrite,",
            "optimizer release, serial capture, or hardware observation.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    modes: list[BoundaryMode] = ["raw", "guarded", "log-domain candidate"]
    packet = benchmark(args.dimensions, modes, args.sample_count, args.tree_depth, args.seed)
    write_outputs(packet, args.json, args.markdown)
    if args.strict:
        if packet["run_count"] == 0:
            raise SystemExit("no benchmark runs emitted")
        for run in packet["runs"]:
            if run["hardware_observed"] is not False:
                raise SystemExit("hardware boundary must remain false")
        by_key = {(run["dimension"], run["mode"]): run for run in packet["runs"]}
        for dimension in args.dimensions:
            raw = by_key[(dimension, "raw")]
            log_domain = by_key[(dimension, "log-domain candidate")]
            if log_domain["finite_survival_rate"] < raw["finite_survival_rate"]:
                raise SystemExit(f"log-domain survival regressed at dimension {dimension}")
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("BOUNDARY_OPTIMIZER_BENCHMARK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
