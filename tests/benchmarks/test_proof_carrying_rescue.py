from tools.proof_carrying_rescue import RescueConfig, run_rescue_trace


SOURCE_PATH = "examples/proof_carrying_rescue.eml"


def test_proof_carrying_rescue_packet_has_witness():
    packet = run_rescue_trace(RescueConfig("positive_log_energy", [-2.0, -0.5, 0.0, 0.25, 1.25], 4.0, SOURCE_PATH))

    assert packet["schema_version"] == "forge.optimizer.proof_carrying_rescue.v1"
    assert packet["source_path"] == SOURCE_PATH
    assert packet["rescue_operator"] == "log_domain_lift"
    assert packet["expected_transition"] == "domain_wall->log_domain_rescue"
    assert packet["machlib_obligation"] == "PositiveCoordinateObligation"
    assert packet["has_transition_witness"] is True
    assert packet["rescued_event_count"] == 3
    assert packet["positive_coordinates_preserved"] is True
    assert packet["function_boundary_preserved"] is True


def test_proof_carrying_rescue_improves_finite_survival():
    packet = run_rescue_trace(RescueConfig("positive_log_energy", [-2.0, -0.5, 0.0, 0.25, 1.25], 4.0, SOURCE_PATH))

    assert packet["lifted_finite_count"] > packet["raw_finite_count"]
    assert packet["survival_delta"] > 0
    assert packet["boundaries"]["semantic_rewrite_claim"] is False
    assert packet["boundaries"]["optimizer_release_claim"] is False
    assert packet["boundaries"]["hardware_observed"] is False
