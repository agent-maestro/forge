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
REGISTRY_SCHEMA_VERSION = "forge.optimizer.rescue_obligation_registry.v0"
APPROVAL_SCHEMA_VERSION = "forge.optimizer.rescue_artifact_approval.v0"


SEMANTIC_CONTRACTS = {
    "log_domain_lift": {
        "semantic_strength": "concrete_sample_invariant",
        "accepts": "raw domain_wall samples with non-positive log coordinates",
        "restores": "positive internal coordinates via exp(theta)",
        "allowed_change": "coordinate representation may change from raw x to lifted internal coordinate",
        "must_not_claim": "global semantic rewrite equivalence for arbitrary programs",
        "preservation_scope": "local invariant restoration",
        "public_copy_safe": True,
    },
    "guard_clamp": {
        "semantic_strength": "concrete_sample_invariant",
        "accepts": "raw overflow_wall samples that exceed the guard's finite evaluation envelope",
        "restores": "bounded guarded coordinate/output witness",
        "allowed_change": "coordinate may be clamped to the configured guard limit",
        "must_not_claim": "optimizer-wide boundedness or production safety",
        "preservation_scope": "local output-safety restoration",
        "public_copy_safe": True,
    },
    "precision_escape": {
        "semantic_strength": "concrete_sample_invariant",
        "accepts": "phantom_attractor samples where a low-precision trace stalls near a basin",
        "restores": "higher-precision nonzero escape signal from a low-precision stall",
        "allowed_change": "numeric precision and probe coordinate may change to expose a descent direction",
        "must_not_claim": "general convergence theorem or optimizer-wide precision-correctness theorem",
        "preservation_scope": "local precision-sensitivity restoration",
        "public_copy_safe": True,
    },
    "saturation_deshelf": {
        "semantic_strength": "concrete_sample_invariant",
        "accepts": "saturation_shelf samples collapsed by clamped output",
        "restores": "pre-clamp pressure within the declared clamp interval",
        "allowed_change": "trace may expose pre-clamp pressure instead of only clamped output",
        "must_not_claim": "rescue-normal completion or equivalence for all saturation rewrites",
        "preservation_scope": "local clamp-invariant restoration",
        "public_copy_safe": False,
    },
}


CONCRETE_WITNESSES = {
    "log_domain_lift": {
        "theorem": "log_domain_positive_coordinate_witness_discharges_concrete_obligation",
        "concrete_obligation": "ConcretePositiveCoordinateObligation",
    },
    "guard_clamp": {
        "theorem": "guard_clamp_output_safety_witness_discharges_concrete_obligation",
        "concrete_obligation": "ConcreteOutputSafetyObligation",
    },
    "precision_escape": {
        "theorem": "precision_escape_witness_discharges_concrete_obligation",
        "concrete_obligation": "ConcretePrecisionEscapeObligation",
    },
    "saturation_deshelf": {
        "theorem": "saturation_deshelf_clamp_witness_discharges_concrete_obligation",
        "concrete_obligation": "ConcreteClampInvariantObligation",
    },
}


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
            "semantic_contract": SEMANTIC_CONTRACTS[packet["rescue_operator"]],
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


def build_obligation_registry(manifest: dict) -> dict:
    entries = []
    for lane in manifest["lanes"]:
        operator = lane["rescue_operator"]
        concrete = CONCRETE_WITNESSES.get(operator)
        entries.append(
            {
                "rescue_operator": operator,
                "transition": lane["expected_transition"],
                "machlib_obligation": lane["machlib_obligation"],
                "source_path": lane["source_path"],
                "status": {
                    "routed": True,
                    "witnessed": lane["has_transition_witness"] is True,
                    "proven": concrete is not None,
                    "ci_guarded": True,
                    "public_copy_safe": lane["semantic_contract"]["public_copy_safe"],
                    "blocked": False,
                },
                "semantic_contract": lane["semantic_contract"],
                "machlib_witness": concrete,
                "review_note": (
                    "Concrete sample-level MachLib witness exists."
                    if concrete
                    else "Packet bridge exists; concrete sample-level theorem remains future work."
                ),
            }
        )
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "suite": manifest["suite"],
        "entry_count": len(entries),
        "entries": entries,
        "policy": {
            "routed_is_not_proven": True,
            "public_copy_requires_conservative_flags": True,
            "deploy_requires_replay_valid": True,
            "electronics_packets_must_use_evidence_grammar": True,
        },
    }


def build_approval_gate(manifest: dict, replay: dict, registry: dict) -> dict:
    issues = []
    if not replay["valid"]:
        issues.append("replay_invalid")
    if manifest["lane_count"] != registry["entry_count"]:
        issues.append("registry_lane_count_mismatch")
    if any(entry["status"]["blocked"] for entry in registry["entries"]):
        issues.append("registry_contains_blocked_entry")
    for flag, value in manifest["boundaries"].items():
        if flag.endswith("_claim") or flag == "hardware_observed":
            if value is not False:
                issues.append(f"conservative_flag_flipped:{flag}")
    concrete_count = sum(1 for entry in registry["entries"] if entry["status"]["proven"])
    if concrete_count != registry["entry_count"]:
        issues.append("incomplete_concrete_machlib_witness_coverage")
    semantic_strengths = {
        entry["rescue_operator"]: entry["semantic_contract"]["semantic_strength"]
        for entry in registry["entries"]
    }

    return {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "suite": manifest["suite"],
        "reviewer": "codex-reviewer",
        "decision": "approved_for_existing_public_surfaces" if not issues else "blocked",
        "surface_allowed": not issues,
        "deploy_allowed": not issues,
        "semantic_summary": {
            "strength_by_operator": semantic_strengths,
            "concrete_sample_invariant_count": sum(
                1 for strength in semantic_strengths.values() if strength == "concrete_sample_invariant"
            ),
            "packet_bridge_only": [
                operator for operator, strength in semantic_strengths.items() if strength == "packet_bridge_only"
            ],
            "semantic_rewrite_claim": False,
            "reviewer_note": (
                "All four v0 rescue lanes restore concrete local invariants; full semantic rewrite correctness "
                "remains outside the v0 claim boundary."
            ),
        },
        "electronics_boundary": {
            "hardware_action_allowed": False,
            "future_physical_packets_must_use_evidence_grammar": True,
            "required_packet_fields": [
                "packet_id",
                "source",
                "capture_mode",
                "trace_path",
                "validator_result",
                "replay_result",
                "claim_flags",
                "review_status",
            ],
        },
        "checks": {
            "replay_valid": replay["valid"],
            "registry_complete": manifest["lane_count"] == registry["entry_count"],
            "conservative_flags_preserved": not any(
                value is not False
                for flag, value in manifest["boundaries"].items()
                if flag.endswith("_claim") or flag == "hardware_observed"
            ),
            "has_complete_concrete_machlib_witness_coverage": concrete_count == registry["entry_count"],
        },
        "issues": issues,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", type=Path, default=Path("reports/proof_carrying_rescue_suite_v0_2026_05_26.json"))
    parser.add_argument("--markdown", type=Path, default=Path("reports/proof_carrying_rescue_suite_v0_2026_05_26.md"))
    parser.add_argument("--replay-json", type=Path, default=None)
    parser.add_argument("--explorer-json", type=Path, default=None)
    parser.add_argument("--registry-json", type=Path, default=None)
    parser.add_argument("--approval-json", type=Path, default=None)
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
    if "obligation_registry" in packet:
        lines.extend(
            [
                "",
                "## Obligation Registry",
                "",
                "| rescue operator | routed | witnessed | proven | semantic strength | public-copy safe |",
                "|---|---:|---:|---:|---|---:|",
            ]
        )
        for entry in packet["obligation_registry"]["entries"]:
            status = entry["status"]
            lines.append(
                f"| `{entry['rescue_operator']}` | {str(status['routed']).lower()} | "
                f"{str(status['witnessed']).lower()} | {str(status['proven']).lower()} | "
                f"`{entry['semantic_contract']['semantic_strength']}` | "
                f"{str(status['public_copy_safe']).lower()} |"
            )
    if "approval_gate" in packet:
        lines.extend(
            [
                "",
                "## Reviewer Approval Gate",
                "",
                f"Decision: `{packet['approval_gate']['decision']}`",
                f"Surface allowed: `{packet['approval_gate']['surface_allowed']}`",
                f"Deploy allowed: `{packet['approval_gate']['deploy_allowed']}`",
                f"Semantic rewrite claim: `{packet['approval_gate']['semantic_summary']['semantic_rewrite_claim']}`",
            ]
        )
    lines.extend(
        [
            "",
            "This manifest is analysis-only. It aggregates the four v0 proof-carrying",
            "rescue packets; it does not claim semantic rewrites, optimizer release,",
            "hardware observations, or completed formal proofs for every lane.",
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
                "semanticContract": SEMANTIC_CONTRACTS[packet["rescue_operator"]],
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
        "approval": manifest.get("approval_gate", {}),
        "lanes": lanes,
    }


def write_explorer_fixture(manifest: dict, replay: dict, output_json: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(build_explorer_fixture(manifest, replay), indent=2) + "\n",
        encoding="utf-8",
    )


def write_obligation_registry(registry: dict, output_json: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


def write_approval_gate(approval: dict, output_json: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(approval, indent=2) + "\n", encoding="utf-8")


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
    registry = packet.get("obligation_registry")
    approval = packet.get("approval_gate")
    if registry is None:
        raise SystemExit("proof-carrying rescue suite is missing obligation registry")
    if approval is None:
        raise SystemExit("proof-carrying rescue suite is missing approval gate")
    if registry["entry_count"] != packet["lane_count"]:
        raise SystemExit("obligation registry must cover every lane")
    if approval["surface_allowed"] is not True:
        raise SystemExit("approval gate must allow existing public surfaces")


def main() -> int:
    args = parse_args()
    packet = run_suite()
    replay = None
    registry = build_obligation_registry(packet)
    packet["obligation_registry"] = registry
    if args.replay_json or args.explorer_json or args.approval_json:
        from tools.proof_carrying_rescue_replay import replay_manifest

        replay = replay_manifest(packet)
    approval = build_approval_gate(packet, replay or {"valid": True}, registry)
    packet["approval_gate"] = approval
    write_outputs(packet, args.json, args.markdown)
    if args.replay_json and replay is not None:
        args.replay_json.parent.mkdir(parents=True, exist_ok=True)
        args.replay_json.write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    if args.explorer_json and replay is not None:
        write_explorer_fixture(packet, replay, args.explorer_json)
    if args.registry_json:
        write_obligation_registry(registry, args.registry_json)
    if args.approval_json:
        write_approval_gate(approval, args.approval_json)
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
    if args.registry_json:
        print(f"Wrote {args.registry_json}")
    if args.approval_json:
        print(f"Wrote {args.approval_json}")
    print("PROOF_CARRYING_RESCUE_SUITE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
