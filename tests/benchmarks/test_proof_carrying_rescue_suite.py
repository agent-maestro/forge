from tools.proof_carrying_rescue_replay import replay_manifest
from tools.proof_carrying_rescue_suite import build_approval_gate, build_obligation_registry, run_suite


def test_proof_carrying_rescue_suite_v0_is_complete():
    packet = run_suite()

    assert packet["schema_version"] == "forge.optimizer.proof_carrying_rescue_suite.v0"
    assert packet["lane_count"] == 4
    assert packet["complete_v0"] is True
    assert {lane["rescue_operator"] for lane in packet["lanes"]} == {
        "log_domain_lift",
        "guard_clamp",
        "precision_escape",
        "saturation_deshelf",
    }
    assert {lane["expected_transition"] for lane in packet["lanes"]} == {
        "domain_wall->log_domain_rescue",
        "overflow_wall->guard_rescue",
        "phantom_attractor->interior_sample",
        "saturation_shelf->corner_concentration",
    }
    assert packet["boundaries"]["semantic_rewrite_claim"] is False
    assert packet["boundaries"]["hardware_observed"] is False


def test_rescue_obligation_registry_marks_second_concrete_witness():
    packet = run_suite()
    registry = build_obligation_registry(packet)
    by_operator = {entry["rescue_operator"]: entry for entry in registry["entries"]}

    assert by_operator["log_domain_lift"]["status"]["proven"] is True
    assert by_operator["guard_clamp"]["status"]["proven"] is True
    assert by_operator["guard_clamp"]["machlib_witness"]["theorem"] == (
        "guard_clamp_output_safety_witness_discharges_concrete_obligation"
    )
    assert by_operator["saturation_deshelf"]["status"]["proven"] is True
    assert by_operator["saturation_deshelf"]["machlib_witness"]["theorem"] == (
        "saturation_deshelf_clamp_witness_discharges_concrete_obligation"
    )
    assert by_operator["precision_escape"]["status"]["proven"] is False


def test_rescue_approval_gate_requires_electronics_evidence_grammar():
    packet = run_suite()
    registry = build_obligation_registry(packet)
    packet["obligation_registry"] = registry
    replay = replay_manifest(packet)
    approval = build_approval_gate(packet, replay, registry)

    assert approval["decision"] == "approved_for_existing_public_surfaces"
    assert approval["surface_allowed"] is True
    assert approval["deploy_allowed"] is True
    assert approval["electronics_boundary"]["hardware_action_allowed"] is False
    assert approval["electronics_boundary"]["future_physical_packets_must_use_evidence_grammar"] is True
