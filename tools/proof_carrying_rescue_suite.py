#!/usr/bin/env python
"""Emit the Monogate proof-carrying rescue suite v0 manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.guard_clamp_rescue import GuardClampConfig, run_guard_clamp_trace, write_outputs as write_guard_outputs
from tools.precision_escape_rescue import (
    PrecisionEscapeConfig,
    run_precision_escape_trace,
    write_outputs as write_precision_outputs,
)
from tools.proof_carrying_rescue import RescueConfig, run_rescue_trace, write_outputs as write_log_domain_outputs
from tools.saturation_deshelf_rescue import (
    SaturationDeshelfConfig,
    run_saturation_deshelf_trace,
    write_outputs as write_saturation_outputs,
)


SCHEMA_VERSION = "forge.optimizer.proof_carrying_rescue_suite.v0"
EXPLORER_SCHEMA_VERSION = "monogate.dev.rescue_suite_explorer_fixture.v0"


def run_suite() -> dict:
    packets = [
        run_rescue_trace(
            RescueConfig(
                "positive_log_energy",
                [-2.0, -0.5, 0.0, 0.25, 1.25, 2.0],
                4.0,
                Path("examples/proof_carrying_rescue.eml"),
            )
        ),
        run_guard_clamp_trace(
            GuardClampConfig("exp_pressure", [1.0, 4.0, 10.0, 30.0, 710.0, 800.0], 8.0, Path("examples/guard_clamp_rescue.eml"))
        ),
        run_precision_escape_trace(
            PrecisionEscapeConfig(
                "quantized_basin",
                [0.25, 0.5, 0.75],
                0.375,
                0.25,
                0.01,
                0.5,
                Path("examples/precision_escape_rescue.eml"),
            )
        ),
        run_saturation_deshelf_trace(
            SaturationDeshelfConfig(
                "saturated_response",
                [-2.0, 0.0, 2.0, 4.0, 8.0],
                0.0,
                1.0,
                3.0,
                Path("examples/saturation_deshelf_rescue.eml"),
            )
        ),
    ]
    lanes = [
        {
            "rescue_operator": packet["rescue_operator"],
            "expected_transition": packet["expected_transition"],
            "machlib_obligation": packet["machlib_obligation"],
            "source_path": packet["source_path"],
            "schema_version": packet["schema_version"],
            "has_transition_witness": packet["has_transition_witness"],
        }
        for packet in packets
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": "proof-carrying-rescue-v0",
        "lane_count": len(lanes),
        "complete_v0": all(lane["has_transition_witness"] for lane in lanes),
        "lanes": lanes,
        "boundaries": {
            "analysis_only": True,
            "simulated_trace": True,
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
            "hardware_observed": False,
            "completed_formal_proof_claim": False,
        },
        "packets": packets,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/proof_carrying_rescue_suite_v0_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/proof_carrying_rescue_suite_v0_2026_05_26.md"))
    parser.add_argument("--replay-json", type=Path, default=None)
    parser.add_argument("--explorer-json", type=Path, default=None)
    parser.add_argument("--write-lane-reports", action="store_true")
    return parser.parse_args()


def write_outputs(packet: dict, output_json: Path, output_markdown: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Proof-Carrying Rescue Suite v0",
        "",
        f"Schema: `{packet['schema_version']}`",
        f"Lanes: `{packet['lane_count']}`",
        f"Complete v0: `{packet['complete_v0']}`",
        "",
        "| rescue operator | transition | obligation | source | witness |",
        "|---|---|---|---|---:|",
    ]
    for lane in packet["lanes"]:
        lines.append(
            f"| `{lane['rescue_operator']}` | `{lane['expected_transition']}` | "
            f"`{lane['machlib_obligation']}` | `{lane['source_path']}` | {str(lane['has_transition_witness']).lower()} |"
        )
    lines.extend(
        [
            "",
            "This manifest is analysis-only. It aggregates the four v0 proof-carrying",
            "rescue packets; it does not claim semantic rewrites, optimizer release,",
            "hardware observations, or completed formal proofs.",
            "",
        ]
    )
    output_markdown.write_text("\n".join(lines), encoding="utf-8")


def _event_payload(frame: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    if "lifted" in frame:
        return frame["raw"], frame["lifted"], "lifted"
    if "guarded" in frame:
        return frame["raw"], frame["guarded"], "guarded"
    if "escaped" in frame:
        return frame["raw"], frame["escaped"], "escaped"
    if "deshelf" in frame:
        return frame["raw"], frame["deshelf"], "deshelf"
    return frame.get("raw", {}), {}, "rescued"


def _coordinate_text(frame: dict[str, Any], rescue_key: str) -> str:
    if rescue_key == "lifted":
        return f"x={frame['raw_coordinate']} -> {frame['lifted_coordinate']}"
    if rescue_key == "guarded":
        return f"x={frame['raw_coordinate']} -> guard={frame['guarded_coordinate']}"
    if rescue_key == "escaped":
        return f"x={frame['probe_coordinate']} -> escape={frame['escaped']['coordinate']}"
    if rescue_key == "deshelf":
        return f"x={frame['probe_coordinate']}"
    return f"sample={frame.get('sample_index')}"


def _metric_text(raw: dict[str, Any], rescued: dict[str, Any], rescue_key: str) -> str:
    if rescue_key in {"lifted", "guarded"}:
        return f"finite: {str(raw.get('finite')).lower()} -> {str(rescued.get('finite')).lower()}"
    if rescue_key == "escaped":
        return (
            f"low grad {raw.get('low_precision_gradient')}, "
            f"high grad {raw.get('high_precision_gradient')}"
        )
    if rescue_key == "deshelf":
        return f"pressure {rescued.get('pre_clamp_pressure')}"
    return ""


def build_explorer_fixture(manifest: dict, replay: dict) -> dict:
    """Build the compact JSON shape consumed by monogate.dev.

    The Explorer intentionally receives a display fixture, not a new
    authority. The authoritative evidence remains the suite manifest and
    replay JSON emitted beside this file.
    """
    lanes = []
    for packet in manifest["packets"]:
        transition = packet["expected_transition"]
        from_event, to_event = transition.split("->", 1)
        frames = []
        for frame in packet["frames"]:
            raw, rescued, rescue_key = _event_payload(frame)
            frames.append(
                {
                    "sample": frame["sample_index"],
                    "input": _coordinate_text(frame, rescue_key),
                    "rawEvent": raw.get("event_class", from_event),
                    "rescueEvent": rescued.get("event_class", to_event),
                    "transition": frame.get("transition", transition),
                    "metric": _metric_text(raw, rescued, rescue_key),
                    "raw": raw,
                    "rescued": rescued,
                    "isWitness": frame.get("transition") == transition,
                }
            )
        lanes.append(
            {
                "operator": packet["rescue_operator"],
                "fromEvent": from_event,
                "toEvent": to_event,
                "transition": transition,
                "obligation": packet["machlib_obligation"],
                "source": packet["source_path"],
                "fixture": packet["eml_shape"],
                "packetSchema": packet["schema_version"],
                "claim": {
                    "log_domain_lift": "Raw non-positive coordinates are lifted through exp(theta), preserving a positive internal coordinate path.",
                    "guard_clamp": "Raw overflow pressure is replayed through a bounded guard coordinate, preserving finite output.",
                    "precision_escape": "A finite low-precision stall is replayed at higher precision, exposing a descent direction and escape witness.",
                    "saturation_deshelf": "Finite clamp-shelf collapse is replayed through pre-clamp pressure, restoring measurable boundary structure.",
                }[packet["rescue_operator"]],
                "summary": {
                    "sampleCount": packet.get("sample_count"),
                    "rescuedEventCount": packet.get("rescued_event_count")
                    or packet.get("deshelved_event_count")
                    or packet.get("saturation_event_count"),
                    "hasTransitionWitness": packet["has_transition_witness"],
                },
                "frames": frames,
            }
        )

    return {
        "schemaVersion": EXPLORER_SCHEMA_VERSION,
        "generatedFrom": {
            "manifestSchema": manifest["schema_version"],
            "replaySchema": replay["schema_version"],
            "suite": manifest["suite"],
        },
        "replayStatus": {
            "schema": replay["schema_version"],
            "sourceSchema": replay["source_schema"],
            "valid": replay["valid"],
            "issueCount": replay["issue_count"],
            "issues": replay["issues"],
            "laneCount": replay["lane_count"],
            "operators": replay["operators"],
            "manifest": "reports/proof_carrying_rescue_suite_v0_2026_05_26.json",
            "replay": "reports/proof_carrying_rescue_replay_v0_2026_05_26.json",
        },
        "boundaryFlags": manifest["boundaries"],
        "lanes": lanes,
    }


def write_explorer_fixture(manifest: dict, replay: dict, output_json: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(build_explorer_fixture(manifest, replay), indent=2) + "\n",
        encoding="utf-8",
    )


def write_lane_reports(packet: dict) -> None:
    by_operator = {lane["rescue_operator"]: lane for lane in packet["lanes"]}
    packets = {p["rescue_operator"]: p for p in packet["packets"]}
    if "log_domain_lift" in by_operator:
        write_log_domain_outputs(
            packets["log_domain_lift"],
            Path("reports/proof_carrying_rescue_2026_05_26.json"),
            Path("reports/proof_carrying_rescue_2026_05_26.md"),
        )
    if "guard_clamp" in by_operator:
        write_guard_outputs(
            packets["guard_clamp"],
            Path("reports/guard_clamp_rescue_2026_05_26.json"),
            Path("reports/guard_clamp_rescue_2026_05_26.md"),
        )
    if "precision_escape" in by_operator:
        write_precision_outputs(
            packets["precision_escape"],
            Path("reports/precision_escape_rescue_2026_05_26.json"),
            Path("reports/precision_escape_rescue_2026_05_26.md"),
        )
    if "saturation_deshelf" in by_operator:
        write_saturation_outputs(
            packets["saturation_deshelf"],
            Path("reports/saturation_deshelf_rescue_2026_05_26.json"),
            Path("reports/saturation_deshelf_rescue_2026_05_26.md"),
        )


def validate_strict(packet: dict) -> None:
    if packet["lane_count"] != 4:
        raise SystemExit("proof-carrying rescue suite v0 must contain four lanes")
    if not packet["complete_v0"]:
        raise SystemExit("proof-carrying rescue suite v0 is missing a transition witness")
    expected = {
        "domain_wall->log_domain_rescue",
        "overflow_wall->guard_rescue",
        "phantom_attractor->interior_sample",
        "saturation_shelf->corner_concentration",
    }
    observed = {lane["expected_transition"] for lane in packet["lanes"]}
    if observed != expected:
        raise SystemExit(f"unexpected rescue transitions: {sorted(observed)}")
    if packet["boundaries"]["semantic_rewrite_claim"] is not False:
        raise SystemExit("semantic rewrite boundary must remain false")
    if packet["boundaries"]["hardware_observed"] is not False:
        raise SystemExit("hardware boundary must remain false")


def main() -> int:
    args = parse_args()
    packet = run_suite()
    write_outputs(packet, args.json, args.markdown)
    replay = None
    if args.replay_json or args.explorer_json:
        from tools.proof_carrying_rescue_replay import replay_manifest

        replay = replay_manifest(packet)
    if args.replay_json and replay is not None:
        args.replay_json.parent.mkdir(parents=True, exist_ok=True)
        args.replay_json.write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    if args.explorer_json and replay is not None:
        write_explorer_fixture(packet, replay, args.explorer_json)
    if args.write_lane_reports:
        write_lane_reports(packet)
    if args.strict:
        validate_strict(packet)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    if args.replay_json:
        print(f"Wrote {args.replay_json}")
    if args.explorer_json:
        print(f"Wrote {args.explorer_json}")
    print("PROOF_CARRYING_RESCUE_SUITE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
