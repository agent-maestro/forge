"""Regenerate MachLib/Discovered/*.lean from Forge industries/*.eml.

For each existing ``<basename>.lean`` under
``<machlib>/foundations/MachLib/Discovered/``, find the matching
``<basename>.eml`` under ``forge/industries/``, re-emit via
``LeanBackend``, redact the source path to ``<private>/<basename>.eml``
(open-core IP discipline), and overwrite the .lean file.

Files with no matching .eml are left untouched and reported. Files
with multiple .eml matches are reported as ambiguous and skipped.

Usage:
    python tools/scripts/regen_discovered.py
    python tools/scripts/regen_discovered.py --dry-run
    python tools/scripts/regen_discovered.py --machlib-root /path/to/machlib
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lang.parser.parser import parse_file  # noqa: E402
from lang.profiler.profiler import Profiler  # noqa: E402
from software.verification.lean.LeanBackend import LeanBackend  # noqa: E402


def _redact_source_path(lean_text: str, basename: str) -> str:
    """Replace the codegen source-path comment with the redacted form.

    The emitter writes::
        -- Source file:   industries/<vertical>/<sub>/<basename>.eml
    We rewrite it to::
        -- Source file:   <private>/<basename>.eml
    """
    out_lines: list[str] = []
    for line in lean_text.splitlines():
        if line.startswith("-- Source file:"):
            out_lines.append(f"-- Source file:   <private>/{basename}.eml")
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if lean_text.endswith("\n") else "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--machlib-root", type=Path,
                   default=Path.home() / "monogate" / "machlib")
    p.add_argument("--forge-root", type=Path,
                   default=Path.home() / "monogate" / "forge")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None,
                   help="Process only the first N files (for smoke tests)")
    args = p.parse_args(argv)

    discovered = (
        args.machlib_root / "foundations" / "MachLib" / "Discovered"
    )
    industries = args.forge_root / "industries"
    if not discovered.is_dir():
        print(f"error: Discovered/ not found at {discovered}", file=sys.stderr)
        return 1
    if not industries.is_dir():
        print(f"error: industries/ not found at {industries}", file=sys.stderr)
        return 1

    # Index .eml files by basename.
    eml_index: dict[str, list[Path]] = {}
    for path in industries.rglob("*.eml"):
        eml_index.setdefault(path.stem, []).append(path)

    lean_files = sorted(discovered.glob("*.lean"))
    if args.limit:
        lean_files = lean_files[:args.limit]

    n_regen = 0
    n_skip_no_eml: list[str] = []
    n_skip_ambiguous: list[str] = []
    n_error: list[tuple[str, str]] = []

    profiler = Profiler()
    backend = LeanBackend(optimize=True)

    for lean_path in lean_files:
        basename = lean_path.stem
        candidates = eml_index.get(basename, [])
        if not candidates:
            n_skip_no_eml.append(basename)
            continue
        if len(candidates) > 1:
            n_skip_ambiguous.append(
                f"{basename}: {[str(c.relative_to(args.forge_root)) for c in candidates]}"
            )
            continue
        eml_path = candidates[0]
        try:
            mod = parse_file(eml_path)
            profiler.profile_module(mod)
            new_text = backend.compile_module(mod)
            new_text = _redact_source_path(new_text, basename)
        except Exception as exc:  # noqa: BLE001
            n_error.append((basename, repr(exc)[:200]))
            continue

        if not args.dry_run:
            lean_path.write_text(new_text, encoding="utf-8")
        n_regen += 1
        if n_regen % 20 == 0:
            print(f"  ... {n_regen} regenerated")

    print()
    print(f"Regenerated: {n_regen}{' (dry run)' if args.dry_run else ''}")
    if n_skip_no_eml:
        print(f"Skipped (no matching .eml): {len(n_skip_no_eml)}")
        for b in n_skip_no_eml[:10]:
            print(f"  - {b}")
        if len(n_skip_no_eml) > 10:
            print(f"  ... and {len(n_skip_no_eml) - 10} more")
    if n_skip_ambiguous:
        print(f"Skipped (ambiguous): {len(n_skip_ambiguous)}")
        for line in n_skip_ambiguous[:10]:
            print(f"  - {line}")
    if n_error:
        print(f"Errors: {len(n_error)}")
        for b, msg in n_error[:10]:
            print(f"  - {b}: {msg}")
    return 0 if not n_error else 2


if __name__ == "__main__":
    raise SystemExit(main())
