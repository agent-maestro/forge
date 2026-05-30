"""Tests for the JavaScript (ES module) backend."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.javascript_backend import (
    JavaScriptBackend,
    CompileError as JsErr,
    _safe_ident,
    _wants_drift_warning,
    _JS_RESERVED,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SPRING = REPO_ROOT / "industries" / "gaming" / "physics" / "spring.eml"
FRESNEL = REPO_ROOT / "industries" / "gaming" / "rendering" / "fresnel.eml"
BREATHING = REPO_ROOT / "industries" / "gaming" / "animation" / "breathing.eml"
DIFFUSE = REPO_ROOT / "industries" / "gaming" / "rendering" / "diffuse.eml"

NODE = shutil.which("node")


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Structural properties ─────────────────────────────────────


class TestJSStructure:
    def test_use_strict_directive(self):
        out = JavaScriptBackend().compile(_profile(SPRING))
        assert '"use strict";' in out

    def test_no_class_or_namespace_wrapper(self):
        out = JavaScriptBackend().compile(_profile(SPRING))
        # Top-level export functions, no class wrapper.
        assert "export function " in out
        assert "class " not in out

    def test_constants_use_export_const(self):
        out = JavaScriptBackend().compile(_profile(BREATHING))
        assert "export const ZERO = 0.0;" in out
        assert "export const T_MAX = 3600.0;" in out

    def test_breathing_signature_has_no_class_self(self):
        out = JavaScriptBackend().compile(_profile(BREATHING))
        assert (
            "export function breath_simple(base, amp, omega, phase, t)"
        ) in out

    def test_jsdoc_present_on_each_function(self):
        out = JavaScriptBackend().compile(_profile(BREATHING))
        # JSDoc opener and at least one @param.
        assert "/**" in out
        assert "@param {number}" in out
        assert "@returns {number}" in out

    def test_repeated_let_name_rebinds_after_first_declaration(self):
        src = """
        module repeated_let;
        fn quad(a: Real, b: Real, c: Real, x: Real) -> Real
            where chain_order <= 0
        {
            let y = a;
            let y = y * x;
            let y = y + b;
            let y = y * x;
            let y = y + c;
            y
        }
        """
        out = JavaScriptBackend().compile(_profile_source(src))
        assert "let y = a;" in out
        assert out.count("const y =") == 0
        assert out.count("let y =") == 1
        assert "y = (y * x);" in out
        assert "y = (y + b);" in out
        assert "y = (y + c);" in out

    @pytest.mark.skipif(NODE is None, reason="node not installed")
    def test_repeated_let_name_passes_node_runtime(self):
        src = """
        module repeated_let;
        fn quad(a: Real, b: Real, c: Real, x: Real) -> Real
            where chain_order <= 0
        {
            let y = a;
            let y = y * x;
            let y = y + b;
            let y = y * x;
            let y = y + c;
            y
        }
        """
        out = JavaScriptBackend().compile(_profile_source(src))
        with tempfile.NamedTemporaryFile(
            "w", suffix=".mjs", delete=False, encoding="utf-8",
        ) as f:
            f.write(out)
            path = f.name
        try:
            runner = (
                "const mod = await import(process.argv[1]);"
                "console.log(mod.quad(2, 3, 5, 7));"
            )
            result = subprocess.run(
                ["node", "--input-type=module", "-e", runner, Path(path).as_uri()],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr
            assert float(result.stdout.strip()) == 124.0
        finally:
            os.unlink(path)


# ── Math name mapping ─────────────────────────────────────────


class TestJSMath:
    def test_math_dot_prefix(self):
        out = JavaScriptBackend().compile(_profile(SPRING))
        assert "Math.exp(" in out
        assert "Math.cos(" in out
        assert "Math.sqrt(" in out
        # Should NOT use Python or Kotlin spellings.
        assert "math.exp(" not in out
        assert "kotlin.math" not in out

    def test_pow_uses_math_pow(self):
        out = JavaScriptBackend().compile(_profile(FRESNEL))
        assert "Math.pow(" in out

    def test_clamp_uses_min_max_idiom(self):
        src = """
        module test_clamp;
        fn cl(x: Real) -> Real
            where chain_order <= 0
            requires (x >= 0.0)
        {
            clamp(x, 0.0, 1.0)
        }
        """
        out = JavaScriptBackend().compile(_profile_source(src))
        assert "Math.min(Math.max(" in out


# ── Preconditions ─────────────────────────────────────────────


class TestJSPreconditions:
    def test_requires_lowers_to_range_error(self):
        out = JavaScriptBackend().compile(_profile(BREATHING))
        # JS uses RangeError so callers can catch it specifically.
        assert "throw new RangeError(" in out
        assert "breath_simple: requires" in out


# ── Identifier handling ───────────────────────────────────────


class TestJSIdentifiers:
    def test_safe_ident_renames_js_reserved(self):
        assert _safe_ident("class") == "class_"
        assert _safe_ident("let") == "let_"
        assert _safe_ident("const") == "const_"
        assert _safe_ident("await") == "await_"
        assert _safe_ident("Math") == "Math_"
        assert _safe_ident("regular_name") == "regular_name"

    def test_reserved_set_contains_js_keywords(self):
        for word in (
            "await", "break", "case", "catch", "class", "const",
            "continue", "debugger", "default", "delete", "do", "else",
            "export", "extends", "finally", "for", "function", "if",
            "import", "in", "instanceof", "let", "new", "return",
            "super", "switch", "this", "throw", "try", "typeof",
            "var", "void", "while", "with", "yield",
            "enum", "implements", "interface", "package", "private",
            "protected", "public", "static",
        ):
            assert word in _JS_RESERVED, f"{word!r} should be reserved"


# ── Tuple returns ─────────────────────────────────────────────


class TestJSTuples:
    def test_tuple_return_emits_array(self):
        src = """
        module test_tuple;
        fn pair(x: Real) -> (Real, Real)
            where chain_order <= 0
        {
            (x, x)
        }
        """
        out = JavaScriptBackend().compile(_profile_source(src))
        assert "return [x, x];" in out


# ── End-to-end on every gaming kernel ──────────────────────────


GAMING_DIR = REPO_ROOT / "industries" / "gaming"


@pytest.mark.parametrize(
    "eml", sorted(GAMING_DIR.rglob("*.eml")), ids=lambda p: p.name,
)
def test_gaming_kernel_compiles_to_js(eml: Path):
    out = JavaScriptBackend().compile(_profile(eml))
    assert '"use strict";' in out
    assert "export function " in out


# ── Real Node syntax check ────────────────────────────────────


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize(
    "eml", [SPRING, FRESNEL, BREATHING, DIFFUSE],
    ids=lambda p: p.name,
)
def test_node_syntax_check_passes(eml: Path):
    """`node --check` parses the generated source without error."""
    out = JavaScriptBackend().compile(_profile(eml))
    with tempfile.NamedTemporaryFile(
        "w", suffix=".mjs", delete=False, encoding="utf-8",
    ) as f:
        f.write(out)
        path = f.name
    try:
        result = subprocess.run(
            [NODE, "--check", path], capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"node --check failed for {eml.name}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    finally:
        os.unlink(path)


# ── Optimizer flag ────────────────────────────────────────────


def test_no_optimize_flag_still_produces_valid_output():
    out = JavaScriptBackend(optimize=False).compile(_profile(SPRING))
    assert '"use strict";' in out
    assert "export function " in out
