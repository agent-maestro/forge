"""Forge benchmark dashboard generator.

Reads `tools/benchmarks/{vertical,stdlib}_baseline.json` and emits
a markdown report tabulating per-function metrics, per-module
rollups, and worst-case rankings.

CLI: `python -m tools.benchmarks.dashboard > report.md`

The output is deterministic (sorted) so it lives in version
control without diffs from line-ordering churn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VERT_BASE = REPO_ROOT / "tools" / "benchmarks" / "vertical_baseline.json"
STD_BASE = REPO_ROOT / "tools" / "benchmarks" / "stdlib_baseline.json"


def render_dashboard(
    vertical: dict | None = None,
    stdlib: dict | None = None,
) -> str:
    """Return the full markdown report."""
    if vertical is None:
        vertical = _load(VERT_BASE)
    if stdlib is None:
        stdlib = _load(STD_BASE)

    parts: list[str] = []
    parts.append("# Forge benchmark dashboard")
    parts.append("")
    parts.append(_overview(vertical, stdlib))
    parts.append("")
    parts.append(_per_module_table("Verticals", vertical))
    parts.append("")
    parts.append(_per_module_table("Stdlib", stdlib))
    parts.append("")
    parts.append(_top_n("Highest chain order (verticals)",
                        vertical, key="chain_order", n=5))
    parts.append("")
    parts.append(_top_n("Highest FPGA cycles (verticals)",
                        vertical, key="fpga_cycles", n=5))
    parts.append("")
    parts.append(_top_n("Highest node count (verticals)",
                        vertical, key="node_count", n=5))
    return "\n".join(parts) + "\n"


# ── Sections ─────────────────────────────────────────────────


def _overview(vertical: dict, stdlib: dict) -> str:
    lines = ["## Overview"]
    n_v = len(vertical)
    n_s = len(stdlib)
    v_modules = len({k.split("::")[0] for k in vertical})
    s_modules = len({k.split("::")[0] for k in stdlib})
    lines.append("")
    lines.append(f"- Verticals: **{n_v}** functions across "
                 f"**{v_modules}** modules")
    lines.append(f"- Stdlib:    **{n_s}** functions across "
                 f"**{s_modules}** modules")
    if vertical:
        max_chain = max(v["chain_order"] for v in vertical.values())
        max_cycles = max(v["fpga_cycles"] for v in vertical.values())
        max_nodes = max(v["node_count"] for v in vertical.values())
        lines.append(
            f"- Vertical worst-case: chain={max_chain}, "
            f"cycles={max_cycles}, nodes={max_nodes}"
        )
    if stdlib:
        max_chain_s = max(v["chain_order"] for v in stdlib.values())
        max_cycles_s = max(v["fpga_cycles"] for v in stdlib.values())
        lines.append(
            f"- Stdlib worst-case:   chain={max_chain_s}, "
            f"cycles={max_cycles_s}"
        )
    return "\n".join(lines)


def _per_module_table(title: str, snap: dict) -> str:
    """Group entries by module prefix, render a markdown table."""
    if not snap:
        return f"## {title}\n\n(no entries)"
    by_mod: dict[str, list[tuple[str, dict]]] = {}
    for full_name, metrics in snap.items():
        mod, _, fn = full_name.partition("::")
        by_mod.setdefault(mod, []).append((fn, metrics))

    lines = [f"## {title}", ""]
    lines.append(
        "| Module | Function | Chain | Nodes | Cycles | "
        "MAC | Trig |"
    )
    lines.append(
        "|--------|----------|------:|------:|-------:|"
        "----:|-----:|"
    )
    for mod in sorted(by_mod):
        for fn, m in sorted(by_mod[mod]):
            lines.append(
                f"| `{mod}` | `{fn}` | {m['chain_order']} | "
                f"{m['node_count']} | {m['fpga_cycles']} | "
                f"{m['mac_units']} | {m['trig_units']} |"
            )
    return "\n".join(lines)


def _top_n(title: str, snap: dict, *, key: str, n: int) -> str:
    """Top-N ranking by a metric."""
    if not snap:
        return f"## {title}\n\n(no entries)"
    ranked = sorted(
        snap.items(),
        key=lambda kv: (-kv[1][key], kv[0]),
    )[:n]
    lines = [f"## {title}", ""]
    lines.append(f"| Function | {key} |")
    lines.append("|----------|------:|")
    for full_name, metrics in ranked:
        lines.append(f"| `{full_name}` | {metrics[key]} |")
    return "\n".join(lines)


# ── IO ───────────────────────────────────────────────────────


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """CLI entry: print the dashboard to stdout."""
    sys.stdout.write(render_dashboard())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
