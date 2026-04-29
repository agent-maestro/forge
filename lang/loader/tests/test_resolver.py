"""Tests for the import resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.loader import LoaderError, ModuleLoader, resolve_imports
from lang.parser.parser import parse_file, parse_source


REPO_ROOT = Path(__file__).resolve().parents[3]
STDLIB_DIR = REPO_ROOT / "lang" / "spec" / "stdlib"


# ── 1. Path resolution ───────────────────────────────────────


def test_resolve_stdlib_math_path() -> None:
    loader = ModuleLoader()
    p = loader.resolve("stdlib::math")
    assert p == STDLIB_DIR / "math.eml"


def test_resolve_unknown_root_errors() -> None:
    loader = ModuleLoader()
    with pytest.raises(LoaderError, match="unknown import root"):
        loader.resolve("notaroot::math")


def test_resolve_single_segment_errors() -> None:
    loader = ModuleLoader()
    with pytest.raises(LoaderError, match="at least 2 segments"):
        loader.resolve("stdlib")


# ── 2. Loading ───────────────────────────────────────────────


def test_load_stdlib_math() -> None:
    loader = ModuleLoader()
    mod = loader.load("stdlib::math")
    assert mod.name == "math"
    assert any(f.name == "lerp" for f in mod.functions)
    assert any(c.name == "LN2" for c in mod.constants)


def test_load_caches_repeated_calls() -> None:
    loader = ModuleLoader()
    a = loader.load("stdlib::math")
    b = loader.load("stdlib::math")
    assert a is b, "loader should cache modules by joined path"


def test_load_missing_module_errors() -> None:
    loader = ModuleLoader()
    with pytest.raises(LoaderError, match="not found"):
        loader.load("stdlib::no_such_module")


# ── 3. Cycle detection ───────────────────────────────────────


def test_cycle_detection(tmp_path: Path) -> None:
    """Two modules that import each other must raise LoaderError."""
    a_path = tmp_path / "a.eml"
    b_path = tmp_path / "b.eml"
    a_path.write_text("module a;\nuse fixt::b;\n", encoding="utf-8")
    b_path.write_text("module b;\nuse fixt::a;\n", encoding="utf-8")

    loader = ModuleLoader(search_paths={"fixt": tmp_path})
    with pytest.raises(LoaderError, match="import cycle"):
        loader.load("fixt::a")


# ── 4. resolve_imports() merges names ────────────────────────


def test_resolve_imports_merges_functions() -> None:
    src = (
        "use stdlib::math;\n"
        "fn t() -> f64 { 1.0 }\n"
    )
    mod = parse_source(src)
    assert len(mod.functions) == 1
    merged = resolve_imports(mod)
    # math has 21 functions in the stdlib snapshot
    fnames = {f.name for f in merged.functions}
    assert "t" in fnames
    assert "lerp" in fnames
    assert "sigmoid" in fnames
    assert len(merged.functions) == 1 + 21


def test_resolve_imports_merges_constants() -> None:
    src = "use stdlib::math;\n"
    merged = resolve_imports(parse_source(src))
    cnames = {c.name for c in merged.constants}
    # math.eml exports LN2, LN10, DEG_TO_RAD, RAD_TO_DEG
    assert {"LN2", "LN10", "DEG_TO_RAD", "RAD_TO_DEG"} <= cnames


def test_resolve_imports_no_imports_pass_through() -> None:
    mod = parse_source("fn t() -> f64 { 1.0 }")
    assert resolve_imports(mod) is mod  # identity


def test_resolve_imports_two_stdlibs_no_clash() -> None:
    """math and control define disjoint names; both should merge."""
    src = "use stdlib::math;\nuse stdlib::control;\n"
    merged = resolve_imports(parse_source(src))
    fnames = {f.name for f in merged.functions}
    assert "lerp" in fnames     # from math
    assert "pid" in fnames      # from control
    assert "saturate" in fnames # from control


# ── 5. Clash detection ───────────────────────────────────────


def test_local_function_shadowing_imported_one_errors() -> None:
    """If the user defines `fn lerp(...)` AND uses stdlib::math
    (which exports lerp), that's an explicit conflict."""
    src = (
        "use stdlib::math;\n"
        "fn lerp(a: f64, b: f64, t: f64) -> f64 { a }\n"
    )
    with pytest.raises(LoaderError, match="already defines"):
        resolve_imports(parse_source(src))


def test_two_imports_both_export_same_name_errors(
    tmp_path: Path,
) -> None:
    """If two imports both bring in the same name, that's a clash
    even when the importing module is empty."""
    a = tmp_path / "a.eml"
    b = tmp_path / "b.eml"
    a.write_text(
        "module a;\nfn duped(x: f64) -> f64 { x }\n",
        encoding="utf-8",
    )
    b.write_text(
        "module b;\nfn duped(x: f64) -> f64 { x + 1.0 }\n",
        encoding="utf-8",
    )

    src = "use fixt::a;\nuse fixt::b;\n"
    mod = parse_source(src)
    loader = ModuleLoader(search_paths={"fixt": tmp_path})
    with pytest.raises(LoaderError, match="already imported"):
        resolve_imports(mod, loader=loader)


# ── 6. parse_file auto-resolves ──────────────────────────────


def test_parse_file_resolves_by_default(tmp_path: Path) -> None:
    f = tmp_path / "client.eml"
    f.write_text(
        "use stdlib::math;\nfn t() -> f64 { 1.0 }\n",
        encoding="utf-8",
    )
    mod = parse_file(f)  # default: resolve=True
    fnames = {f.name for f in mod.functions}
    assert "lerp" in fnames
    assert "t" in fnames


def test_parse_file_resolve_false_keeps_raw(tmp_path: Path) -> None:
    f = tmp_path / "client.eml"
    f.write_text(
        "use stdlib::math;\nfn t() -> f64 { 1.0 }\n",
        encoding="utf-8",
    )
    mod = parse_file(f, resolve=False)
    fnames = {f.name for f in mod.functions}
    assert "lerp" not in fnames
    assert mod.imports[0].joined == "stdlib::math"


# ── 7. Formatter round-trips `use` ───────────────────────────


def test_formatter_emits_use_declarations() -> None:
    from tools.fmt import format_source
    src = (
        "module client;\n"
        "use stdlib::math;\n"
        "use stdlib::control;\n"
        "fn t() -> f64 { 1.0 }\n"
    )
    out = format_source(src)
    assert "use stdlib::math;" in out
    assert "use stdlib::control;" in out


def test_formatter_idempotent_on_use_decls() -> None:
    from tools.fmt import format_source
    src = (
        "module client;\n"
        "use stdlib::math;\n"
        "fn t() -> f64 { 1.0 }\n"
    )
    once = format_source(src)
    twice = format_source(once)
    assert once == twice


# ── 8. Local imports ─────────────────────────────────────────


def test_local_import_resolves_relative_to_source(
    tmp_path: Path,
) -> None:
    """`use local::helpers;` from /a/main.eml resolves to
    /a/helpers.eml."""
    helpers = tmp_path / "helpers.eml"
    helpers.write_text(
        "module helpers;\nfn double(x: f64) -> f64 { 2.0 * x }\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.eml"
    main.write_text(
        "use local::helpers;\n"
        "fn quad(x: f64) -> f64 { double(double(x)) }\n",
        encoding="utf-8",
    )
    mod = parse_file(main)
    fnames = {f.name for f in mod.functions}
    assert "double" in fnames
    assert "quad" in fnames


def test_local_import_caches_per_resolved_path(
    tmp_path: Path,
) -> None:
    """Two sibling files with the same `use local::shared;`
    must resolve to two different files (different dirs)."""
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    (a_dir / "shared.eml").write_text(
        "fn marker_a(x: f64) -> f64 { x }\n", encoding="utf-8",
    )
    (b_dir / "shared.eml").write_text(
        "fn marker_b(x: f64) -> f64 { x }\n", encoding="utf-8",
    )
    (a_dir / "main.eml").write_text(
        "use local::shared;\nfn t(x: f64) -> f64 { x }\n",
        encoding="utf-8",
    )
    (b_dir / "main.eml").write_text(
        "use local::shared;\nfn t(x: f64) -> f64 { x }\n",
        encoding="utf-8",
    )
    a_mod = parse_file(a_dir / "main.eml")
    b_mod = parse_file(b_dir / "main.eml")
    a_names = {f.name for f in a_mod.functions}
    b_names = {f.name for f in b_mod.functions}
    assert "marker_a" in a_names and "marker_b" not in a_names
    assert "marker_b" in b_names and "marker_a" not in b_names


def test_local_import_without_source_dir_errors() -> None:
    """Parsing a string (no source file) and trying to use
    local:: must produce a clear LoaderError."""
    src = (
        "use local::helpers;\n"
        "fn t() -> f64 { 1.0 }\n"
    )
    with pytest.raises(LoaderError, match="requires a source-file"):
        # parse_source with resolve=True triggers loader.load()
        # without a source dir (the source_file is "<string>").
        parse_source(src, resolve=True)


def test_local_import_missing_file_errors(tmp_path: Path) -> None:
    main = tmp_path / "main.eml"
    main.write_text(
        "use local::no_such_helper;\nfn t() -> f64 { 1.0 }\n",
        encoding="utf-8",
    )
    with pytest.raises(LoaderError, match="not found"):
        parse_file(main)


# ── 9. Hardening: case + dedup ───────────────────────────────


def test_case_handling_matches_filesystem(tmp_path: Path) -> None:
    """Loader doesn't case-normalise -- it leaves case handling to
    the underlying filesystem. So the behaviour of
    `use stdlib::MATH;` (vs `math.eml`) is platform-dependent:

    - Case-sensitive (Linux, default macOS APFS): file not found
    - Case-insensitive (Windows NTFS, default macOS HFS+): match

    Either is acceptable; what we DO require is that two
    different-cased spellings that resolve to the same on-disk
    file deduplicate via the cache (covered by the dedup test
    below). This test simply documents the FS-driven behaviour
    rather than enforcing one stance."""
    helpers = tmp_path / "math.eml"
    helpers.write_text(
        "fn marker_lower(x: f64) -> f64 { x }\n",
        encoding="utf-8",
    )
    fs_is_case_insensitive = (tmp_path / "MATH.EML").exists()

    from lang.loader import ModuleLoader
    loader = ModuleLoader(search_paths={"x": tmp_path})
    if fs_is_case_insensitive:
        # The lookup should succeed regardless of spelling.
        mod = loader.load("x::MATH")
        assert any(f.name == "marker_lower" for f in mod.functions)
    else:
        with pytest.raises(LoaderError, match="not found"):
            loader.load("x::MATH")


def test_two_paths_to_same_file_share_one_cache_entry(
    tmp_path: Path,
) -> None:
    """Two `use` paths that resolve to the same on-disk file must
    end up as a single cache entry. The cache key is the resolved
    file path, so even quirky path spellings -- e.g. via a
    symlink (POSIX), or via pathlib normalisation -- collapse."""
    helpers = tmp_path / "helpers.eml"
    helpers.write_text(
        "fn double(x: f64) -> f64 { 2.0 * x }\n",
        encoding="utf-8",
    )

    from lang.loader import ModuleLoader

    loader = ModuleLoader(search_paths={"a": tmp_path, "b": tmp_path})
    mod_a = loader.load("a::helpers")
    mod_b = loader.load("b::helpers")
    # Same on-disk file -> same cached EMLModule object.
    assert mod_a is mod_b


def test_symlink_dedups_across_aliases(tmp_path: Path) -> None:
    """A symlink to the same file goes to the same cache entry.
    Skipped on platforms / accounts that can't create symlinks
    (Windows non-admin, restricted CI runners)."""
    real = tmp_path / "real.eml"
    real.write_text(
        "fn marker(x: f64) -> f64 { x }\n",
        encoding="utf-8",
    )
    link = tmp_path / "alias.eml"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available on this platform/account")

    from lang.loader import ModuleLoader
    loader = ModuleLoader(search_paths={"x": tmp_path})
    a = loader.load("x::real")
    b = loader.load("x::alias")
    assert a is b, "symlink alias should share the cache entry"


def test_loader_cache_independent_per_instance(
    tmp_path: Path,
) -> None:
    """Two ModuleLoader instances have independent caches (so
    test isolation works)."""
    helpers = tmp_path / "helpers.eml"
    helpers.write_text(
        "fn one(x: f64) -> f64 { x }\n", encoding="utf-8",
    )
    from lang.loader import ModuleLoader
    a = ModuleLoader(search_paths={"x": tmp_path})
    b = ModuleLoader(search_paths={"x": tmp_path})
    mod_a = a.load("x::helpers")
    mod_b = b.load("x::helpers")
    # Different loader instances -> distinct EMLModule objects
    # even though the on-disk file is the same.
    assert mod_a is not mod_b


def test_loader_path_with_unusual_segments_resolved(
    tmp_path: Path,
) -> None:
    """`use root::foo::bar::baz;` should look up
    `<root>/foo/bar/baz.eml`. Verify the multi-segment recursion
    actually descends into subdirectories."""
    deep = tmp_path / "foo" / "bar"
    deep.mkdir(parents=True)
    (deep / "baz.eml").write_text(
        "fn deep_fn(x: f64) -> f64 { x }\n", encoding="utf-8",
    )
    from lang.loader import ModuleLoader
    loader = ModuleLoader(search_paths={"x": tmp_path})
    mod = loader.load("x::foo::bar::baz")
    fnames = {f.name for f in mod.functions}
    assert "deep_fn" in fnames
