"""Tests for the opt-in log-domain optimizer branch."""

from __future__ import annotations

import json

from lang.optimizer import optimize_module
from lang.optimizer.log_domain import (
    LOG_DOMAIN_COORDINATE_SCHEMA,
    LOG_DOMAIN_SCHEMA,
    analyze_log_domain_candidates,
    apply_log_domain_optimizer_module,
    coordinate_plan_packet,
)
from lang.parser import parse_source
from lang.profiler import Profiler


def _module():
    src = """module t;
fn candidate(x: f64) -> f64 {
    ln(1.0 + exp(x))
}

fn plain(x: f64) -> f64 {
    x + 1.0
}
"""
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    return mod


def test_log_domain_candidate_analysis_detects_nested_exp_log():
    mod = _module()
    record = analyze_log_domain_candidates(mod.functions[0])

    assert record["candidate"] is True
    assert record["reason"] == "nested_exp_log"
    assert record["max_exp_ln_depth"] >= 2


def test_log_domain_module_pass_annotates_profiles_without_rewriting():
    mod = _module()
    before = mod.functions[0].body
    out, packet = apply_log_domain_optimizer_module(mod)

    assert packet["schema_version"] == LOG_DOMAIN_SCHEMA
    assert packet["candidate_count"] == 1
    assert out.functions[0].profile["log_domain_candidate"] is True
    assert out.functions[0].profile["log_domain_transform"] == "analysis_only"
    assert out.functions[0].body is not before
    assert out.functions[0].body.kind == before.kind
    assert out.functions[1].profile["log_domain_candidate"] is False


def test_optimize_module_log_domain_flag_writes_trace(tmp_path):
    trace_path = tmp_path / "trace.json"
    out = optimize_module(_module(), log_domain=True, optimizer_trace_path=str(trace_path))
    packet = json.loads(trace_path.read_text(encoding="utf-8"))

    assert trace_path.exists()
    assert packet["schema_version"] == LOG_DOMAIN_SCHEMA
    assert packet["boundaries"]["semantic_rewrite_claim"] is False
    assert out.functions[0].profile["log_domain_candidate"] is True


def test_optimize_module_default_leaves_log_domain_off(tmp_path):
    trace_path = tmp_path / "trace.json"
    out = optimize_module(_module(), optimizer_trace_path=str(trace_path))

    assert not trace_path.exists()
    assert "log_domain_candidate" not in (out.functions[0].profile or {})


def test_coordinate_plan_materializes_positive_leaves_and_preserves_boundary():
    packet = coordinate_plan_packet([-100.0, 0.0, 100.0], clamp=2.0)

    assert packet["schema_version"] == LOG_DOMAIN_COORDINATE_SCHEMA
    assert packet["params"] == [-2.0, 0.0, 2.0]
    assert packet["positive_domain_preserved"] is True
    assert packet["function_boundary_preserved"] is True
    assert all(value > 0 for value in packet["leaves"])
