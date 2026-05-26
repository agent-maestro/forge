from tools.proof_carrying_rescue_suite import run_suite


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
