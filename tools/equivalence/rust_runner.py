"""Rust target runner for the equivalence harness.

Compiles a generated EML module to Rust, links it against the
local `monogate-sys` crate, builds a tiny dispatcher binary, and
runs each test vector through it via subprocess.

Toolchain detection: `cargo` and `rustc` must both be on PATH.
When either is missing, `cargo_available()` returns False and the
harness reports the Rust target as `available=False`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from lang.parser.ast_nodes import EMLFunction, EMLModule
from software.backends.rust_backend import RustBackend


def cargo_available() -> bool:
    """True iff cargo + rustc are both on PATH."""
    return shutil.which("cargo") is not None and \
           shutil.which("rustc") is not None


# Path to the in-repo monogate-sys crate.
_MONOGATE_SYS_DIR = (
    Path(__file__).resolve().parents[2]
    / "software" / "runtime" / "rust"
)


class RustRunnerError(RuntimeError):
    """Raised on cargo build / run failure."""


class RustRunner:
    """Holds a built dispatcher crate and runs vectors through it.

    Build is lazy: the first `run()` call invokes `cargo build
    --release`. Subsequent calls reuse the binary.
    """

    def __init__(
        self,
        module: EMLModule,
        *,
        timeout_s: float = 120.0,
        optimize: bool = True,
    ) -> None:
        if not cargo_available():
            raise RustRunnerError("cargo / rustc not on PATH")
        # Apply the optimizer to the module ONCE up front when
        # optimize=True, so the lib.rs source AND the dispatcher's
        # function-name list are in sync (the optimizer's tree-
        # shaker pass can drop unused imported functions, and the
        # dispatcher must not reference dropped names).
        if optimize:
            from lang.optimizer import optimize_module
            self.module = optimize_module(module)
        else:
            self.module = module
        self.timeout_s = timeout_s
        self.optimize = optimize
        self._tmp = tempfile.TemporaryDirectory(prefix="forge_rust_")
        self.crate_dir = Path(self._tmp.name)
        self._binary: Path | None = None
        self._build_crate()

    def __enter__(self) -> "RustRunner":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._tmp.cleanup()
        except OSError:
            # Windows can hold .exe locks briefly after cargo exits.
            pass

    # ── Build ─────────────────────────────────────────────────

    def _build_crate(self) -> None:
        # We already applied optimize_module() in __init__ when
        # self.optimize is True, so the backend should NOT optimize
        # again -- doing so would deepcopy the module + re-run all
        # passes (correct but redundant). Pass optimize=False here
        # to skip the duplicate work.
        rust_src = RustBackend(optimize=False).compile(self.module)
        # Strip the `use monogate_sys::*;` line and re-add inside
        # `lib.rs`. We create both lib.rs (the generated code) and
        # main.rs (the dispatcher).
        (self.crate_dir / "src").mkdir(parents=True, exist_ok=True)
        (self.crate_dir / "src" / "lib.rs").write_text(
            rust_src, encoding="utf-8",
        )
        (self.crate_dir / "src" / "main.rs").write_text(
            self._render_dispatcher(), encoding="utf-8",
        )
        (self.crate_dir / "Cargo.toml").write_text(
            self._render_cargo_toml(), encoding="utf-8",
        )

    def _render_cargo_toml(self) -> str:
        # Use forward slashes so the path works on both Windows and
        # POSIX cargo.
        sys_path = str(_MONOGATE_SYS_DIR).replace("\\", "/")
        crate_name = "forge_eq_test"
        return (
            f"[package]\n"
            f"name = \"{crate_name}\"\n"
            f"version = \"0.0.1\"\n"
            f"edition = \"2021\"\n"
            f"\n"
            f"[lib]\n"
            f"name = \"{crate_name}\"\n"
            f"path = \"src/lib.rs\"\n"
            f"\n"
            f"[[bin]]\n"
            f"name = \"runner\"\n"
            f"path = \"src/main.rs\"\n"
            f"\n"
            f"[dependencies]\n"
            f"monogate-sys = {{ path = \"{sys_path}\" }}\n"
            f"\n"
            f"[profile.release]\n"
            f"opt-level = 1\n"
            f"lto = false\n"
        )

    def _render_dispatcher(self) -> str:
        """A `main.rs` that takes <fn_name> <args...> on argv,
        dispatches to the named function, and prints the result(s)
        in space-separated form on a single stdout line."""
        crate_name = "forge_eq_test"
        arms: list[str] = []
        for fn in self.module.functions:
            arity = len(fn.params)
            arg_calls = ", ".join(
                f"nums[{i}]" for i in range(arity)
            )
            if fn.return_tuple_types:
                # The Rust backend emits a named struct with `eN`
                # fields, not anonymous tuple syntax -- so we
                # access fields as `r.e0`, `r.e1`, ...
                placeholders = " ".join(
                    "{}" for _ in fn.return_tuple_types
                )
                tuple_args = ", ".join(
                    f"r.e{i}" for i in range(len(fn.return_tuple_types))
                )
                body = (
                    f"            let r = {crate_name}::{fn.name}"
                    f"({arg_calls});\n"
                    f"            println!(\"{placeholders}\","
                    f" {tuple_args});"
                )
            else:
                body = (
                    f"            let r = {crate_name}::{fn.name}"
                    f"({arg_calls});\n"
                    f"            println!(\"{{}}\", r);"
                )
            arms.append(
                f"        \"{fn.name}\" => {{\n{body}\n        }}"
            )
        arms_block = "\n".join(arms)
        # Pull every const into the dispatcher's namespace just so
        # nothing is unused -- libs flagged as `unused_imports` get
        # silenced via the `#![allow(...)]` already in the gen.
        return (
            "use std::env;\n"
            "use std::process::exit;\n"
            "\n"
            "fn main() {\n"
            "    let argv: Vec<String> = env::args().collect();\n"
            "    if argv.len() < 2 {\n"
            "        eprintln!(\"usage: runner <fn> <args...>\");\n"
            "        exit(2);\n"
            "    }\n"
            "    let fname = &argv[1];\n"
            "    let nums: Vec<f64> = argv[2..].iter()\n"
            "        .map(|s| s.parse::<f64>()\n"
            "            .expect(\"non-numeric arg\"))\n"
            "        .collect();\n"
            "    match fname.as_str() {\n"
            f"{arms_block}\n"
            "        other => {\n"
            "            eprintln!(\"unknown fn: {}\", other);\n"
            "            exit(3);\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

    def _ensure_built(self) -> Path:
        if self._binary is not None:
            return self._binary
        r = subprocess.run(
            ["cargo", "build", "--release", "--bin", "runner"],
            cwd=str(self.crate_dir),
            capture_output=True, text=True, timeout=self.timeout_s,
        )
        if r.returncode != 0:
            # Filter to only error/warning *headers* + their first
            # context line so the message fits without truncating
            # the actual diagnostic.
            stderr_lines = [
                ln for ln in r.stderr.splitlines()
                if ln.lstrip().startswith(("error", "warning: aborting"))
                or "could not compile" in ln
                or "rustc " in ln
            ]
            stderr_summary = "\n".join(stderr_lines[-30:]) or r.stderr[-2000:]
            raise RustRunnerError(
                f"cargo build failed:\n--- ERRORS ---\n{stderr_summary}"
            )
        exe = self.crate_dir / "target" / "release" / (
            "runner.exe" if sys.platform == "win32" else "runner"
        )
        if not exe.exists():
            raise RustRunnerError(
                f"cargo build succeeded but binary not found at {exe}",
            )
        self._binary = exe
        return exe

    # ── Run ───────────────────────────────────────────────────

    def call(
        self,
        function_name: str,
        vectors: Iterable[tuple[float, ...]],
    ) -> list[float | tuple[float, ...]]:
        """Invoke `function_name` on every vector and return its
        outputs in order. Single-output functions return floats;
        tuple-output functions return float-tuples."""
        binary = self._ensure_built()

        fn = next(
            (f for f in self.module.functions if f.name == function_name),
            None,
        )
        if fn is None:
            raise RustRunnerError(
                f"unknown function {function_name!r} in module"
                f" {self.module.name!r}",
            )
        is_tuple = bool(fn.return_tuple_types)

        out: list = []
        for vec in vectors:
            cmd = [str(binary), function_name] + [
                _format_arg(x) for x in vec
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout_s,
            )
            if r.returncode != 0:
                raise RustRunnerError(
                    f"runner exited {r.returncode} on "
                    f"{function_name}({vec}):\n{r.stderr[:500]}"
                )
            line = r.stdout.strip()
            try:
                parts = [float(p) for p in line.split()]
            except ValueError as e:
                raise RustRunnerError(
                    f"non-numeric output from {function_name}({vec}):"
                    f" {line!r}",
                ) from e
            if is_tuple:
                out.append(tuple(parts))
            else:
                if len(parts) != 1:
                    raise RustRunnerError(
                        f"expected 1 output from {function_name}, "
                        f"got {len(parts)}",
                    )
                out.append(parts[0])
        return out


def _format_arg(x: float) -> str:
    """Print a float in a Rust-parseable form. Special values stay
    in IEEE form (NaN, +inf) so cargo can re-parse them."""
    if x != x:
        return "NaN"
    if x == float("inf"):
        return "inf"
    if x == float("-inf"):
        return "-inf"
    return repr(float(x))
