"""Sidecar emission of MachLib/Discovered/*.lean from any compiled kernel.

This module is the shared core behind two entry points:

  * `--auto-theorems` flag in `tools/cli/main.py` — fires once per
    compiled kernel, so any new `.eml` automatically grows a proof
    target in MachLib/Discovered/.
  * `tools/scripts/regen_discovered.py` — bulk regenerates every
    existing `.lean` in MachLib/Discovered/ from its matching `.eml`.

Both share the same redaction rule (open-core IP discipline,
2026-05-02): any source path that points into `industries/` is
rewritten to `<private>/<basename>.eml` before the file lands on
disk.

Empty Lean output (kernels without any `@verify(lean, ...)` block)
is intentionally a no-op — the regen script and the CLI flag both
treat that as "nothing to emit" rather than overwriting with an
empty file.
"""
from __future__ import annotations

import os
from pathlib import Path

from lang.parser.ast_nodes import EMLModule
from software.verification.lean.LeanBackend import LeanBackend


_DEFAULT_MACHLIB_ROOT = Path.home() / "monogate" / "machlib"


def redact_source_path(lean_text: str, basename: str) -> str:
    """Replace the codegen `-- Source file:` line with the redacted form.

    `LeanBackend` writes the absolute / industries-relative path of
    the source `.eml` for traceability; for any file shipped into
    public MachLib we substitute `<private>/<basename>.eml` so the
    proprietary vertical hierarchy doesn't leak.

    The rewrite is line-oriented and idempotent — applying it twice
    is a no-op.
    """
    out_lines: list[str] = []
    for line in lean_text.splitlines():
        if line.startswith("-- Source file:"):
            out_lines.append(f"-- Source file:   <private>/{basename}.eml")
        else:
            out_lines.append(line)
    trailing_nl = "\n" if lean_text.endswith("\n") else ""
    return "\n".join(out_lines) + trailing_nl


def resolve_machlib_root(explicit: Path | None) -> Path:
    """Resolve the MachLib root from: explicit flag > MACHLIB_ROOT env > default."""
    if explicit is not None:
        return explicit
    env = os.environ.get("MACHLIB_ROOT", "").strip()
    if env:
        return Path(env)
    return _DEFAULT_MACHLIB_ROOT


def discovered_dir(machlib_root: Path) -> Path:
    """Path to MachLib/Discovered/ inside a given machlib root.

    Does not check existence — callers handle missing dirs explicitly.
    """
    return machlib_root / "foundations" / "MachLib" / "Discovered"


def write_discovered_lean(
    mod: EMLModule,
    *,
    basename: str,
    machlib_root: Path,
    backend: LeanBackend | None = None,
    dry_run: bool = False,
) -> Path | None:
    """Compile `mod` via LeanBackend and write to MachLib/Discovered/.

    Returns the destination path on success, or `None` when LeanBackend
    produced empty output (no `@verify(lean, ...)` blocks). On
    `dry_run`, returns the path that would be written without touching
    disk.

    Caller is responsible for `Profiler.profile_module(mod)` having
    already been run; LeanBackend assumes a profiled module.

    The MachLib root must exist; the `Discovered/` subdir is created
    if missing. We deliberately do NOT auto-create the root itself —
    pointing at a wrong path is more often a config bug than a fresh
    install, and a silent `mkdir -p ~/monogate/machlib/...` would
    mask it.
    """
    if backend is None:
        backend = LeanBackend()
    lean_text = backend.compile_module(mod)
    if not lean_text:
        return None

    redacted = redact_source_path(lean_text, basename)
    if not machlib_root.is_dir():
        raise FileNotFoundError(
            f"MachLib root not found: {machlib_root}. "
            "Pass --machlib-root or set MACHLIB_ROOT env."
        )
    dest_dir = discovered_dir(machlib_root)
    dest_path = dest_dir / f"{basename}.lean"
    if dry_run:
        return dest_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(redacted, encoding="utf-8")
    return dest_path
