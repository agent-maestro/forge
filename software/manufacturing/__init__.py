"""Manufacturing-bridge tools.

Phase E3 of the math-to-manufactured-PCB pipeline. Takes a parsed
EML circuit module (already used by the SPICE + KiCad backends)
and produces the artifacts a board-house needs to actually
manufacture and assemble the design.

Today: JLCPCB.

  * :mod:`software.manufacturing.jlcpcb_mapper` -- match
    @spice_<component> declarations against a curated LCSC part
    registry, emit BOM + CPL + manifest CSVs.

Future: PCBWay, OSH Park, custom houses. The interface stays
the same; only the part-registry data changes per house.
"""

from __future__ import annotations

from software.manufacturing.jlcpcb_mapper import (
    JLCPCBMapper,
    MapResult,
    PartMatch,
    BundleArtifacts,
    PartRegistryEntry,
    UnmatchedComponent,
    CompileError,
)

__all__ = [
    "JLCPCBMapper",
    "MapResult",
    "PartMatch",
    "BundleArtifacts",
    "PartRegistryEntry",
    "UnmatchedComponent",
    "CompileError",
]
