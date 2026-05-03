"""``eml-repl`` -- interactive REPL for EML expressions.

A line at a time: parse an EML expression, profile it, and print
chain order + cost class + fp16 drift risk. Optional `:target`
command also compiles the expression to one of the software backends
(python, rust, c, javascript, lean, ...) and prints the result.

Free variables in the input are inferred by scanning identifiers
that are not in `lang.parser.ast_nodes.BUILTIN_NAMES` and not
language keywords. Override with `:vars x y z` when the inference
gets confused (e.g. `pow(x, e)` where `e` is meant as a free var,
not Euler's number).

Design contract: every input must be a single EML expression, not a
full module. The REPL wraps the line as
``module _repl; fn _expr(<vars>: Real) -> Real { <expr> }`` before
handing to the parser. Multi-line / function / module definitions
are out of scope for v1.
"""
from __future__ import annotations

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Callable, Iterable

from lang.parser import ParseError, parse_source
from lang.parser.ast_nodes import BUILTIN_NAMES
from lang.profiler import Profiler


PROMPT = ">>> "

# Keywords / type names the lexer treats as reserved so they
# shouldn't be inferred as free variables.
_KEYWORDS = frozenset({
    "fn", "let", "if", "then", "else", "while", "for", "in",
    "return", "true", "false", "mut", "module", "use", "where",
    "requires", "ensures", "result", "Real", "Int", "Bool",
})

# Identifiers we silently skip during free-var inference.
_NON_VARS = BUILTIN_NAMES | _KEYWORDS

_HELP = """\
Commands:
  :target <name>      compile to a backend (python, rust, c, javascript,
                      lean, ...; pass empty to clear)
  :vars  x y z        override inferred free vars
  :auto               revert to auto-inferred vars
  :show               re-print the last result
  :help               this message
  :quit  /  :q        exit (Ctrl-D / Ctrl-C also exit)

Type an EML expression to evaluate, e.g.
  >>> sin(x) * exp(-t)
"""

_BANNER = (
    "EML REPL  --  type :help for commands, :q to quit.  "
    "Single expressions only.\n"
)


# ────────────────────────── State ──────────────────────────


@dataclass
class ReplState:
    target: str | None = None
    vars_override: tuple[str, ...] | None = None
    last_expr: str | None = None
    last_report: str | None = None


# ──────────────────────── Pure helpers ─────────────────────


_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


def infer_vars(expr: str) -> list[str]:
    """Return identifiers in expr that look like free vars.

    Order-preserving and dedup'd. Skips BUILTIN_NAMES and keywords.
    """
    out: list[str] = []
    seen: set[str] = set()
    for ident in _IDENT_RE.findall(expr):
        if ident in _NON_VARS:
            continue
        if ident in seen:
            continue
        seen.add(ident)
        out.append(ident)
    return out


def wrap_expr(expr: str, vars_: Iterable[str]) -> str:
    """Wrap an EML expression in a synthetic single-fn module."""
    params = ", ".join(f"{v}: Real" for v in vars_)
    return f"module _repl;\nfn _expr({params}) -> Real {{ {expr} }}\n"


# ───────────────────────── Backends ─────────────────────────

# Backend dispatch. Each entry returns the compiled source as a
# string. Lazy imports keep `eml-repl` startup snappy.

def _python_backend(mod):
    from software.backends.python_backend import PythonBackend
    return PythonBackend().compile(mod)


def _rust_backend(mod):
    from software.backends.rust_backend import RustBackend
    return RustBackend().compile(mod)


def _c_backend(mod):
    from software.backends.c_backend import CBackend
    return CBackend().compile(mod)


def _javascript_backend(mod):
    from software.backends.javascript_backend import JavaScriptBackend
    return JavaScriptBackend().compile(mod)


def _lean_backend(mod):
    from software.verification.lean.LeanBackend import LeanBackend
    return LeanBackend().compile_module(mod)


_BACKENDS: dict[str, Callable] = {
    "python": _python_backend,
    "rust": _rust_backend,
    "c": _c_backend,
    "javascript": _javascript_backend,
    "lean": _lean_backend,
}


def compile_to_target(mod, target: str) -> str:
    fn = _BACKENDS.get(target.lower())
    if fn is None:
        raise ValueError(
            f"unknown target {target!r}. "
            f"Known: {', '.join(sorted(_BACKENDS))}"
        )
    return fn(mod)


# ─────────────────────── Evaluation ────────────────────────


def evaluate(expr: str, state: ReplState) -> str:
    """Profile + optionally compile the expression. Returns a report."""
    if state.vars_override is not None:
        vars_ = list(state.vars_override)
    else:
        vars_ = infer_vars(expr)
    src = wrap_expr(expr, vars_)
    try:
        mod = parse_source(src, "<repl>")
    except ParseError as e:
        return f"parse error: {e}"
    try:
        Profiler().profile_module(mod)
    except Exception as e:  # noqa: BLE001
        return f"profile error: {type(e).__name__}: {e}"

    fn = mod.functions[0]
    profile = getattr(fn, "profile", {}) or {}
    chain = profile.get("chain_order", "?")
    cclass = profile.get("cost_class", "?")
    drift = profile.get("fp16_drift_risk", "?")

    lines = [
        f"  vars       : {' '.join(vars_) if vars_ else '<none>'}",
        f"  chain_order: {chain}",
        f"  cost_class : {cclass}",
        f"  drift_risk : {drift}",
    ]

    if state.target:
        try:
            backend_src = compile_to_target(mod, state.target)
        except Exception as e:  # noqa: BLE001
            lines.append(f"  --- {state.target} ---")
            lines.append(f"  backend error: {type(e).__name__}: {e}")
        else:
            lines.append(f"  --- {state.target} ---")
            lines.append(textwrap.indent(backend_src.rstrip(), "  "))

    return "\n".join(lines)


# ───────────────────────── Commands ────────────────────────


def handle_command(line: str, state: ReplState) -> str | None:
    """Handle a `:command` line. Return reply text, or None to exit."""
    parts = line[1:].split()
    if not parts:
        return ""
    cmd, *args = parts
    cmd = cmd.lower()

    if cmd in {"q", "quit", "exit"}:
        return None
    if cmd == "help":
        return _HELP
    if cmd == "target":
        if not args:
            state.target = None
            return "target cleared (profile-only mode)"
        target = args[0].lower()
        if target not in _BACKENDS:
            return (f"unknown target {target!r}. "
                    f"Known: {', '.join(sorted(_BACKENDS))}")
        state.target = target
        return f"target = {target}"
    if cmd == "vars":
        if not args:
            return ("usage: :vars x y z   (override inferred free vars). "
                    "Use :auto to revert.")
        state.vars_override = tuple(args)
        return f"vars override = {' '.join(args)}"
    if cmd == "auto":
        state.vars_override = None
        return "vars override cleared (auto-infer)"
    if cmd == "show":
        return state.last_report or "(no last result)"

    return f"unknown command :{cmd}  (try :help)"


# ──────────────────────── Main loop ────────────────────────


def repl(input_fn=input, output_fn=print) -> int:
    """The interactive loop, parameterised on input/output for testing."""
    state = ReplState()
    output_fn(_BANNER, end="")
    while True:
        try:
            line = input_fn(PROMPT)
        except EOFError:
            output_fn("")
            return 0
        except KeyboardInterrupt:
            output_fn("")
            return 0
        line = line.strip()
        if not line:
            continue
        if line.startswith(":"):
            reply = handle_command(line, state)
            if reply is None:
                return 0
            if reply:
                output_fn(reply)
        else:
            report = evaluate(line, state)
            state.last_expr = line
            state.last_report = report
            output_fn(report)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="eml-repl",
        description=(
            "Interactive REPL for EML expressions. Each line is "
            "profiled (chain order, cost class, drift risk) and "
            "optionally compiled to a backend via :target."
        ),
    )
    p.add_argument("--target", default=None,
                    help="Start with backend compilation enabled.")
    p.add_argument("--version", action="version",
                    version="eml-repl 0.1.0")
    args = p.parse_args(argv)

    # Pre-set state from args via a thin shim around `repl`.
    if args.target:
        state = ReplState(target=args.target.lower())
        if state.target not in _BACKENDS:
            print(f"unknown --target {args.target!r}. "
                  f"Known: {', '.join(sorted(_BACKENDS))}",
                  file=sys.stderr)
            return 2

        def _input(prompt):
            return input(prompt)

        # Inline re-implementation that respects the seeded state.
        print(_BANNER, end="")
        print(f"target = {state.target}")
        while True:
            try:
                line = _input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            line = line.strip()
            if not line:
                continue
            if line.startswith(":"):
                reply = handle_command(line, state)
                if reply is None:
                    return 0
                if reply:
                    print(reply)
            else:
                report = evaluate(line, state)
                state.last_expr = line
                state.last_report = report
                print(report)

    return repl()


if __name__ == "__main__":
    raise SystemExit(main())
