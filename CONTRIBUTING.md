# Contributing to Monogate Forge

Thanks for considering a contribution. Monogate Forge is the
language + compiler half of the broader Monogate stack; it
depends on `eml-cost`, `monogate-research`, and `monogate-lean`
upstream.

---

## Before you start

1. Read `AGENT_FORGE.md` for the rules Claude Code sessions follow
   in this repo. Same rules apply to humans.
2. Read `lang/spec/SPEC.md` for the language semantics. Backends
   MUST conform to the spec — diverging backends are bugs.
3. Check `patents/index.md` if your contribution touches an
   algorithmic method. Some methods are patented; the
   implementation is open but commercial re-implementations may
   need a license.
4. Verify the stack is current: `python tools/audit/audit.py`
   (when implemented).

---

## Standing rules (enforced by CI)

- **Compiler never silently loses precision.** Any change to a
  backend that reduces output precision must include either a
  matching tolerance bump in tests OR a precision-bound update
  with a Lean proof.
- **Chain-order types are enforced, not advisory.** A change that
  weakens type-checking needs sign-off + a roadmap entry
  documenting the tradeoff.
- **Hardware modules are tested against software reference.**
  Every hardware module under `hardware/modules/` must have a
  matching test in `tests/integration/` that compares its output
  against the corresponding software path within tolerance.
- **No industry-specific code in the core compiler.**
  `industries/` provides LIBRARIES, not compiler modifications.
- **Patents are referenced by number in code comments.** When
  you touch code that implements a patented method, the comment
  must reference the patent number from `patents/index.md`.

---

## Pull request workflow

1. Fork + branch off `master`
2. Make focused changes — one concern per PR
3. Update `CHANGELOG.md` under the `Unreleased` section
4. Run `pytest tests/` and confirm all pass
5. For backend changes, also run the precision regression suite
6. Open the PR with a clear description of the WHY
7. CI runs build + test + (where relevant) FPGA simulation

---

## Adding a new industry vertical

1. Create `industries/<name>/` with the standard subdirs
   (`README.md`, application categories, `certification/`)
2. Add an entry to the file list table in `roadmap/industries/<name>.md`
3. Each `.eml` example MUST have a documented chain order + cost class
4. Certification guides go in `industries/<name>/certification/<STANDARD>.md`
5. Open an issue with the `industry_application.md` template attached

---

## Adding a new hardware target

1. Create `hardware/targets/<vendor>/<board>.py`
2. Add device constraints (LUT/DSP/BRAM counts, max frequency)
3. Add board-specific pin / timing constraint file (`.xdc` / `.sdc`)
4. Add a smoke test in `tests/integration/` that compiles
   `lang/spec/grammar/examples/pid_basic.eml` to your target
5. Document in `roadmap/phases/phase3_hardware.md`

---

## Reporting bugs

Use the `bug_report.md` issue template. Include:
- Compiler version (`eml-compile --version`)
- Platform (OS, Python version, target)
- Minimal `.eml` source that reproduces
- Expected vs actual output
- For backend bugs: the generated output (C / Verilog / etc.)

---

## License of contributions

By contributing, you agree your contribution is licensed under
the MIT license (see `LICENSE`). For algorithmic methods that
might be patentable, contributors should disclose any prior art
or pending applications they're aware of.
