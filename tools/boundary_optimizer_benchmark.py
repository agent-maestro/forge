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
BoundaryIntervention = Literal["log_domain_lift", "guard_clamp", "precision_escape", "saturation_deshelf"]
BoundaryEventClass = Literal[
    "interior_sample",
    "corner_concentration",
    "domain_wall",
    "overflow_wall",
    "saturation_shelf",
    "phantom_attractor",
    "guard_rescue",
    "log_domain_rescue",
]
SCHEMA_VERSION = "forge.optimizer.boundary_run_benchmark.v1"
INTERVENTION_SCHEMA_VERSION = "forge.optimizer.boundary_intervention_benchmark.v1"
ELECTRONICS_PACKET_SCHEMA = "monogate-electronics.boundary-run.v0"
EVENT_CLASSES: list[BoundaryEventClass] = [
    "interior_sample",
    "corner_concentration",
    "domain_wall",
    "overflow_wall",
    "saturation_shelf",
    "phantom_attractor",
    "guard_rescue",
    "log_domain_rescue",
]
RESCUE_OPERATORS: dict[BoundaryIntervention, dict[str, str]] = {
    "log_domain_lift": {
        "from_event": "domain_wall",
        "to_event": "log_domain_rescue",
        "target_mode": "log-domain candidate",
        "obligation": "positive_coordinate_preservation",
    },
    "guard_clamp": {
        "from_event": "overflow_wall",
        "to_event": "guard_rescue",
        "target_mode": "guarded",
        "obligation": "output_safety",
    },
    "precision_escape": {
        "from_event": "phantom_attractor",
        "to_event": "interior_sample",
        "target_mode": "log-domain candidate",
        "obligation": "precision_sensitivity",
    },
    "saturation_deshelf": {
        "from_event": "saturation_shelf",
        "to_event": "corner_concentration",
        "target_mode": "guarded",
        "obligation": "clamp_invariant",
    },
}
RESCUE_NORMAL_EVENTS: set[BoundaryEventClass] = {
    "interior_sample",
    "guard_rescue",
    "log_domain_rescue",
}
UNSAFE_BOUNDARY_EVENTS: set[BoundaryEventClass] = {
    "domain_wall",
    "overflow_wall",
    "saturation_shelf",
    "phantom_attractor",
}


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
        raw_would_fail = pressure > 4.15 or domain_draw < config.dimension / 520
        raw_would_saturate = max_abs > 0.96

        if config.mode == "raw":
            domain_failure = raw_would_fail
            saturation_event = raw_would_saturate
        elif config.mode == "guarded":
            domain_failure = pressure > 5.8 and domain_draw < 0.08
            saturation_event = max_abs > 0.97
        else:
            domain_failure = False
            saturation_event = max_abs > 0.992
        event_class = classify_boundary_event(
            mode=config.mode,
            boundary_hit=boundary_hit,
            center_hit=center_hit,
            domain_failure=domain_failure,
            saturation_event=saturation_event,
            raw_would_fail=raw_would_fail,
            pressure=pressure,
        )

        frames.append(
            {
                "sample_index": sample_index,
                "max_abs_coordinate": round(max_abs, 4),
                "pressure": round(pressure, 4),
                "boundary_hit": boundary_hit,
                "center_hit": center_hit,
                "domain_failure": domain_failure,
                "saturation_event": saturation_event,
                "finite_survived": not domain_failure,
                "event_class": event_class,
            }
        )

    center_hits = sum(1 for frame in frames if frame["center_hit"])
    boundary_hits = sum(1 for frame in frames if frame["boundary_hit"])
    domain_failures = sum(1 for frame in frames if frame["domain_failure"])
    saturation_events = sum(1 for frame in frames if frame["saturation_event"])
    event_counts = {
        event_class: sum(1 for frame in frames if frame["event_class"] == event_class)
        for event_class in EVENT_CLASSES
    }
    transition_counts = build_transition_counts(frames)

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
        "event_counts": event_counts,
        "transition_counts": transition_counts,
        "transition_entropy": round(transition_entropy(transition_counts), 4),
        "dominant_transition": dominant_transition(transition_counts),
        "trace_preview": frames[:12],
        "boundary_flags": {
            "live_serial_capture_performed": False,
            "hardware_action_performed": False,
            "esp32_flash_performed": False,
            "fpga_programming_performed": False,
        },
    }


def classify_boundary_event(
    *,
    mode: BoundaryMode,
    boundary_hit: bool,
    center_hit: bool,
    domain_failure: bool,
    saturation_event: bool,
    raw_would_fail: bool,
    pressure: float,
) -> BoundaryEventClass:
    if mode == "log-domain candidate" and raw_would_fail and not domain_failure:
        return "log_domain_rescue"
    if mode == "guarded" and raw_would_fail and not domain_failure:
        return "guard_rescue"
    if domain_failure and pressure > 4.15:
        return "overflow_wall"
    if domain_failure:
        return "domain_wall"
    if saturation_event:
        return "saturation_shelf"
    if center_hit and 3.05 <= pressure <= 3.3:
        return "phantom_attractor"
    if boundary_hit:
        return "corner_concentration"
    return "interior_sample"


def build_transition_counts(frames: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for previous, current in zip(frames, frames[1:]):
        transition = f"{previous['event_class']}->{current['event_class']}"
        counts[transition] = counts.get(transition, 0) + 1
    return dict(sorted(counts.items()))


def parse_transition(transition: str) -> tuple[BoundaryEventClass, BoundaryEventClass]:
    left, separator, right = transition.partition("->")
    if separator != "->":
        raise ValueError(f"invalid boundary transition: {transition}")
    if left not in EVENT_CLASSES or right not in EVENT_CLASSES:
        raise ValueError(f"unknown boundary event in transition: {transition}")
    return left, right  # type: ignore[return-value]


def compose_transition(left: str, right: str) -> str | None:
    """Compose `A->B` with `B->C` into `A->C` when the endpoint matches."""
    left_from, left_to = parse_transition(left)
    right_from, right_to = parse_transition(right)
    if left_to != right_from:
        return None
    return f"{left_from}->{right_to}"


def compose_transition_path(transitions: list[str]) -> str | None:
    if not transitions:
        return None
    composed = transitions[0]
    for transition in transitions[1:]:
        next_composed = compose_transition(composed, transition)
        if next_composed is None:
            return None
        composed = next_composed
    return composed


def is_rescue_normal_event(event_class: str) -> bool:
    if event_class not in EVENT_CLASSES:
        raise ValueError(f"unknown boundary event: {event_class}")
    return event_class in RESCUE_NORMAL_EVENTS


def is_rescue_transition(transition: str) -> bool:
    from_event, to_event = parse_transition(transition)
    return from_event in UNSAFE_BOUNDARY_EVENTS and to_event in RESCUE_NORMAL_EVENTS


def transition_entropy(transition_counts: dict[str, int]) -> float:
    total = sum(transition_counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in transition_counts.values():
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def dominant_transition(transition_counts: dict[str, int]) -> str | None:
    if not transition_counts:
        return None
    return max(transition_counts.items(), key=lambda item: item[1])[0]


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


def intervention_benchmark(dimensions: list[int], sample_count: int, tree_depth: int, seed: int) -> dict:
    pairs = []
    for dimension in dimensions:
        for index, intervention in enumerate(RESCUE_OPERATORS):
            pair_seed = seed + dimension * 101 + index
            pairs.append(run_intervention_pair(dimension, sample_count, tree_depth, pair_seed, intervention))
    return {
        "schema_version": INTERVENTION_SCHEMA_VERSION,
        "source_benchmark_schema": SCHEMA_VERSION,
        "electronics_packet_schema": ELECTRONICS_PACKET_SCHEMA,
        "pair_count": len(pairs),
        "dimensions": dimensions,
        "sample_count": sample_count,
        "tree_depth": tree_depth,
        "seed": seed,
        "rescue_operators": RESCUE_OPERATORS,
        "pairs": pairs,
        "boundaries": {
            "simulated": True,
            "hardware_observed": False,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
        },
    }


def run_intervention_pair(
    dimension: int,
    sample_count: int,
    tree_depth: int,
    seed: int,
    intervention: BoundaryIntervention,
) -> dict:
    operator = RESCUE_OPERATORS[intervention]
    target_mode = operator["target_mode"]
    raw = run_boundary_experiment(
        BoundaryRunConfig(
            dimension=dimension,
            tree_depth=tree_depth,
            sample_count=sample_count,
            mode="raw",
            seed=seed,
        )
    )
    intervened = run_boundary_experiment(
        BoundaryRunConfig(
            dimension=dimension,
            tree_depth=tree_depth,
            sample_count=sample_count,
            mode=target_mode,  # type: ignore[arg-type]
            seed=seed,
        )
    )
    from_event = operator["from_event"]
    to_event = operator["to_event"]
    raw_bad = raw["event_counts"].get(from_event, 0)
    intervened_bad = intervened["event_counts"].get(from_event, 0)
    rescued = intervened["event_counts"].get(to_event, 0)
    return {
        "intervention": intervention,
        "from_event": from_event,
        "to_event": to_event,
        "obligation": operator["obligation"],
        "dimension": dimension,
        "tree_depth": tree_depth,
        "sample_count": sample_count,
        "seed": seed,
        "raw": summarize_run(raw),
        "intervened": summarize_run(intervened),
        "bad_event_delta": raw_bad - intervened_bad,
        "rescued_event_count": rescued,
        "finite_survival_delta": round(intervened["finite_survival_rate"] - raw["finite_survival_rate"], 4),
        "transition_entropy_delta": round(intervened["transition_entropy"] - raw["transition_entropy"], 4),
        "expected_transition": f"{from_event}->{to_event}",
        "intervention_claim": "simulated_pairwise_benchmark",
    }


def summarize_run(run: dict) -> dict:
    return {
        "mode": run["mode"],
        "center_hits": run["center_hits"],
        "boundary_hits": run["boundary_hits"],
        "domain_failures": run["domain_failures"],
        "saturation_events": run["saturation_events"],
        "finite_survival_rate": run["finite_survival_rate"],
        "dominant_event": dominant_event(run["event_counts"]),
        "dominant_transition": run["dominant_transition"],
        "transition_entropy": run["transition_entropy"],
        "event_counts": run["event_counts"],
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
    parser.add_argument(
        "--intervention-json",
        type=Path,
        default=Path("reports/boundary_intervention_benchmark_2026_05_26.json"),
    )
    parser.add_argument(
        "--intervention-markdown",
        type=Path,
        default=Path("reports/boundary_intervention_benchmark_2026_05_26.md"),
    )
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
        "| dimension | mode | dominant event | dominant transition | entropy | boundary hits | center hits | domain failures | saturation events | finite survival |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for run in packet["runs"]:
        lines.append(
            f"| {run['dimension']} | {run['mode']} | {dominant_event(run['event_counts'])} | "
            f"{run['dominant_transition']} | {run['transition_entropy']:.4f} | {run['boundary_hits']} | "
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


def write_intervention_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Boundary Intervention Benchmark",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Pairs: `{packet['pair_count']}`",
        "",
        "| dimension | intervention | expected transition | obligation | raw survival | intervened survival | survival delta | bad-event delta | rescued count | entropy delta |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for pair in packet["pairs"]:
        lines.append(
            f"| {pair['dimension']} | {pair['intervention']} | `{pair['expected_transition']}` | "
            f"{pair['obligation']} | {pair['raw']['finite_survival_rate']:.4f} | "
            f"{pair['intervened']['finite_survival_rate']:.4f} | {pair['finite_survival_delta']:.4f} | "
            f"{pair['bad_event_delta']} | {pair['rescued_event_count']} | {pair['transition_entropy_delta']:.4f} |"
        )
    lines.extend(
        [
            "",
            "This benchmark is simulated and pairwise. It tests whether named rescue",
            "operators change boundary-event dynamics; it does not claim a semantic",
            "rewrite, optimizer release, serial capture, or hardware observation.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def dominant_event(event_counts: dict[str, int]) -> str:
    return max(event_counts.items(), key=lambda item: item[1])[0]


def main() -> int:
    args = parse_args()
    modes: list[BoundaryMode] = ["raw", "guarded", "log-domain candidate"]
    packet = benchmark(args.dimensions, modes, args.sample_count, args.tree_depth, args.seed)
    intervention_packet = intervention_benchmark(args.dimensions, args.sample_count, args.tree_depth, args.seed)
    write_outputs(packet, args.json, args.markdown)
    write_intervention_outputs(intervention_packet, args.intervention_json, args.intervention_markdown)
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
        if intervention_packet["pair_count"] == 0:
            raise SystemExit("no intervention pairs emitted")
        for pair in intervention_packet["pairs"]:
            if pair["finite_survival_delta"] < 0:
                raise SystemExit(f"intervention survival regressed: {pair['intervention']} d={pair['dimension']}")
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print(f"Wrote {args.intervention_json}")
    print(f"Wrote {args.intervention_markdown}")
    print("BOUNDARY_OPTIMIZER_BENCHMARK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
