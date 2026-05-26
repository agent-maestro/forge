from tools.precision_escape_rescue import PrecisionEscapeConfig, run_precision_escape_trace


SOURCE_PATH = "examples/precision_escape_rescue.eml"


def test_precision_escape_rescue_packet_has_witness():
    packet = run_precision_escape_trace(
        PrecisionEscapeConfig("quantized_basin", [0.25, 0.5, 0.75], 0.375, 0.25, 0.01, 0.5, SOURCE_PATH)
    )

    assert packet["schema_version"] == "forge.optimizer.precision_escape_rescue.v1"
    assert packet["source_path"] == SOURCE_PATH
    assert packet["rescue_operator"] == "precision_escape"
    assert packet["expected_transition"] == "phantom_attractor->interior_sample"
    assert packet["machlib_obligation"] == "PrecisionSensitivityObligation"
    assert packet["has_transition_witness"] is True
    assert packet["phantom_event_count"] >= 2
    assert packet["rescued_event_count"] >= 2
    assert packet["precision"]["finite_trace_preserved"] is True
    assert packet["precision"]["precision_sensitivity_witnessed"] is True


def test_precision_escape_rescue_does_not_claim_true_optimum():
    packet = run_precision_escape_trace(
        PrecisionEscapeConfig("quantized_basin", [0.25, 0.5, 0.75], 0.375, 0.25, 0.01, 0.5, SOURCE_PATH)
    )

    assert packet["boundaries"]["true_local_optimum_claim"] is False
    assert packet["boundaries"]["semantic_rewrite_claim"] is False
    assert packet["boundaries"]["optimizer_release_claim"] is False
    assert packet["boundaries"]["hardware_observed"] is False
    assert any(frame["raw"]["escape_improved"] for frame in packet["frames"])
