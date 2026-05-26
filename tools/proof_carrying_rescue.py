#!/usr/bin/env python
"""Emit the first proof-carrying rescue trace packet.

The trace is intentionally narrow: a positive-domain function family is sampled
with raw optimizer coordinates and then with log-domain lifted coordinates. The
packet records the observed `domain_wall -> log_domain_rescue` path and the
MachLib obligation it should discharge next.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from lang.optimizer.log_domain import coordinate_plan_packet
from lang.parser import parse_source
from lang.profiler import Profiler
from tools.boundary_optimizer_benchmark import compose_transition, is_rescue_transition


SCHEMA_VERSION = "forge.optimizer.proof_carrying_rescue.v1"


@dataclass(frozen=True)
class RescueConfig:
    family: str
    params: list[float]
    clamp: float
    source_path: Path


def positive_log_energy(x: float) -> float:
    return math.log(x) + math.sqrt(x) + (1.0 / x)


def evaluate_positive_family(x: float) -> dict:
    if x <= 0:
        return {
            "finite": False,
            "domain_preserved": False,
            "value": None,
            "event_class": "domain_wall",
        }
    value = positive_log_energy(x)
    return {
        "finite": math.isfinite(value),
        "domain_preserved": True,
        "value": round(value, 8),
        "event_class": "interior_sample",
    }


def run_rescue_trace(config: RescueConfig) -> dict:
    source_path = Path(config.source_path)
    source = source_path.read_text(encoding="utf-8")
    module = parse_source(source, source_path.as_posix())
    Profiler().profile_module(module)
    function = next(fn for fn in module.functions if fn.name == config.family)
    coordinate_plan = coordinate_plan_packet(config.params, clamp=config.clamp)
    frames = []
    raw_survived = 0
    rescued_survived = 0

    for index, raw_coordinate in enumerate(config.params):
        raw_eval = evaluate_positive_family(raw_coordinate)
        lifted_coordinate = coordinate_plan["leaves"][index]
        lifted_eval = evaluate_positive_family(lifted_coordinate)
        if raw_eval["finite"]:
            raw_survived += 1
        if lifted_eval["finite"]:
            rescued_survived += 1
        from_event = raw_eval["event_class"]
        to_event = "log_domain_rescue" if lifted_eval["finite"] and not raw_eval["finite"] else lifted_eval["event_class"]
        transition = f"{from_event}->{to_event}"
        frames.append(
            {
                "sample_index": index,
                "raw_coordinate": raw_coordinate,
                "lifted_coordinate": round(lifted_coordinate, 8),
                "raw": raw_eval,
                "lifted": {
                    **lifted_eval,
                    "event_class": to_event,
                    "positive_coordinate": lifted_coordinate > 0,
                },
                "transition": transition,
                "rescue_transition": is_rescue_transition(transition),
            }
        )

    expected_transition = "domain_wall->log_domain_rescue"
    witness_frames = [frame for frame in frames if frame["transition"] == expected_transition]
    return {
        "schema_version": SCHEMA_VERSION,
        "function_family": config.family,
        "source_path": source_path.as_posix(),
        "eml_shape": "fn positive_log_energy(x: Real) -> Real requires (x > 0.0) { ln(x) + sqrt(x) + 1.0 / x }",
        "profile": function.profile or {},
        "rescue_operator": "log_domain_lift",
        "expected_transition": expected_transition,
        "composed_transition_demo": compose_transition(expected_transition, "log_domain_rescue->interior_sample"),
        "machlib_obligation": "PositiveCoordinateObligation",
        "intervention_obligation": "PositiveCoordinateInterventionObligation",
        "coordinate_plan": coordinate_plan,
        "sample_count": len(config.params),
        "raw_finite_count": raw_survived,
        "lifted_finite_count": rescued_survived,
        "survival_delta": rescued_survived - raw_survived,
        "rescued_event_count": len(witness_frames),
        "has_transition_witness": bool(witness_frames),
        "positive_coordinates_preserved": coordinate_plan["positive_domain_preserved"],
        "function_boundary_preserved": coordinate_plan["function_boundary_preserved"],
        "frames": frames,
        "boundaries": {
            "analysis_only": True,
            "simulated_trace": True,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
            "hardware_observed": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clamp", type=float, default=4.0)
    parser.add_argument("--params", nargs="+", type=float, default=[-2.0, -0.5, 0.0, 0.25, 1.25, 2.0])
    parser.add_argument("--source", type=Path, default=Path("examples/proof_carrying_rescue.eml"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/proof_carrying_rescue_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/proof_carrying_rescue_2026_05_26.md"))
    return parser.parse_args()


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# First Proof-Carrying Rescue",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Function family: `{packet['function_family']}`",
        f"Rescue operator: `{packet['rescue_operator']}`",
        f"Expected transition: `{packet['expected_transition']}`",
        f"MachLib obligation: `{packet['machlib_obligation']}`",
        "",
        "| sample | raw x | raw event | lifted x | lifted event | transition |",
        "|---:|---:|---|---:|---|---|",
    ]
    for frame in packet["frames"]:
        lines.append(
            f"| {frame['sample_index']} | {frame['raw_coordinate']} | {frame['raw']['event_class']} | "
            f"{frame['lifted_coordinate']:.8f} | {frame['lifted']['event_class']} | `{frame['transition']}` |"
        )
    lines.extend(
        [
            "",
            f"Raw finite count: `{packet['raw_finite_count']}`",
            f"Lifted finite count: `{packet['lifted_finite_count']}`",
            f"Rescued event count: `{packet['rescued_event_count']}`",
            "",
            "This packet is analysis-only. It demonstrates the evidence shape for a",
            "proof-carrying rescue; it does not claim a semantic rewrite, optimizer",
            "release, hardware observation, or completed formal proof.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def validate_strict(packet: dict) -> None:
    if not packet["has_transition_witness"]:
        raise SystemExit("expected domain_wall->log_domain_rescue witness was not emitted")
    if not packet["positive_coordinates_preserved"]:
        raise SystemExit("log-domain lift failed to preserve positive coordinates")
    if packet["lifted_finite_count"] < packet["raw_finite_count"]:
        raise SystemExit("lifted trace regressed finite survival")
    if packet["boundaries"]["semantic_rewrite_claim"] is not False:
        raise SystemExit("semantic rewrite boundary must remain false")
    if packet["boundaries"]["hardware_observed"] is not False:
        raise SystemExit("hardware boundary must remain false")


def main() -> int:
    args = parse_args()
    packet = run_rescue_trace(RescueConfig("positive_log_energy", args.params, args.clamp, args.source))
    write_outputs(packet, args.json, args.markdown)
    if args.strict:
        validate_strict(packet)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("PROOF_CARRYING_RESCUE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
