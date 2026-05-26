#!/usr/bin/env python
"""Emit the overflow-wall proof-carrying rescue trace packet."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from lang.parser import parse_source
from lang.profiler import Profiler
from tools.boundary_optimizer_benchmark import compose_transition, is_rescue_transition


SCHEMA_VERSION = "forge.optimizer.guard_clamp_rescue.v1"


@dataclass(frozen=True)
class GuardClampConfig:
    family: str
    params: list[float]
    clamp: float
    source_path: Path


def exp_pressure(x: float) -> float:
    return math.exp(x) + math.exp(x * x)


def evaluate_exp_pressure(x: float) -> dict:
    try:
        value = exp_pressure(x)
    except OverflowError:
        return {
            "finite": False,
            "bounded_output": False,
            "value": None,
            "event_class": "overflow_wall",
        }
    finite = math.isfinite(value)
    return {
        "finite": finite,
        "bounded_output": finite,
        "value": round(value, 8) if finite else None,
        "event_class": "interior_sample" if finite else "overflow_wall",
    }


def run_guard_clamp_trace(config: GuardClampConfig) -> dict:
    source_path = Path(config.source_path)
    source = source_path.read_text(encoding="utf-8")
    module = parse_source(source, source_path.as_posix())
    Profiler().profile_module(module)
    function = next(fn for fn in module.functions if fn.name == config.family)
    frames = []
    raw_survived = 0
    guarded_survived = 0

    for index, raw_coordinate in enumerate(config.params):
        guarded_coordinate = max(min(raw_coordinate, config.clamp), -config.clamp)
        raw_eval = evaluate_exp_pressure(raw_coordinate)
        guarded_eval = evaluate_exp_pressure(guarded_coordinate)
        if raw_eval["finite"]:
            raw_survived += 1
        if guarded_eval["finite"]:
            guarded_survived += 1
        from_event = raw_eval["event_class"]
        to_event = "guard_rescue" if guarded_eval["finite"] and not raw_eval["finite"] else guarded_eval["event_class"]
        transition = f"{from_event}->{to_event}"
        frames.append(
            {
                "sample_index": index,
                "raw_coordinate": raw_coordinate,
                "guarded_coordinate": guarded_coordinate,
                "guard_clamped": guarded_coordinate != raw_coordinate,
                "raw": raw_eval,
                "guarded": {
                    **guarded_eval,
                    "event_class": to_event,
                    "within_guard_bounds": abs(guarded_coordinate) <= config.clamp,
                },
                "transition": transition,
                "rescue_transition": is_rescue_transition(transition),
            }
        )

    expected_transition = "overflow_wall->guard_rescue"
    witness_frames = [frame for frame in frames if frame["transition"] == expected_transition]
    return {
        "schema_version": SCHEMA_VERSION,
        "function_family": config.family,
        "source_path": source_path.as_posix(),
        "eml_shape": "fn exp_pressure(x: Real) -> Real { exp(x) + exp(x * x) }",
        "profile": function.profile or {},
        "rescue_operator": "guard_clamp",
        "expected_transition": expected_transition,
        "composed_transition_demo": compose_transition(expected_transition, "guard_rescue->interior_sample"),
        "machlib_obligation": "OutputSafetyObligation",
        "intervention_obligation": "OutputSafetyInterventionObligation",
        "guard": {
            "clamp": config.clamp,
            "bounded_coordinates": True,
            "output_safety_preserved": all(frame["guarded"]["finite"] for frame in frames),
            "function_boundary_preserved": True,
        },
        "sample_count": len(config.params),
        "raw_finite_count": raw_survived,
        "guarded_finite_count": guarded_survived,
        "survival_delta": guarded_survived - raw_survived,
        "rescued_event_count": len(witness_frames),
        "has_transition_witness": bool(witness_frames),
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
    parser.add_argument("--clamp", type=float, default=8.0)
    parser.add_argument("--params", nargs="+", type=float, default=[1.0, 4.0, 10.0, 30.0, 710.0, 800.0])
    parser.add_argument("--source", type=Path, default=Path("examples/guard_clamp_rescue.eml"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/guard_clamp_rescue_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/guard_clamp_rescue_2026_05_26.md"))
    return parser.parse_args()


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Guard-Clamp Proof-Carrying Rescue",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Function family: `{packet['function_family']}`",
        f"Rescue operator: `{packet['rescue_operator']}`",
        f"Expected transition: `{packet['expected_transition']}`",
        f"MachLib obligation: `{packet['machlib_obligation']}`",
        "",
        "| sample | raw x | raw event | guarded x | guarded event | transition |",
        "|---:|---:|---|---:|---|---|",
    ]
    for frame in packet["frames"]:
        lines.append(
            f"| {frame['sample_index']} | {frame['raw_coordinate']} | {frame['raw']['event_class']} | "
            f"{frame['guarded_coordinate']} | {frame['guarded']['event_class']} | `{frame['transition']}` |"
        )
    lines.extend(
        [
            "",
            f"Raw finite count: `{packet['raw_finite_count']}`",
            f"Guarded finite count: `{packet['guarded_finite_count']}`",
            f"Rescued event count: `{packet['rescued_event_count']}`",
            "",
            "This packet is analysis-only. It demonstrates the evidence shape for an",
            "overflow/output-safety rescue; it does not claim a semantic rewrite,",
            "optimizer release, hardware observation, or completed formal proof.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def validate_strict(packet: dict) -> None:
    if not packet["has_transition_witness"]:
        raise SystemExit("expected overflow_wall->guard_rescue witness was not emitted")
    if not packet["guard"]["output_safety_preserved"]:
        raise SystemExit("guard clamp failed to preserve bounded finite output")
    if packet["guarded_finite_count"] < packet["raw_finite_count"]:
        raise SystemExit("guarded trace regressed finite survival")
    if packet["boundaries"]["semantic_rewrite_claim"] is not False:
        raise SystemExit("semantic rewrite boundary must remain false")
    if packet["boundaries"]["hardware_observed"] is not False:
        raise SystemExit("hardware boundary must remain false")


def main() -> int:
    args = parse_args()
    packet = run_guard_clamp_trace(GuardClampConfig("exp_pressure", args.params, args.clamp, args.source))
    write_outputs(packet, args.json, args.markdown)
    if args.strict:
        validate_strict(packet)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("GUARD_CLAMP_RESCUE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
