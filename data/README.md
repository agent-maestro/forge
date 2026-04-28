# Data — Canonical Numbers and Definitions

Source-of-truth for all volatile numbers Forge depends on.
Mirrors the governance pattern from
`monogate-research/data/README.md`.

## Files

| File | What it holds | Mirror of |
|------|---------------|-----------|
| `status.md` | Headline numbers (one source of truth) | `monogate-research/data/status.md` |
| `operators.json` | 23-operator family definitions | `monogate-research/data/operators.json` (TBD when canonicalized upstream) |
| `superbest.json` | SuperBEST routing table | `monogate-research/data/superbest.md` (extracted) |
| `tower_registry.json` | 10 Pfaffian tower definitions | `monogate-research/exploration/E201_extended_atlas/independence_table.json` |
| `corpus_profiles.json` | 578-expression Pfaffian profiles | `monogate-research/exploration/E196_algorithmic_corpus/master_corpus_578.csv` (transformed) |
| `audit_log.md` | Append-only correction log | (Forge-local) |
| `save_points.json` | SHA256 verification hashes | `monogate-research/data/save_points.json` (filtered to Forge keys) |

## Update protocol

When upstream changes:
1. Run `python tools/audit/audit.py sync-data` (when implemented)
2. Diff the output; commit with a CHANGELOG entry referencing the
   upstream commit
3. Bump any test that asserts a moved number

## Volatile vs decision keys

Same convention as `monogate-research`:
- VOLATILE keys (corpus row count, Lean theorem count, etc.)
  are auto-derived from sources at audit time
- DECISION keys (canonical headline numbers like the 23-operator
  count, the 10-tower count) are user-curated and only change with
  an audit log entry
