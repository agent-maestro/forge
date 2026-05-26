"""Log-domain optimizer analysis pass.

This pass promotes the high-dimensional Forge research packet into the real
optimizer pipeline as an opt-in branch. It does not rewrite user code yet:
log-domain parameterization changes the search coordinates used by Forge, not
the mathematical function signature. The pass marks candidate functions and can
export a deterministic trace packet for audit/replay surfaces.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any

from lang.parser.ast_nodes import ASTNode, EMLFunction, EMLModule, NodeKind


LOG_DOMAIN_SCHEMA = "forge.optimizer.log_domain_trace.v1"
LOG_DOMAIN_COORDINATE_SCHEMA = "forge.optimizer.log_domain_coordinate_plan.v1"


@dataclass(frozen=True)
class LogDomainCoordinatePlan:
    """Internal optimizer coordinate transform plan.

    `params` are unconstrained optimizer coordinates. `leaves` are positive
    EML terminal coordinates materialized by an exp map. This is an internal
    search-coordinate transform; it does not alter the user-facing function
    boundary.
    """

    schema_version: str
    parameter_count: int
    clamp: float
    params: list[float]
    leaves: list[float]
    min_leaf: float
    max_leaf: float
    positive_domain_preserved: bool
    function_boundary_preserved: bool

_TRANSCENDENTAL_KINDS = {
    NodeKind.EML,
    NodeKind.EXP,
    NodeKind.LN,
    NodeKind.POW,
    NodeKind.SQRT,
    NodeKind.TANH,
}


def analyze_log_domain_candidates(fn: EMLFunction) -> dict[str, Any]:
    """Return a small, stable candidate record for one function."""
    if fn.body is None:
        return {
            "function": fn.name,
            "candidate": False,
            "reason": "no_body",
            "transcendental_count": 0,
            "max_exp_ln_depth": 0,
            "parameter_count": len(fn.params),
        }
    count = _count_kinds(fn.body, _TRANSCENDENTAL_KINDS)
    depth = _max_depth_for_kinds(fn.body, {NodeKind.EXP, NodeKind.LN, NodeKind.EML})
    drift = (fn.profile or {}).get("fp16_drift_risk", "LOW")
    candidate = count >= 2 or depth >= 2 or drift == "HIGH"
    reason = "high_drift" if drift == "HIGH" else "nested_exp_log" if depth >= 2 else "multi_transcendental" if count >= 2 else "below_threshold"
    return {
        "function": fn.name,
        "candidate": candidate,
        "reason": reason,
        "transcendental_count": count,
        "max_exp_ln_depth": depth,
        "parameter_count": len(fn.params),
        "drift_risk": drift,
    }


def apply_log_domain_optimizer(fn: EMLFunction) -> tuple[EMLFunction, dict[str, Any]]:
    """Annotate one function with log-domain optimizer metadata."""
    out = deepcopy(fn)
    record = analyze_log_domain_candidates(out)
    out.profile = dict(out.profile or {})
    out.profile["log_domain_candidate"] = bool(record["candidate"])
    out.profile["log_domain_reason"] = record["reason"]
    out.profile["log_domain_transform"] = "analysis_only"
    if record["candidate"]:
        warnings = list(out.profile.get("stability_warnings", []))
        warnings.append(
            "Log-domain optimizer candidate: search coordinates may be "
            "parameterized through positive exp-mapped leaves."
        )
        out.profile["stability_warnings"] = warnings
    return out, record


def build_log_domain_coordinate_plan(params: list[float], *, clamp: float = 4.0) -> LogDomainCoordinatePlan:
    """Build a deterministic positive-coordinate plan for Forge search."""
    bounded = [max(min(float(x), clamp), -clamp) for x in params]
    leaves = [math.exp(x) for x in bounded]
    return LogDomainCoordinatePlan(
        schema_version=LOG_DOMAIN_COORDINATE_SCHEMA,
        parameter_count=len(params),
        clamp=clamp,
        params=bounded,
        leaves=leaves,
        min_leaf=min(leaves) if leaves else math.nan,
        max_leaf=max(leaves) if leaves else math.nan,
        positive_domain_preserved=all(x > 0 for x in leaves),
        function_boundary_preserved=True,
    )


def coordinate_plan_packet(params: list[float], *, clamp: float = 4.0) -> dict[str, Any]:
    """Return a JSON-serializable coordinate plan packet."""
    return asdict(build_log_domain_coordinate_plan(params, clamp=clamp))


def apply_log_domain_optimizer_module(mod: EMLModule) -> tuple[EMLModule, dict[str, Any]]:
    """Apply log-domain analysis to every function and return a trace."""
    out = deepcopy(mod)
    records = []
    functions = []
    for fn in out.functions:
        next_fn, record = apply_log_domain_optimizer(fn)
        functions.append(next_fn)
        records.append(record)
    out.functions = functions
    packet = {
        "schema_version": LOG_DOMAIN_SCHEMA,
        "mode": "analysis_only",
        "function_count": len(records),
        "candidate_count": sum(1 for row in records if row["candidate"]),
        "functions": records,
        "boundaries": {
            "semantic_rewrite_claim": False,
            "optimizer_release_claim": False,
            "function_boundary_preserved": True,
            "trace_export": True,
        },
    }
    return out, packet


def write_log_domain_trace(packet: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")


def _count_kinds(node: ASTNode, kinds: set[NodeKind]) -> int:
    return (1 if node.kind in kinds else 0) + sum(_count_kinds(child, kinds) for child in node.children)


def _max_depth_for_kinds(node: ASTNode, kinds: set[NodeKind]) -> int:
    child_depth = max((_max_depth_for_kinds(child, kinds) for child in node.children), default=0)
    return child_depth + 1 if node.kind in kinds else child_depth
