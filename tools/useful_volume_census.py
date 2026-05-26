#!/usr/bin/env python
"""Estimate useful-volume collapse in sampled EML tree space.

This census is a deterministic research harness. It samples a tree-depth and
dimension grid, classifies simulated boundary events, and estimates how much of
the sampled volume remains finite, non-saturated, and rescue-normal.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from tools.boundary_optimizer_benchmark import (
    BoundaryEventClass,
    classify_boundary_event,
    is_rescue_normal_event,
)


SCHEMA_VERSION = "forge.optimizer.useful_volume_census.v1"


@dataclass(frozen=True)
class CensusConfig:
    depths: list[int]
    dimensions: list[int]
    sample_count: int
    seed: int


def classify_sample(dimension: int, depth: int, rng: random.Random) -> dict:
    coords = [rng.random() * 2 - 1 for _ in range(dimension)]
    max_abs = max(abs(coord) for coord in coords)
    normalized_radius = math.sqrt(sum(coord * coord for coord in coords) / dimension)
    effective_boundary_threshold = max(0.7, 0.92 - depth * 0.018)
    boundary_hit = max_abs >= effective_boundary_threshold
    center_hit = normalized_radius <= 0.33
    pressure = max_abs * math.log2(dimension + depth + 1) + depth / 7
    raw_would_fail = pressure > 4.2 or rng.random() < min(0.45, dimension * depth / 2600)
    saturation_event = max_abs > 0.965 or pressure > 6.2
    domain_failure = raw_would_fail
    event_class = classify_boundary_event(
        mode="raw",
        boundary_hit=boundary_hit,
        center_hit=center_hit,
        domain_failure=domain_failure,
        saturation_event=saturation_event,
        raw_would_fail=raw_would_fail,
        pressure=pressure,
    )
    finite = not domain_failure
    useful = finite and not saturation_event and is_rescue_normal_event(event_class)
    return {
        "event_class": event_class,
        "finite": finite,
        "useful": useful,
        "saturated": saturation_event,
        "boundary_hit": boundary_hit,
        "center_hit": center_hit,
    }


def census_row(dimension: int, depth: int, sample_count: int, seed: int) -> dict:
    rng = random.Random(seed)
    samples = [classify_sample(dimension, depth, rng) for _ in range(sample_count)]
    useful_count = sum(1 for sample in samples if sample["useful"])
    finite_count = sum(1 for sample in samples if sample["finite"])
    saturated_count = sum(1 for sample in samples if sample["saturated"])
    boundary_count = sum(1 for sample in samples if sample["boundary_hit"])
    center_count = sum(1 for sample in samples if sample["center_hit"])
    event_counts = {
        event_class: sum(1 for sample in samples if sample["event_class"] == event_class)
        for event_class in [
            "interior_sample",
            "corner_concentration",
            "domain_wall",
            "overflow_wall",
            "saturation_shelf",
            "phantom_attractor",
            "guard_rescue",
            "log_domain_rescue",
        ]
    }
    return {
        "dimension": dimension,
        "tree_depth": depth,
        "terminal_count": 2**depth,
        "effective_coordinate_count": dimension * 2**depth,
        "sample_count": sample_count,
        "seed": seed,
        "finite_count": finite_count,
        "useful_count": useful_count,
        "invalid_count": sample_count - finite_count,
        "saturated_count": saturated_count,
        "boundary_hit_count": boundary_count,
        "center_hit_count": center_count,
        "finite_ratio": round(finite_count / sample_count, 6),
        "useful_ratio": round(useful_count / sample_count, 6),
        "invalid_ratio": round((sample_count - finite_count) / sample_count, 6),
        "saturated_ratio": round(saturated_count / sample_count, 6),
        "boundary_ratio": round(boundary_count / sample_count, 6),
        "center_ratio": round(center_count / sample_count, 6),
        "event_counts": event_counts,
    }


def useful_volume_census(config: CensusConfig) -> dict:
    rows = [
        census_row(
            dimension=dimension,
            depth=depth,
            sample_count=config.sample_count,
            seed=config.seed + dimension * 409 + depth * 37,
        )
        for depth in config.depths
        for dimension in config.dimensions
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_count": config.sample_count,
        "seed": config.seed,
        "depths": config.depths,
        "dimensions": config.dimensions,
        "rows": rows,
        "boundaries": {
            "simulated": True,
            "hardware_observed": False,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depths", nargs="+", type=int, default=[2, 4, 6, 8, 10])
    parser.add_argument("--dimensions", nargs="+", type=int, default=[4, 8, 16, 32, 64])
    parser.add_argument("--sample-count", type=int, default=512)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/useful_volume_census_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/useful_volume_census_2026_05_26.md"))
    return parser.parse_args()


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Useful Volume Census",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Rows: `{len(packet['rows'])}`",
        "",
        "| depth | dimension | effective coordinates | useful ratio | finite ratio | boundary ratio | center ratio | invalid ratio | saturated ratio |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in packet["rows"]:
        lines.append(
            f"| {row['tree_depth']} | {row['dimension']} | {row['effective_coordinate_count']} | "
            f"{row['useful_ratio']:.6f} | {row['finite_ratio']:.6f} | {row['boundary_ratio']:.6f} | "
            f"{row['center_ratio']:.6f} | {row['invalid_ratio']:.6f} | {row['saturated_ratio']:.6f} |"
        )
    lines.extend(
        [
            "",
            "This census is simulated and analysis-only. It estimates how quickly the",
            "sampled finite/useful subset collapses as depth and dimension increase.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def validate_strict(packet: dict) -> None:
    if not packet["rows"]:
        raise SystemExit("no useful-volume census rows emitted")
    if packet["boundaries"]["hardware_observed"] is not False:
        raise SystemExit("hardware boundary must remain false")
    by_dimension: dict[int, list[dict]] = {}
    for row in packet["rows"]:
        by_dimension.setdefault(row["dimension"], []).append(row)
    for dimension, rows in by_dimension.items():
        ordered = sorted(rows, key=lambda row: row["tree_depth"])
        if ordered[-1]["useful_ratio"] > ordered[0]["useful_ratio"]:
            raise SystemExit(f"useful ratio increased from min to max depth at dimension {dimension}")
        if ordered[-1]["boundary_ratio"] < ordered[0]["boundary_ratio"]:
            raise SystemExit(f"boundary ratio decreased from min to max depth at dimension {dimension}")


def main() -> int:
    args = parse_args()
    packet = useful_volume_census(CensusConfig(args.depths, args.dimensions, args.sample_count, args.seed))
    write_outputs(packet, args.json, args.markdown)
    if args.strict:
        validate_strict(packet)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("USEFUL_VOLUME_CENSUS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
