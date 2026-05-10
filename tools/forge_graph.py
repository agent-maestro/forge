"""tools/forge_graph.py — structural queries over monogate-forge.

Standalone (no external deps; reads only files in this repo).
Five subcommands:

    status     buildout progress per major directory
    deps       compiler-stage dependency graph
    patents    map patents to directories; flag uncovered dirs
    industry   per-vertical readiness (file count + cert template?)
    chain FILE compilation chain trace for a .eml source
                (compiler-dependent — prints "not built yet" today)

Usage:

    python tools/forge_graph.py status
    python tools/forge_graph.py deps
    python tools/forge_graph.py patents
    python tools/forge_graph.py industry
    python tools/forge_graph.py chain lang/spec/grammar/examples/pid_basic.eml
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Reconfigure stdout/stderr to utf-8 so any Unicode in the scaffold
# (Lean ℂ ℝ → ∉, corpus labels) prints cleanly on Windows.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


REPO_ROOT = Path(__file__).resolve().parent.parent  # forge repo root


# ── Config: targets + classifications ─────────────────────────────────

# Per-section file-count targets from `lang/spec/EML_LANG_DESIGN.md`
# "File Count Summary" table.
EXPECTED_FILES: dict[str, int] = {
    "lang":       30,
    "software":   40,
    "hardware":   50,
    "industries": 80,
    "patents":    25,
    "roadmap":    15,
    "tools":      20,
    "data":       10,
    "docs":       15,
    "tests":      20,
}

# A file counts as "filled" when it's > FILLED_BYTES_THRESHOLD AND
# does NOT contain any of the SCAFFOLD_MARKERS strings. Stubs that
# exist but only carry placeholders count as "stub-only".
FILLED_BYTES_THRESHOLD = 500
SCAFFOLD_MARKERS = (
    "raise NotImplementedError",
    "SCAFFOLD",
    "todo!",
    "TODO: ",
    "PLACEHOLDER",
)

# File extensions we COUNT toward the totals. Avoids accidentally
# counting binary or vendor artifacts.
COUNTED_EXTS = frozenset({
    ".md", ".py", ".json", ".toml", ".lean", ".v", ".vh", ".vhd",
    ".sv", ".c", ".h", ".rs", ".ts", ".tsx", ".js", ".eml",
    ".g4", ".sdc", ".xdc", ".pc", ".sh", ".yml", ".yaml", "",
})

# Directories under which we never recurse for the file count.
SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".lake", "build",
    "dist", ".pytest_cache", ".mypy_cache", "target",
})


# ── Dep graph (static; sourced from EML_LANG_DESIGN.md sec 2-3) ───────

@dataclass(frozen=True)
class Stage:
    name: str
    path: str               # repo-relative dir
    deps: tuple[str, ...]   # upstream stage names
    external_deps: tuple[str, ...] = ()


COMPILER_STAGES: tuple[Stage, ...] = (
    Stage("parser", "lang/parser",
          deps=(),
          external_deps=("ANTLR4 grammar (lang/spec/grammar/eml_lang.g4)",)),
    Stage("profiler", "lang/profiler",
          deps=("parser",),
          external_deps=("eml-cost 0.19.0 (PyPI)",)),
    Stage("type_checker", "lang/parser/type_checker.py",
          deps=("profiler",)),
    Stage("optimizer", "lang/optimizer",
          deps=("type_checker",),
          external_deps=("SuperBEST table (data/superbest.json)",
                         "Patent #01 #02 #08 #12")),
    Stage("c_backend", "software/backends/c_backend.py",
          deps=("optimizer",),
          external_deps=("software/runtime/c/libmonogate.h",)),
    Stage("rust_backend", "software/backends/rust_backend.py",
          deps=("optimizer",),
          external_deps=("monogate-sys crate",)),
    Stage("python_backend", "software/backends/python_backend.py",
          deps=("optimizer",),
          external_deps=("eml-cost.transpile (Tool 5)",)),
    Stage("llvm_backend", "software/backends/llvm_backend.py",
          deps=("optimizer",),
          external_deps=("LLVM toolchain",)),
    Stage("wasm_backend", "software/backends/wasm_backend.py",
          deps=("llvm_backend",)),
    Stage("verilog_backend", "hardware/hdl_gen/verilog_backend.py",
          deps=("optimizer", "fpga_allocator"),
          external_deps=("hardware/modules/transcendental/cordic_*.v",)),
    Stage("vhdl_backend", "hardware/hdl_gen/vhdl_backend.py",
          deps=("optimizer", "fpga_allocator")),
    Stage("fpga_allocator", "hardware/allocator",
          deps=("profiler",),
          external_deps=("Patent #14 (FPGA resource allocator)",
                         "vendor target file (hardware/targets/<vendor>/<board>.py)")),
    Stage("lean_backend", "software/verification/lean/LeanBackend.py",
          deps=("type_checker",),
          external_deps=("monogate-lean (Tactics.lean: eml_auto)",)),
    Stage("smt_backend", "software/verification/smt",
          deps=("type_checker",),
          external_deps=("Z3 SMT solver",)),
    Stage("cbmc_backend", "software/verification/cbmc",
          deps=("c_backend",),
          external_deps=("CBMC bounded model checker",)),
)


# ── Patent → directory map (from EML_LANG_DESIGN.md "Patent Implications") ─

PATENT_MAP: dict[str, tuple[int, ...]] = {
    "lang/optimizer/superbest.py":       (1, 2, 8),
    "lang/optimizer/fusion.py":          (12,),
    "lang/profiler":                     (11, 15),
    "lang/parser/type_checker.py":       (21,),
    "hardware/allocator":                (14,),
    "industries/ml/quantization":        (20,),
    "software":                          (22,),    # cross-cutting
    "hardware":                          (22,),    # cross-cutting
    "industries/ml/activations":         (3,),
    "industries/ml/loss":                (13,),
}

# Subdirectories of these top-level sections we EXPECT to be covered
# by some patent; flag any that have no entry in PATENT_MAP.
PATENT_COVERAGE_SCOPE = (
    "lang/parser",
    "lang/profiler",
    "lang/optimizer",
    "software/backends",
    "software/verification",
    "hardware/allocator",
    "hardware/hdl_gen",
    "hardware/modules",
)


# ── File classification ──────────────────────────────────────────────

@dataclass(frozen=True)
class FileStat:
    path: Path
    bytes: int
    is_filled: bool
    is_stub: bool


def classify_file(path: Path) -> FileStat | None:
    """Return a FileStat or None if the file should not be counted."""
    if path.suffix not in COUNTED_EXTS:
        return None
    if any(part in SKIP_DIRS for part in path.parts):
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:
        return FileStat(path, 0, False, True)

    is_stub = False
    if size < FILLED_BYTES_THRESHOLD:
        is_stub = True
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if any(m in text for m in SCAFFOLD_MARKERS):
            is_stub = True

    return FileStat(path, size, not is_stub, is_stub)


def walk_section(section: str) -> list[FileStat]:
    """All counted files under one top-level section."""
    base = REPO_ROOT / section
    if not base.is_dir():
        return []
    out: list[FileStat] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        stat = classify_file(p)
        if stat is not None:
            out.append(stat)
    return out


# ── Subcommand: status ───────────────────────────────────────────────

def cmd_status() -> int:
    print()
    print("  Forge buildout progress (filled = >{}b AND no scaffold marker)"
          .format(FILLED_BYTES_THRESHOLD))
    print()

    section_w = max(len(s) for s in EXPECTED_FILES) + 1
    grand_filled = grand_total = 0

    for section, target in EXPECTED_FILES.items():
        files = walk_section(section)
        filled = sum(1 for f in files if f.is_filled)
        existing = len(files)
        pct = (filled / target * 100) if target else 0
        marker = ""
        if existing > target:
            marker = " (over-target on file count)"
        print(f"  {section.ljust(section_w)} {filled:>3d}/{target:<3d} "
              f"filled  ({pct:>3.0f}%)   "
              f"[{existing} files exist{marker}]")
        grand_filled += filled
        grand_total += target

    overall_pct = (grand_filled / grand_total * 100) if grand_total else 0
    print()
    print(f"  OVERALL: {grand_filled}/{grand_total} files filled "
          f"({overall_pct:.0f}%)")
    print()
    print("  Next priority: lang/parser/ (Phase 1.2 — see roadmap/phases/phase1_language.md)")
    return 0


# ── Subcommand: deps ─────────────────────────────────────────────────

def cmd_deps() -> int:
    print()
    print("  Compiler-stage dependency graph")
    print("  (deps must be implemented before the dependent stage)")
    print()
    for stage in COMPILER_STAGES:
        deps = ", ".join(stage.deps) if stage.deps else "(none — root stage)"
        path_exists = (REPO_ROOT / stage.path).exists()
        marker = "OK " if path_exists else "?? "
        print(f"  {marker}{stage.name:18s}  deps: {deps}")
        print(f"     path: {stage.path}")
        if stage.external_deps:
            for ext in stage.external_deps:
                print(f"     ext:  {ext}")
        print()

    print("  Reading bottom-up: parser is the root; everything else")
    print("  depends transitively on the (parsed + profiled +")
    print("  type-checked + optimized) AST.")
    return 0


# ── Subcommand: patents ──────────────────────────────────────────────

def cmd_patents() -> int:
    print()
    print("  Patent → directory map (from EML_LANG_DESIGN.md)")
    print()
    for path, patents in PATENT_MAP.items():
        marker = "" if (REPO_ROOT / path).exists() else "  (path missing!)"
        ids = ", ".join(f"#{p:02d}" for p in patents)
        print(f"  {path:40s} -> {ids}{marker}")
    print()

    # Check for uncovered directories.
    print("  Coverage gaps (directories in PATENT_COVERAGE_SCOPE")
    print("  that don't appear in PATENT_MAP):")
    print()
    covered = set(PATENT_MAP.keys())
    gaps: list[str] = []
    for scope in PATENT_COVERAGE_SCOPE:
        # A scope is "covered" if it OR any prefix path is in PATENT_MAP.
        is_covered = False
        for c in covered:
            if scope == c or scope.startswith(c + "/") or c.startswith(scope + "/"):
                is_covered = True
                break
        if not is_covered:
            gaps.append(scope)
    if not gaps:
        print("  OK every scope directory has at least one patent reference.")
    else:
        for g in gaps:
            print(f"  ?  {g}  (no patent in PATENT_MAP)")
        print()
        print(f"  {len(gaps)} directories have no patent coverage.")
    return 0


# ── Subcommand: industry ─────────────────────────────────────────────

VERTICAL_CERT = {
    "aerospace":     ("DO-178C",       "certification/DO_178C.md"),
    "automotive":    ("ISO 26262",     "certification/ISO_26262.md"),
    "robotics":      ("none standard", None),
    "manufacturing": ("ISO 9001",      "certification/ISO_9001.md"),
    "energy":        ("NRC / IEC 61508", "certification/NRC_compliance.md"),
    "medical":       ("IEC 62304 + FDA 510(k)", "certification/IEC_62304.md"),
    "defense":       ("MIL-STD-882",   "certification/MIL_STD_882.md"),
    "crypto":        ("FIPS 140-3 + CC EAL", "certification/FIPS_140_3.md"),
    "audio":         ("none",          None),
    "ml":            ("none",          None),
    "scientific":    ("none",          None),
}


def cmd_industry() -> int:
    print()
    print("  Per-vertical readiness")
    print()
    print(f"  {'vertical':<14s}{'files':>8s}  cert std                   tmpl?")
    print(f"  {'-'*14}{'-'*8}  {'-'*25}  -----")

    template_count = 0
    readme_only = 0

    for vertical, (cert_std, tmpl_path) in VERTICAL_CERT.items():
        base = REPO_ROOT / "industries" / vertical
        if not base.is_dir():
            print(f"  {vertical:<14s}    --   (directory missing)")
            continue
        files = walk_section(f"industries/{vertical}")
        n_files = len(files)
        # README-only if exactly 1 markdown file and it's README.md
        is_readme_only = (
            n_files == 1
            and files[0].path.name.lower() == "readme.md"
        )
        if is_readme_only:
            readme_only += 1
        # Cert template existence
        if tmpl_path is None:
            tmpl_marker = " n/a "
        elif (base / tmpl_path).exists():
            tmpl_marker = " YES "
            template_count += 1
        else:
            tmpl_marker = "  no "

        flag = " (README only)" if is_readme_only else ""
        print(f"  {vertical:<14s}{n_files:>5d}     {cert_std:<25s}  "
              f"{tmpl_marker}{flag}")

    print()
    print(f"  {template_count} verticals have certification templates")
    print(f"  {readme_only} verticals are README-only")
    return 0


# ── Subcommand: chain ────────────────────────────────────────────────

def cmd_chain(source_path: str) -> int:
    """Compilation chain trace for a .eml file. Compiler-dependent;
    today: print "not built yet" with a hint."""
    src = Path(source_path)
    if not src.is_absolute():
        src = REPO_ROOT / source_path
    print()
    print(f"  SOURCE: {src.relative_to(REPO_ROOT) if src.is_relative_to(REPO_ROOT) else src}")
    if not src.is_file():
        print(f"  ERROR: source file not found")
        return 1
    if src.suffix != ".eml":
        print(f"  WARN: not a .eml file (suffix={src.suffix})")

    # Show what we CAN compute today: file size, line count, function /
    # const count by simple regex.
    try:
        text = src.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"  ERROR: cannot read source: {e}")
        return 1
    n_lines = text.count("\n") + 1
    n_funcs = len(re.findall(r"(?m)^\s*fn\s+\w+", text))
    n_consts = len(re.findall(r"(?m)^\s*const\s+\w+", text))
    n_types = len(re.findall(r"(?m)^\s*type\s+\w+", text))
    n_verify = len(re.findall(r"@verify", text))
    n_target = len(re.findall(r"@target", text))

    print(f"  STATIC SCAN ({n_lines} lines):")
    print(f"    {n_funcs} fn declarations")
    print(f"    {n_consts} const declarations")
    print(f"    {n_types} type aliases")
    print(f"    {n_verify} @verify blocks")
    print(f"    {n_target} @target blocks")
    print()
    print("  PARSE:    compiler not built yet -- Phase 1.2 required")
    print("  PROFILE:  compiler not built yet -- Phase 1.3 required")
    print("  TYPES:    compiler not built yet -- Phase 1.3 required")
    print("  OPTIMIZE: compiler not built yet -- Phase 2.1 required")
    print()
    print("  TARGETS (would emit, once backends ship):")
    print(f"    C:       {src.stem}.c       (Phase 2.1)")
    print(f"    Rust:    {src.stem}.rs      (Phase 2.2)")
    print(f"    LLVM:    {src.stem}.ll      (Phase 2.3)")
    if n_target:
        print(f"    Verilog: {src.stem}.v       (Phase 3.2)")
    if n_verify:
        print(f"    Lean:    {src.stem}.lean    (Phase 2.4)")
    print()
    print("  Next session that completes Phase 1 unblocks PARSE / PROFILE /")
    print("  TYPES output here. See roadmap/phases/phase1_language.md.")
    return 0


# ── Entrypoint ───────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in {"-h", "--help", "help"}:
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "status":
        return cmd_status()
    if cmd == "deps":
        return cmd_deps()
    if cmd == "patents":
        return cmd_patents()
    if cmd == "industry":
        return cmd_industry()
    if cmd == "chain":
        if len(args) < 2:
            print("Usage: forge_graph.py chain <path-to-eml-source>",
                  file=sys.stderr)
            return 1
        return cmd_chain(args[1])
    print(f"Unknown subcommand: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
