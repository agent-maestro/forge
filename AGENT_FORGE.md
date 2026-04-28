# Agent Role: Monogate Forge

> **For Claude Code sessions working in `D:/monogate-forge/`.**
> Read this before any non-trivial change.

---

## Repo identity

- **Repo:** `monogate-forge` (planned at github.com/agent-maestro/monogate-forge)
- **Purpose:** language + compiler for verified math computation,
  targeting both software and hardware from one source
- **License:** MIT compiler, patents cover specific methods
- **Status:** SCAFFOLD (v0.0.1) — most modules awaiting development

## Cross-repo dependencies

This repo is part of the broader Monogate stack:

| Upstream repo | What it provides |
|---------------|------------------|
| `D:/monogate-research/` | Canonical data (`data/`), tower census, the conjecture swarm, the structured + auto memory, and the eml-cost analyzer's source-of-truth corpus |
| `D:/eml-cost-pkg-public/` | The Pfaffian cost analyzer that powers `lang/profiler/` |
| `D:/monogate-lean/` | The Lean 4 formalization that backs `software/verification/lean/` |
| `D:/monogate/` | The public site (monogate.org) — read-only from this repo |

When `monogate-forge`'s `data/` mirrors a file from `monogate-research/data/`,
the latter is canonical. Re-mirror via `tools/audit/audit.py sync-data`
(when implemented).

## Standing rules

1. **Compiler never silently loses precision.** Backends MUST emit
   the same numerical answer as the reference (within declared tol).
2. **Chain-order types are enforced, not advisory.** Type-checker
   rejects expressions whose chain order exceeds declared bounds.
3. **No industry-specific code in the core compiler.**
   `industries/` provides LIBRARIES, not compiler modifications.
4. **Hardware modules are tested against software reference.** Every
   `hardware/modules/` entry has a `tests/integration/` test
   comparing it to the matching `software/` path.
5. **Patents are referenced by number in code comments** when the
   code implements a patented method.

## Where to put new things

| Kind of change | Location |
|----------------|----------|
| Grammar / language feature | `lang/spec/` (canonical), `lang/parser/` (impl) |
| New software target | `software/backends/<target>.py` + `software/runtime/<target>/` |
| New hardware module | `hardware/modules/<category>/<name>.v` + tests |
| New FPGA target board | `hardware/targets/<vendor>/<board>.py` + `<board>.xdc/sdc` |
| Industry application | `industries/<vertical>/<category>/<app>.eml` |
| Certification guide | `industries/<vertical>/certification/<STANDARD>.md` |
| New patent filing | `patents/pending/<NN>_<slug>/README.md` + index update |
| Roadmap update | `roadmap/{phases,industries,business}/<name>.md` |
| Canonical number | `data/<file>.{md,json}` + audit log entry |

## When NOT to write code

- Don't implement features ahead of the roadmap. If `roadmap/phases/`
  doesn't list the phase, the spec hasn't been finalized.
- Don't add backends without a corresponding test plan.
- Don't add industry verticals without a certification target.
- Don't write hardware modules without a software reference test.

## Cross-references back to monogate-research

Findings, lessons, and project state about Monogate Forge that
might be useful to future sessions get saved as memory entries
in `~/.claude/projects/D--monogate/memory/` with the prefix
`forge_<YYYY_MM_DD>.md` (the auto-memory curator picks them up
under the `forge` tag — add to TAG_INFERENCE in `curator.py`
if not already there).

The priority-projects index in
`monogate-research/priority-projects/INDEX.md` lists this repo
as priority project #1; update its status field as the project
moves through scaffold → MVP → v1.0.

## Quick orientation each session

```bash
cd D:/monogate-forge

# What state is the repo in?
git status
git log --oneline -10
cat CHANGELOG.md | head -30

# What's currently planned?
ls roadmap/phases/
cat roadmap/README.md

# What's the language spec say today?
cat lang/spec/SPEC.md | head -50
```
