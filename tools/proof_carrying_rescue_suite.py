#!/usr/bin/env python
"""Emit the Monogate proof-carrying rescue suite v0 manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    if args.write_lane_reports:
        write_lane_reports(packet)
    if args.strict:
        validate_strict(packet)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.markdown}")
    print("PROOF_CARRYING_RESCUE_SUITE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
