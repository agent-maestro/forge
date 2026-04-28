# Forge Audit Log

> Append-only log of corrections to canonical numbers. Same
> protocol as `monogate-research/data/audit_log.md`.

## 2026-04-28 -- Initial scaffold

- `data/operators.json` ships with 9 of 23 operators. Remaining
  14 to be added once the canonical list is locked upstream in
  `monogate-research/data/operators.json`.
- `data/tower_registry.json` mirrored from
  `monogate-research/exploration/E201_extended_atlas/independence_table.json`
  (10 towers including T_Lerch and T_Mathieu added 2026-04-27).
- `data/corpus_profiles.json` not yet generated. Will be a
  transformed view of `master_corpus_578.csv` once the schema
  for the consumer (the profiler) is finalized.
- `data/save_points.json` not yet generated. Pending the audit
  pipeline implementation in `tools/audit/`.
