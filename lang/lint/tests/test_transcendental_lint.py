"""v0.5 deprecation lint: transcendental functions in `requires` clauses.

TDD RED phase -- all tests must FAIL before implementation.

Coverage matrix
---------------
  requires(sin(x) > 0)        -> warns  (sin is transcendental)
  requires(sqrt(dt) > 0)      -> warns  (sqrt is transcendental)
  requires(x > 0.0)           -> silent (decidable, no transcendental)
  assume(sin(x) > 0)          -> silent (migration target -- never warn)
  requires(pow(x, 2) > 0)    -> silent (integer exponent -- not flagged)
  requires(pow(x, 0.5) > 0)  -> warns  (non-integer exponent -- equivalent to sqrt)
  no --lint flag              -> zero warnings regardless of content
  warning text                -> mentions name, line:col, suggests `assume`
  real fixture: binomial_tree.eml  -> exactly 2 warns on risk_neutral_prob's requires
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ── helpers ──────────────────────────────────────────────────────────────────


def _import_lint():
    """Import the lint module; fail fast if not implemented."""
    try:
        from lang.lint import lint_module, LintWarning
        return lint_module, LintWarning
    except ImportError as exc:
        pytest.fail(f"lang.lint not yet implemented: {exc}")


def _import_transcendental():
    """Import the transcendental submodule directly."""
    try:
        from lang.lint.transcendental import lint_transcendental_requires
        return lint_transcendental_requires
    except ImportError as exc:
        pytest.fail(f"lang.lint.transcendental not yet implemented: {exc}")


def _parse(src: str):
    from lang.parser import parse_source
    return parse_source(src)


FORGE_ROOT = Path(__file__).resolve().parents[3]
BINOMIAL_TREE = (
    FORGE_ROOT / "industries" / "finance" / "pricing" / "binomial_tree.eml"
)


# ── Unit tests: transcendental walker ────────────────────────────────────────


@pytest.mark.unit
def test_sin_in_requires_produces_warning():
    """requires(sin(x) > 0) must produce a lint warning."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (sin(x) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) >= 1
    w = warnings[0]
    assert isinstance(w, LintWarning)
    assert "sin" in w.message


@pytest.mark.unit
def test_sqrt_in_requires_produces_warning():
    """requires(sqrt(dt) > 0) must produce a lint warning."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn up_factor(vol: Real, dt: Real) -> Real
            requires (vol * sqrt(dt) > 0.0)
        { vol }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) >= 1
    assert any("sqrt" in w.message for w in warnings)


@pytest.mark.unit
def test_decidable_requires_no_warning():
    """requires(x > 0.0) -- fully decidable -- must NOT warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (x > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_assume_with_transcendental_no_warning():
    """assume(sin(x) > 0) is the migration target; must NOT warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            assume (sin(x) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_pow_integer_exponent_no_warning():
    """requires(pow(x, 2) > 0) -- integer exponent -- must NOT warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (pow(x, 2) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_pow_noninteger_exponent_warns():
    """requires(pow(x, 0.5) > 0) -- non-integer exponent -- MUST warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (pow(x, 0.5) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) >= 1
    assert any("pow" in w.message for w in warnings)


# ── Warning text quality ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_warning_text_mentions_transcendental_name():
    """Warning text must name the specific transcendental function."""
    lint_module, LintWarning = _import_lint()
    for fn_name in ("sin", "cos", "tan", "exp", "ln", "sqrt",
                     "asin", "acos", "atan", "sinh", "cosh", "tanh"):
        mod = _parse(
            f"""
            fn f(x: Real) -> Real
                requires ({fn_name}(x) > 0.0)
            {{ x }}
            """
        )
        warnings = lint_module(mod)
        assert len(warnings) >= 1, f"expected warning for {fn_name}"
        assert any(fn_name in w.message for w in warnings), (
            f"warning for {fn_name} did not mention function name"
        )


@pytest.mark.unit
def test_warning_text_mentions_assume_migration():
    """Warning text must suggest migrating to `assume`."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (sqrt(x) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) >= 1
    w = warnings[0]
    assert "assume" in w.message.lower()


@pytest.mark.unit
def test_warning_carries_line_and_col():
    """LintWarning must carry non-zero line and col attributes."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (sin(x) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) >= 1
    w = warnings[0]
    assert hasattr(w, "line"), "LintWarning must have a 'line' attribute"
    assert hasattr(w, "col"), "LintWarning must have a 'col' attribute"
    assert w.line > 0, f"expected line > 0, got {w.line}"


# ── Default-OFF: no --lint means zero warnings ────────────────────────────────


@pytest.mark.unit
def test_lint_module_default_off_via_flag():
    """When lint_module is called with lint=False, no warnings are emitted."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (sqrt(x) > 0.0)
        { x }
        """
    )
    # When called with lint_enabled=False, result must be empty
    warnings = lint_module(mod, lint_enabled=False)
    assert warnings == []


@pytest.mark.unit
def test_lint_module_default_parameter_is_true():
    """lint_module(mod) with default args should lint (lint_enabled defaults True)."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (sqrt(x) > 0.0)
        { x }
        """
    )
    # Default call -- lint_enabled should default to True at this layer
    # (the CLI gates this behind --lint; the function itself is always-on
    # when invoked; gating is at call site)
    warnings = lint_module(mod)
    assert len(warnings) >= 1


# ── Multiple functions / clauses ─────────────────────────────────────────────


@pytest.mark.unit
def test_multiple_transcendentals_in_one_requires():
    """A single requires clause using two transcendentals emits at least one warning."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real, y: Real) -> Real
            requires (sin(x) + cos(y) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    # At minimum one warning per requires clause that uses a transcendental
    assert len(warnings) >= 1


@pytest.mark.unit
def test_mixed_requires_only_flags_transcendental_ones():
    """When one requires is decidable and one uses sqrt, only one warning fires."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real, dt: Real) -> Real
            requires (x > 0.0)
            requires (sqrt(dt) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) == 1
    assert "sqrt" in warnings[0].message


@pytest.mark.unit
def test_no_requires_no_warning():
    """A function with no requires clauses produces no warnings."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
        { x }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


# ── Real-world fixture: binomial_tree.eml ────────────────────────────────────


# Inline fixture mirroring the pre-Phase-F shape of risk_neutral_prob:
# transcendental sqrt(dt) inside two `requires` clauses. Phase F
# migrated the real binomial_tree.eml fixture to `assume` (which is
# exactly the lint's recommended migration), so these tests now use
# an inline source to keep the lint behaviour under test.
_BINOMIAL_TREE_PRE_PHASE_F = """
const VOL_MIN: Real = 1.0e-6
const VOL_MAX: Real = 5.0
const DT_MIN: Real = 1.0e-6
const DT_MAX: Real = 10.0

fn risk_neutral_prob(rate: Real, vol: Real, dt: Real) -> Real
    requires (vol >= VOL_MIN)
    requires (vol <= VOL_MAX)
    requires (dt >= DT_MIN)
    requires (dt <= DT_MAX)
    requires (rate * dt < vol * sqrt(dt))
    requires (rate * dt > -vol * sqrt(dt))
{ rate }
"""


@pytest.mark.integration
def test_binomial_tree_fixture_warns_on_sqrt():
    """Pre-Phase-F binomial_tree shape: risk_neutral_prob has 2
    requires using sqrt(dt). The lint tool must surface both."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(_BINOMIAL_TREE_PRE_PHASE_F)
    warnings = lint_module(mod)
    # risk_neutral_prob has exactly 2 requires clauses that use sqrt(dt)
    assert len(warnings) == 2, (
        f"expected 2 warnings from binomial_tree pre-Phase-F shape, "
        f"got {len(warnings)}: {[w.message for w in warnings]}"
    )
    for w in warnings:
        assert "sqrt" in w.message
        assert "risk_neutral_prob" in w.message or w.line > 0


@pytest.mark.integration
def test_binomial_tree_warnings_mention_filename():
    """Each warning message or metadata should reference the source line."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(_BINOMIAL_TREE_PRE_PHASE_F)
    warnings = lint_module(mod)
    assert len(warnings) >= 1
    # Each warning should have a positive line number
    for w in warnings:
        assert w.line > 0, f"line should be > 0, got: {w.line}"


# ── CLI integration: --lint flag ──────────────────────────────────────────────


@pytest.mark.integration
def test_cli_no_lint_flag_produces_no_stderr_warnings(tmp_path):
    """Without --lint, eml-compile on binomial_tree.eml writes nothing warning-like to stderr."""
    if not BINOMIAL_TREE.exists():
        pytest.skip(f"fixture not found: {BINOMIAL_TREE}")
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "tools.cli.main",
         str(BINOMIAL_TREE), "--target", "c"],
        capture_output=True, text=True,
        cwd=str(FORGE_ROOT),
    )
    # stderr should not contain "transcendental" or "requires" deprecation notices
    assert "transcendental" not in result.stderr, (
        f"unexpected transcendental warning without --lint:\n{result.stderr}"
    )
    assert result.returncode == 0, f"compile failed: {result.stderr}"


@pytest.mark.integration
def test_cli_lint_flag_produces_warnings_on_stderr(tmp_path):
    """With --lint, eml-compile on a kernel with transcendental
    `requires` clauses writes warnings to stderr."""
    fixture = tmp_path / "binomial_tree_pre_phase_f.eml"
    fixture.write_text(_BINOMIAL_TREE_PRE_PHASE_F)
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "tools.cli.main",
         str(fixture), "--target", "c", "--lint"],
        capture_output=True, text=True,
        cwd=str(FORGE_ROOT),
    )
    assert result.returncode == 0, (
        f"compile must succeed even with --lint; stderr:\n{result.stderr}"
    )
    assert "warning" in result.stderr.lower(), (
        f"expected 'warning' in stderr, got:\n{result.stderr}"
    )
    assert "sqrt" in result.stderr, (
        f"expected 'sqrt' in stderr, got:\n{result.stderr}"
    )


@pytest.mark.integration
def test_cli_lint_flag_produces_assume_suggestion_on_stderr(tmp_path):
    """With --lint, warning text must suggest `assume` migration."""
    fixture = tmp_path / "binomial_tree_pre_phase_f.eml"
    fixture.write_text(_BINOMIAL_TREE_PRE_PHASE_F)
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "tools.cli.main",
         str(fixture), "--target", "c", "--lint"],
        capture_output=True, text=True,
        cwd=str(FORGE_ROOT),
    )
    assert "assume" in result.stderr, (
        f"expected 'assume' migration suggestion in stderr, got:\n{result.stderr}"
    )


# ── Edge cases ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_nested_transcendental_in_requires_warns():
    """exp(vol * sqrt(T)) -- nested call -- still triggers a warning."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(vol: Real, T: Real) -> Real
            requires (exp(vol * sqrt(T)) > 1.0)
        { vol }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) >= 1


@pytest.mark.unit
def test_empty_module_no_warnings():
    """An empty module produces no warnings."""
    lint_module, LintWarning = _import_lint()
    mod = _parse("module empty;")
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_pow_with_negative_integer_exponent_no_warning():
    """requires(pow(x, -2) > 0) -- negative integer -- must NOT warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (pow(x, -2) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_pow_with_zero_exponent_no_warning():
    """requires(pow(x, 0) > 0) -- zero is integer -- must NOT warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (pow(x, 0) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_transcendental_in_body_no_warning():
    """Transcendentals in function body (not requires) must NOT warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (x > 0.0)
        { sqrt(x) }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_transcendental_in_ensures_no_warning():
    """Transcendentals in ensures clauses (not requires) must NOT warn."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (x > 0.0)
            ensures  (result < sqrt(x) + 1.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert warnings == []


@pytest.mark.unit
def test_log_in_requires_warns():
    """'ln' (natural log) in requires must produce a warning."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn f(x: Real) -> Real
            requires (ln(x) > 0.0)
        { x }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) >= 1
    assert any("ln" in w.message for w in warnings)


@pytest.mark.unit
def test_warning_message_format():
    """Warning message must contain 'requires' and describe the migration path."""
    lint_module, LintWarning = _import_lint()
    mod = _parse(
        """
        fn black_scholes(vol: Real, T: Real) -> Real
            requires (vol * sqrt(T) > 0.0)
        { vol }
        """
    )
    warnings = lint_module(mod)
    assert len(warnings) == 1
    msg = warnings[0].message
    # Must say what the problem is
    assert "requires" in msg
    assert "sqrt" in msg
    # Must suggest at least one migration path
    assert "assume" in msg
