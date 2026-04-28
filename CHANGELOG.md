# Changelog

All notable changes to Monogate Forge will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.0.1] — 2026-04-28

### Added

- Initial repository scaffold
- Top-level documentation: `README.md`, `LICENSE` (MIT), `CONTRIBUTING.md`,
  `AGENT_FORGE.md`
- Full directory tree for all 10 sections (lang, software, hardware,
  industries, patents, roadmap, tools, data, docs, tests)
- Language specification skeleton at `lang/spec/SPEC.md`
- Standard library skeleton at `lang/spec/stdlib/STDLIB.md`
- Type system documentation at `lang/spec/types/TYPES.md`
- 10 example `.eml` files at `lang/spec/grammar/examples/` (placeholder)
- C runtime header at `software/runtime/c/libmonogate.h` (23 operators)
- Patent index at `patents/index.md` (17 filed + 5 pending)
- Per-industry README at each `industries/<vertical>/`
- Roadmap master at `roadmap/README.md` with phase + industry + business plans
- CLI entry point stub at `tools/cli/main.py`
- Canonical data files at `data/` (operators.json, tower_registry.json mirrored
  from `monogate-research/data/` and `exploration/E201_extended_atlas/`)

### Notes

This is the FOUNDATIONAL SCAFFOLD release. No backend produces working
output yet; the structure is ready for development to begin in any of the
phases listed in `roadmap/phases/`.
