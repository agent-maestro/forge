"""Tests for ``tools/cli/repl.py``."""
from __future__ import annotations

import io
from collections import deque

import pytest

from tools.cli.repl import (
    ReplState,
    compile_to_target,
    evaluate,
    handle_command,
    infer_vars,
    repl,
    wrap_expr,
)


# ──────── infer_vars ────────

def test_infer_vars_excludes_builtins():
    assert infer_vars("sin(x) * exp(-t)") == ["x", "t"]


def test_infer_vars_orders_by_first_appearance_and_dedups():
    assert infer_vars("a + b + a + c + b") == ["a", "b", "c"]


def test_infer_vars_excludes_keywords():
    # `if`, `then`, `else`, `let`, `Real` should not be free vars
    expr = "if x > 0.0 then x else -x"
    assert "x" in infer_vars(expr)
    assert "if" not in infer_vars(expr)
    assert "then" not in infer_vars(expr)
    assert "else" not in infer_vars(expr)


def test_infer_vars_empty_for_constant_expr():
    assert infer_vars("1.0 + 2.0 * 3.0") == []


def test_infer_vars_handles_underscore_idents():
    assert infer_vars("x_1 + _y + foo_bar") == ["x_1", "_y", "foo_bar"]


# ──────── wrap_expr ────────

def test_wrap_expr_with_vars():
    src = wrap_expr("a + b", ["a", "b"])
    assert "module _repl;" in src
    assert "fn _expr(a: Real, b: Real) -> Real" in src
    assert "{ a + b }" in src


def test_wrap_expr_no_vars():
    src = wrap_expr("1.0 + 2.0", [])
    assert "fn _expr() -> Real" in src
    assert "{ 1.0 + 2.0 }" in src


# ──────── evaluate (profile + report) ────────

def test_evaluate_simple_expression():
    state = ReplState()
    report = evaluate("x + 1.0", state)
    assert "vars       : x" in report
    assert "chain_order:" in report
    assert "cost_class :" in report
    assert "drift_risk :" in report


def test_evaluate_with_target_includes_backend_output():
    state = ReplState(target="python")
    report = evaluate("x + 1.0", state)
    assert "--- python ---" in report
    # PythonBackend emits a `def _expr` for the wrapped function
    assert "def _expr" in report


def test_evaluate_uses_vars_override():
    state = ReplState(vars_override=("x", "y", "z"))
    # `cos(x)` would normally infer just `x`; override says also y, z
    report = evaluate("cos(x)", state)
    assert "vars       : x y z" in report


def test_evaluate_parse_error_returns_friendly_message():
    state = ReplState()
    report = evaluate("1.0 + )", state)
    assert "parse error" in report.lower()


def test_evaluate_unknown_target_emits_backend_error():
    state = ReplState(target="bogus-target")
    report = evaluate("x + 1.0", state)
    assert "--- bogus-target ---" in report
    assert "backend error" in report


# ──────── compile_to_target ────────

def test_compile_to_target_unknown_raises():
    from lang.parser import parse_source
    from lang.profiler import Profiler
    mod = parse_source("module t; fn f(x: Real) -> Real { x }", "<test>")
    Profiler().profile_module(mod)
    with pytest.raises(ValueError, match="unknown target"):
        compile_to_target(mod, "klingon")


# ──────── handle_command ────────

def test_command_quit_returns_none():
    state = ReplState()
    assert handle_command(":q", state) is None
    assert handle_command(":quit", state) is None
    assert handle_command(":exit", state) is None


def test_command_help_returns_text():
    state = ReplState()
    assert "Commands:" in handle_command(":help", state)


def test_command_target_set_and_clear():
    state = ReplState()
    reply = handle_command(":target python", state)
    assert state.target == "python"
    assert "python" in reply
    reply = handle_command(":target", state)
    assert state.target is None
    assert "cleared" in reply.lower()


def test_command_target_unknown_does_not_set():
    state = ReplState(target="python")
    reply = handle_command(":target klingon", state)
    assert "unknown target" in reply
    assert state.target == "python"  # unchanged


def test_command_vars_override_and_auto():
    state = ReplState()
    reply = handle_command(":vars a b c", state)
    assert state.vars_override == ("a", "b", "c")
    assert "a b c" in reply
    reply = handle_command(":auto", state)
    assert state.vars_override is None


def test_command_vars_no_args_explains_usage():
    state = ReplState()
    reply = handle_command(":vars", state)
    assert "usage:" in reply.lower()
    assert state.vars_override is None  # not changed


def test_command_show_returns_last_report():
    state = ReplState(last_report="foo bar")
    assert handle_command(":show", state) == "foo bar"


def test_command_show_when_empty():
    state = ReplState()
    assert handle_command(":show", state) == "(no last result)"


def test_command_unknown():
    state = ReplState()
    reply = handle_command(":nonsense", state)
    assert ":nonsense" in reply or "unknown" in reply.lower()


# ──────── repl loop integration ────────

def _drive_repl(lines: list[str]) -> str:
    """Run repl() with a scripted input stream; return concatenated output."""
    inputs = deque(lines)
    out = io.StringIO()

    def _input(_prompt):
        if not inputs:
            raise EOFError
        return inputs.popleft()

    def _print(*args, **kwargs):
        end = kwargs.get("end", "\n")
        out.write(" ".join(str(a) for a in args) + end)

    rc = repl(input_fn=_input, output_fn=_print)
    return out.getvalue() + f"[exit={rc}]"


def test_repl_evaluates_then_quits():
    out = _drive_repl(["x + 1.0", ":q"])
    assert "EML REPL" in out
    assert "chain_order" in out
    assert "[exit=0]" in out


def test_repl_target_python_then_eval():
    out = _drive_repl([":target python", "x + 1.0", ":q"])
    assert "target = python" in out
    assert "--- python ---" in out
    assert "def _expr" in out


def test_repl_blank_lines_are_ignored():
    out = _drive_repl(["", "  ", "x + 1.0", ":q"])
    assert out.count("chain_order") == 1


def test_repl_eof_exits():
    # No :q -- repl gets EOFError and exits
    out = _drive_repl(["x + 1.0"])
    assert "chain_order" in out
    assert "[exit=0]" in out
