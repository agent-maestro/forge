from tools.boundary_optimizer_benchmark import BoundaryRunConfig, benchmark, run_boundary_experiment


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


def test_log_domain_survival_is_not_worse_than_raw_for_same_benchmark_seed():
    packet = benchmark([64], ["raw", "log-domain candidate"], 512, 8, 1701)
    by_mode = {run["mode"]: run for run in packet["runs"]}

    assert packet["schema_version"] == "forge.optimizer.boundary_run_benchmark.v1"
    assert by_mode["log-domain candidate"]["finite_survival_rate"] >= by_mode["raw"]["finite_survival_rate"]
    assert packet["boundaries"]["optimizer_release_claim"] is False
