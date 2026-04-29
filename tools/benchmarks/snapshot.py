"""Snapshot generator + diff for vertical benchmarks.

A snapshot is a dict keyed by `<module>::<fn_name>` whose values
are the metrics we care about regressing on:

  - chain_order:   the profiler's inferred chain order
  - node_count:    AST node count after the full optimizer pass
  - fpga_cycles:   FPGA estimated latency (cycles) from the profiler
  - mac_units:     FPGA mac unit count
  - trig_units:    FPGA trig unit count

Locally-defined functions only -- imported stdlib functions get
their own snapshots if you generate from the stdlib files.

Persistence: snapshots serialize to JSON via `to_json` /
`from_json`. Tests load a baseline and assert the current run's
metrics never regress.
"""

from __future__ import annotations

import json
from pathlib import Path

from lang.optimizer import optimize_module
from lang.parser.ast_nodes import ASTNode, EMLModule, NodeKind
from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler


# Per-function metric record.
def _node_count(node: ASTNode) -> int:
    return 1 + sum(_node_count(c) for c in node.children)


def snapshot_module(mod: EMLModule) -> dict:
    """Return a {fn_qualified_name: metrics} dict for every LOCAL
    function in `mod` after running the full optimizer."""
    Profiler().profile_module(mod)
    opt = optimize_module(mod)

    out: dict = {}
    module_name = mod.name or "(unnamed)"
    for fn in opt.functions:
        if fn.imported_from is not None:
            continue
        prof = fn.profile or {}
        body = fn.body
        out[f"{module_name}::{fn.name}"] = {
            "chain_order": _to_int(prof.get("chain_order", 0)),
            "node_count":  _node_count(body) if body else 0,
            "fpga_cycles": _to_int(
                (prof.get("fpga_estimate") or {})
                .get("estimated_latency_cycles", 0),
            ),
            "mac_units":   _to_int(
                (prof.get("fpga_estimate") or {}).get("mac_units", 0),
            ),
            "trig_units":  _to_int(
                (prof.get("fpga_estimate") or {}).get("trig_units", 0),
            ),
        }
    return out


def snapshot_path(path: str | Path) -> dict:
    return snapshot_module(parse_file(path))


def to_json(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


def from_json(text: str) -> dict:
    return json.loads(text)


def load_baseline(path: str | Path) -> dict:
    return from_json(Path(path).read_text(encoding="utf-8"))


def diff_against(baseline: dict, current: dict) -> list[str]:
    """Return one finding per regressing metric. Empty list means
    `current` is at least as good as `baseline` on every entry.

    Rules per metric:
      - chain_order : strictly equal (any change is a regression)
      - node_count  : current must be <= baseline (more nodes = bad)
      - fpga_cycles : current must be <= baseline
      - mac_units   : current must be <= baseline
      - trig_units  : current must be <= baseline

    Brand-new functions (in `current` but not `baseline`) and
    deleted functions (in `baseline` but not `current`) are
    surfaced as informational findings -- the operator decides
    whether to fold them into the baseline."""
    findings: list[str] = []

    cur_keys = set(current)
    base_keys = set(baseline)

    for added in sorted(cur_keys - base_keys):
        findings.append(
            f"NEW {added}: not yet in baseline -- update snapshot "
            f"to include it"
        )
    for removed in sorted(base_keys - cur_keys):
        findings.append(
            f"DELETED {removed}: in baseline but absent from current"
        )

    for name in sorted(cur_keys & base_keys):
        b = baseline[name]
        c = current[name]
        # chain_order strict equality
        if c["chain_order"] != b["chain_order"]:
            findings.append(
                f"REGRESS {name}: chain_order "
                f"{b['chain_order']} -> {c['chain_order']}"
            )
        # monotone-down metrics
        for metric in ("node_count", "fpga_cycles",
                       "mac_units", "trig_units"):
            if c[metric] > b[metric]:
                findings.append(
                    f"REGRESS {name}: {metric} "
                    f"{b[metric]} -> {c[metric]}"
                )
    return findings


def _to_int(v) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    return 0
