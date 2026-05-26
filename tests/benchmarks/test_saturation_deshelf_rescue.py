from tools.saturation_deshelf_rescue import SaturationDeshelfConfig, run_saturation_deshelf_trace


SOURCE_PATH = "examples/saturation_deshelf_rescue.eml"


def test_saturation_deshelf_rescue_packet_has_witness():
    packet = run_saturation_deshelf_trace(
        SaturationDeshelfConfig("saturated_response", [-2.0, 0.0, 2.0, 4.0, 8.0], 0.0, 1.0, 3.0, SOURCE_PATH)
    )

    assert packet["schema_version"] == "forge.optimizer.saturation_deshelf_rescue.v1"
    assert packet["source_path"] == SOURCE_PATH
    assert packet["rescue_operator"] == "saturation_deshelf"
    assert packet["expected_transition"] == "saturation_shelf->corner_concentration"
    assert packet["machlib_obligation"] == "ClampInvariantObligation"
    assert packet["has_transition_witness"] is True
    assert packet["saturation_event_count"] >= 3
    assert packet["deshelved_event_count"] >= 2
    assert packet["deshelf"]["clamp_invariant_preserved"] is True
    assert packet["deshelf"]["measurable_boundary_structure_restored"] is True


def test_saturation_deshelf_rescue_does_not_claim_global_win():
    packet = run_saturation_deshelf_trace(
        SaturationDeshelfConfig("saturated_response", [-2.0, 0.0, 2.0, 4.0, 8.0], 0.0, 1.0, 3.0, SOURCE_PATH)
    )

    assert packet["boundaries"]["global_optimizer_win_claim"] is False
    assert packet["boundaries"]["semantic_rewrite_claim"] is False
    assert packet["boundaries"]["optimizer_release_claim"] is False
    assert packet["boundaries"]["hardware_observed"] is False
    assert all(frame["raw"]["finite"] for frame in packet["frames"])
