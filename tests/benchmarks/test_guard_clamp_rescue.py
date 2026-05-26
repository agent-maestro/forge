from tools.guard_clamp_rescue import GuardClampConfig, run_guard_clamp_trace


SOURCE_PATH = "examples/guard_clamp_rescue.eml"


def test_guard_clamp_rescue_packet_has_witness():
    packet = run_guard_clamp_trace(GuardClampConfig("exp_pressure", [1.0, 4.0, 30.0, 710.0], 8.0, SOURCE_PATH))

    assert packet["schema_version"] == "forge.optimizer.guard_clamp_rescue.v1"
    assert packet["source_path"] == SOURCE_PATH
    assert packet["rescue_operator"] == "guard_clamp"
    assert packet["expected_transition"] == "overflow_wall->guard_rescue"
    assert packet["machlib_obligation"] == "OutputSafetyObligation"
    assert packet["has_transition_witness"] is True
    assert packet["rescued_event_count"] == 2
    assert packet["guard"]["output_safety_preserved"] is True
    assert packet["guard"]["function_boundary_preserved"] is True


def test_guard_clamp_rescue_improves_finite_survival():
    packet = run_guard_clamp_trace(GuardClampConfig("exp_pressure", [1.0, 4.0, 30.0, 710.0], 8.0, SOURCE_PATH))

    assert packet["guarded_finite_count"] > packet["raw_finite_count"]
    assert packet["survival_delta"] > 0
    assert packet["boundaries"]["semantic_rewrite_claim"] is False
    assert packet["boundaries"]["optimizer_release_claim"] is False
    assert packet["boundaries"]["hardware_observed"] is False
