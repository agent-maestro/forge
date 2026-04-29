"""Tests for the canonical formatter (eml-fmt).

Three guarantees the test suite enforces:

  1. Idempotence: format(format(x)) == format(x)
  2. AST preservation: parse(format(x)) is structurally identical
     to parse(x) (semantics-preserving)
  3. CLI gate: --fmt --check exits 0 on canonical files and 1
     on non-canonical files

Comment preservation is NOT a guarantee -- the parser strips
comments at lex time. Source files with important commentary
should not be `--write`-formatted.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lang.parser.parser import parse_source
from lang.parser.ast_nodes import ASTNode, EMLModule
from tools.fmt import format_source


REPO_ROOT = Path(__file__).resolve().parents[3]
STDLIB_DIR = REPO_ROOT / "lang" / "spec" / "stdlib"
INDUSTRY_DIR = REPO_ROOT / "industries"


def _all_real_eml_files() -> list[Path]:
    paths: list[Path] = []
    paths += sorted(STDLIB_DIR.glob("*.eml"))
    if INDUSTRY_DIR.exists():
        paths += sorted(INDUSTRY_DIR.rglob("*.eml"))
    return paths


# ── 1. Idempotence ────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    _all_real_eml_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
)
def test_format_is_idempotent(path: Path) -> None:
    """format(format(x)) must equal format(x) -- otherwise CI
    diff-checks would oscillate forever."""
    src = path.read_text(encoding="utf-8")
    once = format_source(src, source_file=str(path))
    twice = format_source(once, source_file=str(path))
    assert once == twice, (
        f"{path.name}: formatter not idempotent\n"
        f"--- once ---\n{once[:600]}\n"
        f"--- twice ---\n{twice[:600]}"
    )


# ── 2. AST preservation ───────────────────────────────────────


def _ast_shape(node: ASTNode) -> tuple:
    """Recursive structural fingerprint of an AST node. Drops
    line / col, keeps kind + value + children."""
    return (
        node.kind.value,
        repr(node.value),
        tuple(_ast_shape(c) for c in node.children),
    )


def _module_shape(mod: EMLModule) -> tuple:
    """Structural fingerprint of an entire module."""
    return (
        mod.name,
        tuple(
            (c.name, c.type_name, _ast_shape(c.value))
            for c in mod.constants
        ),
        tuple(
            (t.name, t.base_type, t.constraint)
            for t in mod.types
        ),
        tuple(
            (
                fn.name,
                fn.return_type,
                tuple(fn.return_tuple_types),
                tuple((p.name, p.type_name) for p in fn.params),
                tuple(
                    (w.kind, w.op, _serialize_where_value(w.value))
                    for w in fn.where_clauses
                ),
                _ast_shape(fn.body) if fn.body else None,
            )
            for fn in mod.functions
        ),
    )


def _serialize_where_value(v):
    """`where domain: <expr>` stores the value as an ASTNode --
    serialize via _ast_shape; primitives pass through."""
    if isinstance(v, ASTNode):
        return _ast_shape(v)
    return v


@pytest.mark.parametrize(
    "path",
    _all_real_eml_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)).replace("\\", "/"),
)
def test_format_preserves_ast(path: Path) -> None:
    """The formatted source must parse to a structurally-identical
    AST as the original."""
    src = path.read_text(encoding="utf-8")
    original = parse_source(src, source_file=str(path))
    formatted = format_source(src, source_file=str(path))
    reparsed = parse_source(formatted, source_file=str(path))
    assert _module_shape(original) == _module_shape(reparsed), (
        f"{path.name}: format() altered the parsed AST shape"
    )


# ── 3. Hand-written fixtures ──────────────────────────────────


SIMPLE_FN = """\
fn add(a: f64, b: f64) -> f64
    where chain_order <= 0
{
    a + b
}
"""


def test_formatter_handles_simple_fn() -> None:
    out = format_source(SIMPLE_FN)
    assert "fn add(a: f64, b: f64) -> f64" in out
    assert "where chain_order <= 0" in out
    assert "a + b" in out


def test_formatter_minimises_parentheses() -> None:
    """Source with redundant parens must render without them
    (a*(b)*(c) -> a * b * c)."""
    src = "fn t(a: f64, b: f64, c: f64) -> f64 { (a) * (b) * (c) }\n"
    out = format_source(src)
    # Should contain "a * b * c" with no surrounding parens
    assert "a * b * c" in out
    # No three-deep paren stack on the body line
    body_line = next(
        l for l in out.splitlines() if "a * b * c" in l
    )
    assert not body_line.strip().startswith("("), body_line


def test_formatter_preserves_needed_parentheses() -> None:
    """Source with semantically-required parens (precedence) must
    keep them."""
    src = "fn t(a: f64, b: f64, c: f64) -> f64 { a * (b + c) }\n"
    out = format_source(src)
    assert "a * (b + c)" in out


def test_formatter_handles_constants_and_let_bindings() -> None:
    src = (
        "const K: f64 = 2.5;\n"
        "fn t(x: f64) -> f64 {\n"
        "    let y = K * x;\n"
        "    y + 1.0\n"
        "}\n"
    )
    out = format_source(src)
    assert "const K: f64 = 2.5;" in out
    assert "let y = K * x;" in out


def test_formatter_emits_trailing_newline() -> None:
    out = format_source("fn t(x: f64) -> f64 { x }\n")
    assert out.endswith("\n")


# ── 4. CLI gate (--fmt --check) ───────────────────────────────


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "cli" / "main.py"),
         *args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=30,
    )


def test_cli_fmt_emits_to_stdout(tmp_path: Path) -> None:
    """`--fmt` (no flags) prints canonical source to stdout."""
    src = "fn t(x: f64) -> f64 { x*x }\n"
    f = tmp_path / "t.eml"
    f.write_text(src, encoding="utf-8")
    r = _run_cli(str(f), "--fmt")
    assert r.returncode == 0, r.stderr
    assert "x * x" in r.stdout


def test_cli_fmt_check_passes_canonical_file(tmp_path: Path) -> None:
    """`--fmt --check` exits 0 on already-canonical files."""
    src = format_source("fn t(x: f64) -> f64 { x * x }\n")
    f = tmp_path / "t.eml"
    f.write_text(src, encoding="utf-8")
    r = _run_cli(str(f), "--fmt", "--check")
    assert r.returncode == 0, (
        f"--fmt --check failed on a canonical file:\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    )


def test_cli_fmt_check_fails_non_canonical_file(tmp_path: Path) -> None:
    """`--fmt --check` exits 1 on non-canonical files."""
    src = "fn t(x:f64)->f64{x*x}\n"  # no spaces
    f = tmp_path / "t.eml"
    f.write_text(src, encoding="utf-8")
    r = _run_cli(str(f), "--fmt", "--check")
    assert r.returncode == 1, (
        f"--fmt --check should have failed:\n{r.stdout}\n{r.stderr}"
    )


def test_cli_fmt_write_rewrites_in_place(tmp_path: Path) -> None:
    """`--fmt --write` rewrites the file in place."""
    src = "fn t(x:f64)->f64{x*x}\n"
    f = tmp_path / "t.eml"
    f.write_text(src, encoding="utf-8")
    r = _run_cli(str(f), "--fmt", "--write")
    assert r.returncode == 0, r.stderr
    after = f.read_text(encoding="utf-8")
    assert "x * x" in after
    # And running --check on the now-formatted file must pass.
    r2 = _run_cli(str(f), "--fmt", "--check")
    assert r2.returncode == 0, r2.stderr
