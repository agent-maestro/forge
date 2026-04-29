"""C target runner for the equivalence harness.

Compiles a generated EML module to C, links it against
`software/runtime/c/libmonogate.{h,c}`, builds a tiny dispatcher
binary via gcc, and runs each test vector through it.

Mirrors the design of `rust_runner.py`. When gcc isn't on PATH,
`gcc_available()` returns False and the harness reports the C
target as `available=False`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from lang.parser.ast_nodes import EMLModule
from software.backends.c_backend import CBackend


def gcc_available() -> bool:
    return shutil.which("gcc") is not None


_RUNTIME_C_DIR = (
    Path(__file__).resolve().parents[2]
    / "software" / "runtime" / "c"
)


class CRunnerError(RuntimeError):
    pass


class CRunner:
    def __init__(
        self,
        module: EMLModule,
        *,
        timeout_s: float = 60.0,
    ) -> None:
        if not gcc_available():
            raise CRunnerError("gcc not on PATH")
        self.module = module
        self.timeout_s = timeout_s
        self._tmp = tempfile.TemporaryDirectory(prefix="forge_c_")
        self.work_dir = Path(self._tmp.name)
        self._binary: Path | None = None
        self._build()

    def __enter__(self) -> "CRunner":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._tmp.cleanup()
        except OSError:
            pass

    # ── Build ─────────────────────────────────────────────────

    def _build(self) -> None:
        c_src = CBackend().compile(self.module)
        # The generated header includes "libmonogate.h" -- we point
        # the include path at the runtime dir.
        gen_c = self.work_dir / "gen.c"
        gen_c.write_text(c_src, encoding="utf-8")

        main_c = self.work_dir / "main.c"
        main_c.write_text(self._render_main(), encoding="utf-8")

        # libmonogate.c must be in the same TU set so its symbols
        # are linked.
        runtime_c = _RUNTIME_C_DIR / "libmonogate.c"

        binary = self.work_dir / (
            "runner.exe" if sys.platform == "win32" else "runner"
        )
        cmd = [
            "gcc", "-O2", "-std=c11",
            "-Wall", "-Wno-unused-function", "-Wno-unused-variable",
            f"-I{_RUNTIME_C_DIR}",
            str(gen_c), str(main_c), str(runtime_c),
            "-lm",
            "-o", str(binary),
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=self.timeout_s,
        )
        if r.returncode != 0:
            raise CRunnerError(
                f"gcc build failed:\n--- STDERR ---\n{r.stderr[:2000]}"
            )
        self._binary = binary

    def _render_main(self) -> str:
        arms: list[str] = []
        for fn in self.module.functions:
            arity = len(fn.params)
            arg_list = ", ".join(
                f"atof(argv[{2+i}])" for i in range(arity)
            )
            if fn.return_tuple_types:
                # Generated C wraps tuples in a struct; print each
                # field. Field names are r0..rN per the C backend.
                struct_fields = " ".join(
                    "%g" for _ in fn.return_tuple_types
                )
                accessors = ", ".join(
                    f"r.r{i}"
                    for i in range(len(fn.return_tuple_types))
                )
                arms.append(
                    f'        if (strcmp(argv[1], "{fn.name}") == 0) '
                    f'{{\n'
                    f'            {fn.name}_ret r = '
                    f'{fn.name}({arg_list});\n'
                    f'            printf("{struct_fields}\\n", '
                    f'{accessors});\n'
                    f'            return 0;\n'
                    f'        }}'
                )
            else:
                arms.append(
                    f'        if (strcmp(argv[1], "{fn.name}") == 0) '
                    f'{{\n'
                    f'            double r = {fn.name}({arg_list});\n'
                    f'            printf("%.17g\\n", r);\n'
                    f'            return 0;\n'
                    f'        }}'
                )
        arms_block = "\n".join(arms)
        return (
            "#include <stdio.h>\n"
            "#include <stdlib.h>\n"
            "#include <string.h>\n"
            "#include \"gen.c\"\n"
            "\n"
            "int main(int argc, char **argv) {\n"
            "    if (argc < 2) {\n"
            "        fprintf(stderr, "
            "\"usage: runner <fn> <args...>\\n\");\n"
            "        return 2;\n"
            "    }\n"
            f"{arms_block}\n"
            "    fprintf(stderr, \"unknown fn: %s\\n\", argv[1]);\n"
            "    return 3;\n"
            "}\n"
        )

    # ── Run ───────────────────────────────────────────────────

    def call(
        self,
        function_name: str,
        vectors: Iterable[tuple[float, ...]],
    ) -> list[float | tuple[float, ...]]:
        if self._binary is None:
            raise CRunnerError("binary not built")
        fn = next(
            (f for f in self.module.functions if f.name == function_name),
            None,
        )
        if fn is None:
            raise CRunnerError(
                f"unknown function {function_name!r}",
            )
        is_tuple = bool(fn.return_tuple_types)

        out: list = []
        for vec in vectors:
            cmd = [str(self._binary), function_name] + [
                _format_arg(x) for x in vec
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout_s,
            )
            if r.returncode != 0:
                raise CRunnerError(
                    f"runner exited {r.returncode}: {r.stderr[:500]}"
                )
            parts = [float(p) for p in r.stdout.strip().split()]
            if is_tuple:
                out.append(tuple(parts))
            else:
                out.append(parts[0])
        return out


def _format_arg(x: float) -> str:
    if x != x:
        return "nan"
    if x == float("inf"):
        return "inf"
    if x == float("-inf"):
        return "-inf"
    return repr(float(x))
