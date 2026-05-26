from tools.boundary_optimizer_benchmark import (
    BoundaryRunConfig,
    benchmark,
    build_transition_counts,
    classify_boundary_event,
    compose_transition,
    compose_transition_path,
    dominant_transition,
    intervention_benchmark,
    is_rescue_normal_event,
    is_rescue_transition,
    run_boundary_experiment,
    run_intervention_pair,
    transition_entropy,
)


def test_boundary_run_packet_matches_course_contract():
    packet = run_boundary_experiment(
        BoundaryRunConfig(
            dimension=32,
            tree_depth=8,
            sample_count=256,
            mode="guarded",
            seed=1701,
        )
    )

    assert packet["schema_version"] == "monogate-electronics.boundary-run.v0"
    assert packet["course"] == "006-ee-math-kernels"
    assert packet["simulated"] is True
    assert packet["hardware_observed"] is False
    assert packet["boundary_flags"]["live_serial_capture_performed"] is False
    assert packet["boundary_hits"] > packet["center_hits"]
    assert packet["event_counts"]["corner_concentration"] + packet["event_counts"]["guard_rescue"] > 0
    assert packet["transition_counts"]
    assert packet["transition_entropy"] >= 0
    assert "->" in packet["dominant_transition"]
    assert packet["trace_preview"][0]["event_class"]


def test_log_domain_survival_is_not_worse_than_raw_for_same_benchmark_seed():
    packet = benchmark([64], ["raw", "log-domain candidate"], 512, 8, 1701)
    by_mode = {run["mode"]: run for run in packet["runs"]}

    assert packet["schema_version"] == "forge.optimizer.boundary_run_benchmark.v1"
    assert by_mode["log-domain candidate"]["finite_survival_rate"] >= by_mode["raw"]["finite_survival_rate"]
    assert by_mode["log-domain candidate"]["event_counts"]["log_domain_rescue"] > 0
    assert packet["boundaries"]["optimizer_release_claim"] is False


def test_boundary_classifier_priority():
    assert classify_boundary_event(
        mode="raw",
        boundary_hit=True,
        center_hit=False,
        domain_failure=True,
        saturation_event=True,
        raw_would_fail=True,
        pressure=4.9,
    ) == "overflow_wall"
    assert classify_boundary_event(
        mode="guarded",
        boundary_hit=True,
        center_hit=False,
        domain_failure=False,
        saturation_event=False,
        raw_would_fail=True,
        pressure=4.9,
    ) == "guard_rescue"


def test_transition_graph_helpers():
    frames = [
        {"event_class": "interior_sample"},
        {"event_class": "corner_concentration"},
        {"event_class": "overflow_wall"},
        {"event_class": "guard_rescue"},
        {"event_class": "guard_rescue"},
    ]
    transitions = build_transition_counts(frames)

    assert transitions["interior_sample->corner_concentration"] == 1
    assert transitions["guard_rescue->guard_rescue"] == 1
    assert transition_entropy(transitions) > 0
    assert dominant_transition(transitions) is not None


def test_boundary_calculus_composes_matching_paths():
    assert (
        compose_transition("domain_wall->log_domain_rescue", "log_domain_rescue->interior_sample")
        == "domain_wall->interior_sample"
    )
    assert compose_transition("domain_wall->log_domain_rescue", "guard_rescue->interior_sample") is None
    assert (
        compose_transition_path(
            [
                "domain_wall->log_domain_rescue",
                "log_domain_rescue->corner_concentration",
                "corner_concentration->interior_sample",
            ]
        )
        == "domain_wall->interior_sample"
    )


def test_boundary_calculus_names_rescue_normal_events():
    assert is_rescue_normal_event("interior_sample") is True
    assert is_rescue_normal_event("guard_rescue") is True
    assert is_rescue_normal_event("domain_wall") is False
    assert is_rescue_transition("overflow_wall->guard_rescue") is True
    assert is_rescue_transition("saturation_shelf->corner_concentration") is False


def test_intervention_pair_emits_rescue_contract():
    pair = run_intervention_pair(64, 512, 8, 1701, "log_domain_lift")

    assert pair["intervention"] == "log_domain_lift"
    assert pair["expected_transition"] == "domain_wall->log_domain_rescue"
    assert pair["obligation"] == "positive_coordinate_preservation"
    assert pair["finite_survival_delta"] >= 0
    assert pair["intervention_claim"] == "simulated_pairwise_benchmark"


def test_intervention_benchmark_covers_all_rescue_operators():
    packet = intervention_benchmark([16], 256, 8, 1701)
    interventions = {pair["intervention"] for pair in packet["pairs"]}

    assert packet["schema_version"] == "forge.optimizer.boundary_intervention_benchmark.v1"
    assert interventions == {"log_domain_lift", "guard_clamp", "precision_escape", "saturation_deshelf"}
    assert packet["boundaries"]["optimizer_release_claim"] is False
