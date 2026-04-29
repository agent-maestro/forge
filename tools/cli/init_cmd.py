"""`eml-compile init` -- scaffold a new EML project.

Creates the canonical project layout in `target_dir`:

    <target>/
      pyproject.toml          # forge dependency declaration
      main.eml                # hello-world starter
      .vscode/
        settings.json         # eml-fmt-on-save + diagnostic wiring

Existing files are not overwritten unless `--force` is passed.

Reference: lang/spec/EML_LANG_DESIGN.md section 4.2 (`eml-compile init`).
"""

from __future__ import annotations

import argparse
from pathlib import Path


_PYPROJECT_TEMPLATE = '''\
[project]
name = "{name}"
version = "0.1.0"
description = "EML-lang project"
requires-python = ">=3.10"
dependencies = [
    "monogate-forge",
]

[tool.eml-fmt]
# Canonical formatter settings. Run via:  eml-compile <file.eml> --fmt --check
indent = 4
line-width = 100
'''


_MAIN_EML_TEMPLATE = '''\
// {name}.eml -- starter program. Replace with your own pipeline.

module {name};

@target(c, rust)
fn hello(x: f64) -> f64
  where chain_order <= 1
{
    sin(x) + cos(x)
}
'''


_VSCODE_SETTINGS_TEMPLATE = '''\
{
  "[eml]": {
    "editor.formatOnSave": true,
    "editor.tabSize": 4,
    "editor.insertSpaces": true
  },
  "files.associations": {
    "*.eml": "eml"
  },
  "eml.compile.target": "c",
  "eml.fpga.target": "xilinx.artix7"
}
'''


_GITIGNORE_TEMPLATE = '''\
# Generated artifacts
*.c
*.rs
*.v
*.vhd
*.lean
*.wasm
build/
__pycache__/
'''


def _render(template: str, name: str) -> str:
    """Render a template, substituting {name} once. We avoid str.format
    because the JSON template contains literal braces."""
    return template.replace("{name}", name)


def init_project(
    target_dir: Path,
    *,
    name: str | None = None,
    force: bool = False,
) -> int:
    """Create the canonical project layout in `target_dir`.

    Returns 0 on success, non-zero on a precondition failure.
    """
    target_dir = Path(target_dir).resolve()
    project_name = name or target_dir.name or "eml_project"

    target_dir.mkdir(parents=True, exist_ok=True)

    files = {
        target_dir / "pyproject.toml":
            _render(_PYPROJECT_TEMPLATE, project_name),
        target_dir / "main.eml":
            _render(_MAIN_EML_TEMPLATE, project_name),
        target_dir / ".vscode" / "settings.json":
            _render(_VSCODE_SETTINGS_TEMPLATE, project_name),
        target_dir / ".gitignore":
            _render(_GITIGNORE_TEMPLATE, project_name),
    }

    written = 0
    skipped = 0
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not force:
            skipped += 1
            continue
        path.write_text(content, encoding="utf-8")
        written += 1

    print(f"eml-compile init: scaffolded '{project_name}' "
          f"in {target_dir}")
    print(f"  wrote {written} file(s); skipped {skipped} (use --force to overwrite)")
    print()
    print("Next steps:")
    print(f"  cd {target_dir}")
    print(f"  eml-compile main.eml --profile-only")
    print(f"  eml-compile main.eml --target c -o main.c")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point for `eml-compile init <dir>`."""
    parser = argparse.ArgumentParser(
        prog="eml-compile init",
        description="Scaffold a new EML-lang project.",
    )
    parser.add_argument(
        "target",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Directory to initialize (default: current directory).",
    )
    parser.add_argument(
        "--name",
        help="Project name (default: target directory name).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files instead of skipping them.",
    )
    args = parser.parse_args(argv)
    return init_project(args.target, name=args.name, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
