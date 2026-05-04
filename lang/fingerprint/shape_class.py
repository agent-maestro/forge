"""C-237 shape-class lookup — the genome-class slot of the
computation fingerprint.

Background: session C-237 (monogate-research/exploration/
C237_eml_complexity_genome) classified the bundled 576-row corpus
into 76 distinct shape classes based on the cost-class string the
profiler emits (``p<chain_order>-d<eml_depth>-w<width>-c<composite>``).
That bucketing is the published "76 shape classes" referenced in the
Verification Network spec.

This module pins the canonical ordering — frequency-descending across
the C-237 corpus, with ties broken by lexicographic order — and
exposes a single ``classify`` function that maps a profile dict to
either a 0..75 ID or ``None`` if the profile's cost class is novel.

Schema-version contract: the file ``shape_classes_v1.json`` IS the
spec. Adding a new class would require ``shape_classes_v2.json`` and
a bump of the fingerprint document version, since the IDs would no
longer round-trip across versions.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Mapping, Optional


@lru_cache(maxsize=1)
def _canonical_index() -> tuple[Mapping[str, int], tuple[str, ...]]:
    """Load the v1 canonical class list. Cached so we read the JSON once."""
    raw = files(__package__).joinpath("shape_classes_v1.json").read_text(
        encoding="utf-8"
    )
    classes = tuple(json.loads(raw))
    if len(classes) != 76:
        raise RuntimeError(
            f"shape_classes_v1.json must hold exactly 76 entries, "
            f"got {len(classes)}"
        )
    by_name = {name: i for i, name in enumerate(classes)}
    return by_name, classes


def classify(profile: Optional[dict]) -> Optional[int]:
    """Return the C-237 shape-class ID for the given profile, or
    ``None`` if the profile has no recognisable cost class.

    The profile's ``cost_class`` field is the canonical key — Forge's
    profiler emits it as ``p<r>-d<depth>-w<width>-c<composite>``.
    Unknown classes (out-of-corpus expressions) return ``None``
    rather than guessing — the slot is honest about its coverage.
    """
    if not profile:
        return None
    cc = profile.get("cost_class")
    if not isinstance(cc, str):
        return None
    by_name, _ = _canonical_index()
    return by_name.get(cc)


def class_name(shape_class_id: int) -> Optional[str]:
    """Reverse lookup: ID → cost-class string. Useful for renderers
    and human-readable diagnostics."""
    _, classes = _canonical_index()
    if 0 <= shape_class_id < len(classes):
        return classes[shape_class_id]
    return None


def coverage_of(profiles) -> dict:
    """Diagnostic: how many of the supplied profiles map to a known
    class. Returns counts of ``known``, ``unknown_with_cost_class``,
    and ``no_cost_class``."""
    by_name, _ = _canonical_index()
    known = unknown = missing = 0
    for p in profiles:
        cc = (p or {}).get("cost_class") if p else None
        if not isinstance(cc, str):
            missing += 1
        elif cc in by_name:
            known += 1
        else:
            unknown += 1
    return {
        "known": known,
        "unknown_with_cost_class": unknown,
        "no_cost_class": missing,
    }
