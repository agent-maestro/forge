from tools.proof_carrying_rescue_replay import replay_manifest
from tools.proof_carrying_rescue_suite import run_suite


def test_proof_carrying_rescue_replay_accepts_suite_manifest():
    packet = run_suite()
    from tools.proof_carrying_rescue_suite import build_obligation_registry

    packet["obligation_registry"] = build_obligation_registry(packet)
    result = replay_manifest(packet)

    assert result["schema_version"] == "forge.optimizer.proof_carrying_rescue_replay.v0"
    assert result["valid"] is True
    assert result["issue_count"] == 0
    assert result["operators"] == ["guard_clamp", "log_domain_lift", "precision_escape", "saturation_deshelf"]


def test_proof_carrying_rescue_replay_rejects_overclaim():
    packet = run_suite()
    from tools.proof_carrying_rescue_suite import build_obligation_registry

    packet["obligation_registry"] = build_obligation_registry(packet)
    packet["boundaries"]["hardware_observed"] = True
    result = replay_manifest(packet)

    assert result["valid"] is False
    assert result["issue_count"] == 1
    assert "hardware_observed" in result["issues"][0]


def test_proof_carrying_rescue_replay_rejects_missing_registry():
    result = replay_manifest(run_suite())

    assert result["valid"] is False
    assert "missing obligation registry" in result["issues"]
