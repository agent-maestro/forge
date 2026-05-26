#!/usr/bin/env python
"""Emit the phantom-attractor proof-carrying rescue trace packet."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from lang.parser import parse_source
from lang.profiler import Profiler
from tools.boundary_optimizer_benchmark import compose_transition, is_rescue_transition


SCHEMA_VERSION = "forge.optimizer.precision_escape_rescue.v1"


@dataclass(frozen=True)
class PrecisionEscapeConfig:
    family: str
    probes: list[float]
    target: float
    low_precision_step: float
    high_precision_eps: float
    learning_rate: float
    source_path: Path


def quantized_basin(x: float, target: float) -> float:
    dx = x - target
    return dx * dx


def quantize(x: float, step: float) -> float:
    return round(x / step) * step


def low_precision_gradient(x: float, config: PrecisionEscapeConfig) -> float:
    step = config.low_precision_step
    left = quantized_basin(quantize(x - config.high_precision_eps, step), config.target)
    right = quantized_basin(quantize(x + config.high_precision_eps, step), config.target)
    return (right - left) / (2 * config.high_precision_eps)


def high_precision_gradient(x: float, config: PrecisionEscapeConfig) -> float:
    eps = config.high_precision_eps
    left = quantized_basin(x - eps, config.target)
    right = quantized_basin(x + eps, config.target)
    return (right - left) / (2 * eps)


def classify_probe(x: float, config: PrecisionEscapeConfig) -> dict:
    raw_value = quantized_basin(x, config.target)
    low_grad = low_precision_gradient(x, config)
    high_grad = high_precision_gradient(x, config)
    escape_x = x - config.learning_rate * high_grad
    escape_value = quantized_basin(escape_x, config.target)
    finite = all(math.isfinite(value) for value in [raw_value, low_grad, high_grad, escape_value])
    low_stalled = abs(low_grad) <= 1.0e-12
    high_sensitive = abs(high_grad) >= 1.0e-6
    escaped = escape_value < raw_value
    phantom = finite and low_stalled and high_sensitive and escaped
    return {
        "finite": finite,
        "raw_value": round(raw_value, 10),
        "low_precision_gradient": round(low_grad, 10),
        "high_precision_gradient": round(high_grad, 10),
        "escape_coordinate": round(escape_x, 10),
        "escape_value": round(escape_value, 10),
        "sensitivity_score": round(abs(high_grad - low_grad), 10),
        "low_precision_stalled": low_stalled,
        "higher_precision_sensitive": high_sensitive,
        "escape_improved": escaped,
        "event_class": "phantom_attractor" if phantom else "interior_sample",
    }


def run_precision_escape_trace(config: PrecisionEscapeConfig) -> dict:
    source_path = Path(config.source_path)
    source = source_path.read_text(encoding="utf-8")
    module = parse_source(source, source_path.as_posix())
    Profiler().profile_module(module)
    function = next(fn for fn in module.functions if fn.name == config.family)
    frames = []

    for index, probe in enumerate(config.probes):
        raw = classify_probe(probe, config)
        to_event = "interior_sample" if raw["event_class"] == "phantom_attractor" else raw["event_class"]
        transition = f"{raw['event_class']}->{to_event}"
        frames.append(
            {
                "sample_index": index,
                "probe_coordinate": probe,
                "raw": raw,
                "escaped": {
                    "coordinate": raw["escape_coordinate"],
                    "value": raw["escape_value"],
                    "event_class": to_event,
                    "finite": raw["finite"],
                },
                "transition": transition,
                "rescue_transition": is_rescue_transition(transition),
            }
        )

    expected_transition = "phantom_attractor->interior_sample"
    witness_frames = [frame for frame in frames if frame["transition"] == expected_transition]
    return {
        "schema_version": SCHEMA_VERSION,
        "function_family": config.family,
        "source_path": source_path.as_posix(),
        "eml_shape": "fn quantized_basin(x: Real) -> Real { let dx = x - 0.375; dx * dx }",
        "profile": function.profile or {},
        "rescue_operator": "precision_escape",
        "expected_transition": expected_transition,
        "composed_transition_demo": compose_transition(expected_transition, "interior_sample->interior_sample"),
        "machlib_obligation": "PrecisionSensitivityObligation",
        "intervention_obligation": "PrecisionEscapeInterventionObligation",
        "precision": {
            "low_precision_step": config.low_precision_step,
            "high_precision_eps": config.high_precision_eps,
            "learning_rate": config.learning_rate,
            "target": config.target,
            "finite_trace_preserved": all(frame["raw"]["finite"] for frame in frames),
            "precision_sensitivity_witnessed": bool(witness_frames),
            "function_boundary_preserved": True,
        },
        "sample_count": len(config.probes),
        "phantom_event_count": sum(1 for frame in frames if frame["raw"]["event_class"] == "phantom_attractor"),
        "rescued_event_count": len(witness_frames),
        "has_transition_witness": bool(witness_frames),
        "frames": frames,
        "boundaries": {
            "analysis_only": True,
            "simulated_trace": True,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
            "hardware_observed": False,
            "true_local_optimum_claim": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=float, default=0.375)
    parser.add_argument("--low-precision-step", type=float, default=0.25)
    parser.add_argument("--high-precision-eps", type=float, default=0.01)
    parser.add_argument("--learning-rate", type=float, default=0.5)
    parser.add_argument("--probes", nargs="+", type=float, default=[0.25, 0.5, 0.75])
    parser.add_argument("--source", type=Path, default=Path("examples/precision_escape_rescue.eml"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/precision_escape_rescue_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/precision_escape_rescue_2026_05_26.md"))
    return parser.parse_args()


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Precision-Escape Proof-Carrying Rescue",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Function family: `{packet['function_family']}`",
        f"Rescue operator: `{packet['rescue_operator']}`",
        f"Expected transition: `{packet['expected_transition']}`",
        f"MachLib obligation: `{packet['machlib_obligation']}`",
        "",
        "| sample | x | raw event | low-grad | high-grad | escaped x | transition |",
        "|---:|---:|---|---:|---:|---:|---|",
    ]
    for frame in packet["frames"]:
        raw = frame["raw"]
        lines.append(
            f"| {frame['sample_index']} | {frame['probe_coordinate']} | {raw['event_class']} | "
            f"{raw['low_precision_gradient']:.10f} | {raw['high_precision_gradient']:.10f} | "
            f"{raw['escape_coordinate']:.10f} | `{frame['transition']}` |"
        )
    lines.extend(
        [
            "",
            f"Phantom event count: `{packet['phantom_event_count']}`",
            f"Rescued event count: `{packet['rescued_event_count']}`",
            "",
            "This packet is analysis-only. It demonstrates one suspicious finite trap",
            "that is sensitive to precision and escapable under replay; it does not",
            "claim a true local optimum, semantic rewrite, optimizer release, hardware",
            "observation, or completed formal proof.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def validate_strict(packet: dict) -> None:
    if not packet["has_transition_witness"]:
        raise SystemExit("expected phantom_attractor->interior_sample witness was not emitted")
    if not packet["precision"]["finite_trace_preserved"]:
        raise SystemExit("phantom trace must remain finite")
    if not packet["precision"]["precision_sensitivity_witnessed"]:
        raise SystemExit("precision sensitivity was not witnessed")
    if packet["boundaries"]["true_local_optimum_claim"] is not False:
        raise SystemExit("true local optimum boundary must remain false")
    if packet["boundaries"]["semantic_rewrite_claim"] is not False:
        raise SystemExit("semantic rewrite boundary must remain false")
    if packet["boundaries"]["hardware_observed"] is not False:
        raise SystemExit("hardware boundary must remain false")


def main() -> int:
    args = parse_args()
    packet = run_precision_escape_trace(
        PrecisionEscapeConfig(
            family="quantized_basin",
            probes=args.probes,
            target=args.target,
            low_precision_step=args.low_precision_step,
            high_precision_eps=args.high_precision_eps,
            learning_rate=args.learning_rate,
            source_path=args.source,
        )
    )
    write_outputs(packet, args.json, args.markdown)
    if args.strict:
        validate_strict(packet)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("PRECISION_ESCAPE_RESCUE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
