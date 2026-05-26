#!/usr/bin/env python
"""Replay/validate a proof-carrying rescue suite manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED_SCHEMA = "forge.optimizer.proof_carrying_rescue_suite.v0"
EXPECTED_LANES = {
    "log_domain_lift": ("domain_wall->log_domain_rescue", "PositiveCoordinateObligation"),
    "guard_clamp": ("overflow_wall->guard_rescue", "OutputSafetyObligation"),
    "precision_escape": ("phantom_attractor->interior_sample", "PrecisionSensitivityObligation"),
    "saturation_deshelf": ("saturation_shelf->corner_concentration", "ClampInvariantObligation"),
}
CONSERVATIVE_BOUNDARY_FLAGS = {
    "semantic_rewrite_claim",
    "optimizer_release_claim",
    "hardware_observed",
    "completed_formal_proof_claim",
}


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def replay_manifest(packet: dict) -> dict:
    issues: list[str] = []
    if packet.get("schema_version") != EXPECTED_SCHEMA:
        issues.append(f"unexpected schema_version: {packet.get('schema_version')}")
    if packet.get("lane_count") != 4:
        issues.append(f"expected 4 lanes, found {packet.get('lane_count')}")
    if packet.get("complete_v0") is not True:
        issues.append("complete_v0 must be true")

    lanes = {lane.get("rescue_operator"): lane for lane in packet.get("lanes", [])}
    if set(lanes) != set(EXPECTED_LANES):
        issues.append(f"unexpected rescue operators: {sorted(lanes)}")

    for operator, (transition, obligation) in EXPECTED_LANES.items():
        lane = lanes.get(operator)
        if lane is None:
            continue
        if lane.get("expected_transition") != transition:
            issues.append(f"{operator} transition mismatch: {lane.get('expected_transition')}")
        if lane.get("machlib_obligation") != obligation:
            issues.append(f"{operator} obligation mismatch: {lane.get('machlib_obligation')}")
        if lane.get("has_transition_witness") is not True:
            issues.append(f"{operator} missing transition witness")

    packets = packet.get("packets", [])
    if len(packets) != 4:
        issues.append(f"expected 4 embedded packets, found {len(packets)}")
    for embedded in packets:
        operator = embedded.get("rescue_operator")
        if operator not in EXPECTED_LANES:
            issues.append(f"unexpected embedded packet operator: {operator}")
            continue
        transition, obligation = EXPECTED_LANES[operator]
        if embedded.get("expected_transition") != transition:
            issues.append(f"{operator} embedded transition mismatch: {embedded.get('expected_transition')}")
        if embedded.get("machlib_obligation") != obligation:
            issues.append(f"{operator} embedded obligation mismatch: {embedded.get('machlib_obligation')}")
        if embedded.get("has_transition_witness") is not True:
            issues.append(f"{operator} embedded packet missing witness")
        embedded_boundaries = embedded.get("boundaries", {})
        for flag in CONSERVATIVE_BOUNDARY_FLAGS:
            if flag in embedded_boundaries and embedded_boundaries.get(flag) is not False:
                issues.append(f"{operator} boundary flag must be false: {flag}")

    for flag in CONSERVATIVE_BOUNDARY_FLAGS:
        if packet.get("boundaries", {}).get(flag) is not False:
            issues.append(f"suite boundary flag must be false: {flag}")

    return {
        "schema_version": "forge.optimizer.proof_carrying_rescue_replay.v0",
        "source_schema": packet.get("schema_version"),
        "valid": not issues,
        "issue_count": len(issues),
        "issues": issues,
        "lane_count": packet.get("lane_count"),
        "operators": sorted(lanes),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = replay_manifest(load_manifest(args.manifest))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if args.strict and not result["valid"]:
        raise SystemExit("PROOF_CARRYING_RESCUE_REPLAY_FAILED")
    print("PROOF_CARRYING_RESCUE_REPLAY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
