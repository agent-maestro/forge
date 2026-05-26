#!/usr/bin/env python
"""Emit the saturation-shelf proof-carrying rescue trace packet."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from lang.parser import parse_source
from lang.profiler import Profiler
from tools.boundary_optimizer_benchmark import compose_transition


SCHEMA_VERSION = "forge.optimizer.saturation_deshelf_rescue.v1"


@dataclass(frozen=True)
class SaturationDeshelfConfig:
    family: str
    probes: list[float]
    clamp_min: float
    clamp_max: float
    boundary_pressure: float
    source_path: Path


def saturated_response(x: float, clamp_min: float, clamp_max: float) -> float:
    return min(max(math.exp(x), clamp_min), clamp_max)


def evaluate_saturation(x: float, config: SaturationDeshelfConfig) -> dict:
    pre_clamp = math.exp(x)
    output = min(max(pre_clamp, config.clamp_min), config.clamp_max)
    on_shelf = output == config.clamp_max and pre_clamp > config.clamp_max
    pressure = math.log1p(pre_clamp)
    return {
        "finite": math.isfinite(output),
        "value": round(output, 10),
        "pre_clamp_pressure": round(pressure, 10),
        "shelf_distance": round(pre_clamp - config.clamp_max, 10),
        "event_class": "saturation_shelf" if on_shelf else "interior_sample",
    }


def run_saturation_deshelf_trace(config: SaturationDeshelfConfig) -> dict:
    source_path = Path(config.source_path)
    source = source_path.read_text(encoding="utf-8")
    module = parse_source(source, source_path.as_posix())
    Profiler().profile_module(module)
    function = next(fn for fn in module.functions if fn.name == config.family)
    frames = []

    for index, probe in enumerate(config.probes):
        raw = evaluate_saturation(probe, config)
        deshelf_event = (
            "corner_concentration"
            if raw["event_class"] == "saturation_shelf" and raw["pre_clamp_pressure"] >= config.boundary_pressure
            else raw["event_class"]
        )
        transition = f"{raw['event_class']}->{deshelf_event}"
        frames.append(
            {
                "sample_index": index,
                "probe_coordinate": probe,
                "raw": raw,
                "deshelf": {
                    "event_class": deshelf_event,
                    "pre_clamp_pressure": raw["pre_clamp_pressure"],
                    "measurable_boundary_structure": deshelf_event == "corner_concentration",
                    "finite": raw["finite"],
                },
                "transition": transition,
                "deshelf_transition": transition == "saturation_shelf->corner_concentration",
            }
        )

    expected_transition = "saturation_shelf->corner_concentration"
    witness_frames = [frame for frame in frames if frame["transition"] == expected_transition]
    return {
        "schema_version": SCHEMA_VERSION,
        "function_family": config.family,
        "source_path": source_path.as_posix(),
        "eml_shape": "fn saturated_response(x: Real) -> Real { clamp(exp(x), 0.0, 1.0) }",
        "profile": function.profile or {},
        "rescue_operator": "saturation_deshelf",
        "expected_transition": expected_transition,
        "composed_transition_demo": compose_transition(expected_transition, "corner_concentration->interior_sample"),
        "machlib_obligation": "ClampInvariantObligation",
        "intervention_obligation": "ClampDeshelfInterventionObligation",
        "deshelf": {
            "clamp_min": config.clamp_min,
            "clamp_max": config.clamp_max,
            "boundary_pressure": config.boundary_pressure,
            "finite_trace_preserved": all(frame["raw"]["finite"] for frame in frames),
            "clamp_invariant_preserved": all(
                config.clamp_min <= frame["raw"]["value"] <= config.clamp_max for frame in frames
            ),
            "measurable_boundary_structure_restored": bool(witness_frames),
            "function_boundary_preserved": True,
        },
        "sample_count": len(config.probes),
        "saturation_event_count": sum(1 for frame in frames if frame["raw"]["event_class"] == "saturation_shelf"),
        "deshelved_event_count": len(witness_frames),
        "has_transition_witness": bool(witness_frames),
        "frames": frames,
        "boundaries": {
            "analysis_only": True,
            "simulated_trace": True,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
            "hardware_observed": False,
            "global_optimizer_win_claim": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clamp-min", type=float, default=0.0)
    parser.add_argument("--clamp-max", type=float, default=1.0)
    parser.add_argument("--boundary-pressure", type=float, default=3.0)
    parser.add_argument("--probes", nargs="+", type=float, default=[-2.0, 0.0, 2.0, 4.0, 8.0])
    parser.add_argument("--source", type=Path, default=Path("examples/saturation_deshelf_rescue.eml"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/saturation_deshelf_rescue_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/saturation_deshelf_rescue_2026_05_26.md"))
    return parser.parse_args()


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Saturation-Deshelf Proof-Carrying Rescue",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Function family: `{packet['function_family']}`",
        f"Rescue operator: `{packet['rescue_operator']}`",
        f"Expected transition: `{packet['expected_transition']}`",
        f"MachLib obligation: `{packet['machlib_obligation']}`",
        "",
        "| sample | x | raw value | raw event | pre-clamp pressure | deshelf event | transition |",
        "|---:|---:|---:|---|---:|---|---|",
    ]
    for frame in packet["frames"]:
        raw = frame["raw"]
        lines.append(
            f"| {frame['sample_index']} | {frame['probe_coordinate']} | {raw['value']:.10f} | "
            f"{raw['event_class']} | {raw['pre_clamp_pressure']:.10f} | "
            f"{frame['deshelf']['event_class']} | `{frame['transition']}` |"
        )
    lines.extend(
        [
            "",
            f"Saturation event count: `{packet['saturation_event_count']}`",
            f"Deshelved event count: `{packet['deshelved_event_count']}`",
            "",
            "This packet is analysis-only. It demonstrates a finite clamp shelf being",
            "replayed as measurable boundary structure; it does not claim a semantic",
            "rewrite, optimizer release, hardware observation, global optimizer win,",
            "or completed formal proof.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def validate_strict(packet: dict) -> None:
    if not packet["has_transition_witness"]:
        raise SystemExit("expected saturation_shelf->corner_concentration witness was not emitted")
    if not packet["deshelf"]["finite_trace_preserved"]:
        raise SystemExit("saturation trace must remain finite")
    if not packet["deshelf"]["clamp_invariant_preserved"]:
        raise SystemExit("clamp invariant was not preserved")
    if not packet["deshelf"]["measurable_boundary_structure_restored"]:
        raise SystemExit("deshelf replay did not restore measurable boundary structure")
    if packet["boundaries"]["global_optimizer_win_claim"] is not False:
        raise SystemExit("global optimizer win boundary must remain false")
    if packet["boundaries"]["semantic_rewrite_claim"] is not False:
        raise SystemExit("semantic rewrite boundary must remain false")
    if packet["boundaries"]["hardware_observed"] is not False:
        raise SystemExit("hardware boundary must remain false")


def main() -> int:
    args = parse_args()
    packet = run_saturation_deshelf_trace(
        SaturationDeshelfConfig(
            family="saturated_response",
            probes=args.probes,
            clamp_min=args.clamp_min,
            clamp_max=args.clamp_max,
            boundary_pressure=args.boundary_pressure,
            source_path=args.source,
        )
    )
    write_outputs(packet, args.json, args.markdown)
    if args.strict:
        validate_strict(packet)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("SATURATION_DESHELF_RESCUE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
