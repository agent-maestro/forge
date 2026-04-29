# CLI reference — `eml-compile`

> The complete surface of the front-door CLI. For the
> `groff(1)`-rendered version, run `eml-compile manpage`.

---

## Synopsis

```
eml-compile [--target TARGET] [-o OUTPUT] [--profile-only]
            [--allocate] [--fpga-target TARGET]
            [--fmt [--write | --check]]
            [--explain [--json] [--backend-stats]]
            [--no-optimize]
            FILE.eml

eml-compile init [DIRECTORY] [--name NAME] [--force]

eml-compile manpage
```

---

## Targets

| Target    | Output          | Notes |
|-----------|-----------------|-------|
| `c`       | C99 source      | Links `libmonogate.h`. Compiles with `gcc -O2 -Wall -Werror`. |
| `rust`    | Rust source     | Consumes the `monogate-sys` crate. `cargo clippy -D warnings` clean. |
| `python`  | Python source   | Uses `math.*` only — no third-party deps. |
| `llvm`    | LLVM IR text    | Portable IR; compile with `llc` / `clang`. |
| `wasm`    | wasm32 bytecode | Lowers via LLVM IR. Falls back to IR text when no `llc`/`clang` on PATH. |
| `verilog` | Synthesizable Verilog | Uses `hardware/modules/transcendental/` library. |
| `vhdl`    | VHDL-2008       | Same module shape as Verilog target. |
| `chisel`  | Chisel 3 / Scala| Generates FIRRTL via the chisel3 toolchain. |
| `lean`    | Lean 4 source   | Emits theorems for `@verify(lean, ...)` blocks only. |
| `all`     | All of the above | `-o` is interpreted as a directory. |

Targets that cannot apply (e.g. `verilog` on a module with no
`@target(fpga)` functions) skip cleanly when used with `--target all`.

---

## Flags

### Core

- **`--target {c,rust,python,llvm,wasm,verilog,vhdl,chisel,lean,all}`**
  Backend to invoke. Without a target, the CLI prints the profile
  summary and exits.
- **`-o, --output PATH`** Write to PATH. With `--target all`, PATH
  is treated as a directory.
- **`--no-optimize`** Bypass the 5-pass optimizer pipeline. Useful
  when comparing optimized vs unoptimized output.
- **`--version`** Print the version string and exit.

### Profile

- **`--profile-only`** Print Pfaffian profile summary; emit nothing.
- **`--explain`** Per-function optimizer diff (which passes fired,
  before/after node counts, SuperBEST family, CSE bindings).
- **`--json`** With `--explain`, emit machine-readable JSON.
- **`--backend-stats`** With `--explain`, also compile to every
  backend and report per-target source size.

### FPGA / hardware

- **`--allocate`** Run the FPGA allocator (Patent #14) and print the
  plan. Requires at least one `@target(fpga, ...)` function.
- **`--fpga-target TARGET`** FPGA target identifier. Choices:
  - `xilinx.artix7` (default)
  - `lattice.ice40`
  - `lattice.ecp5`
  - `intel.cyclone10`
  - `asic.sky130`

### Formatter

- **`--fmt`** Print canonically-formatted source to stdout.
- **`--write`** With `--fmt`, rewrite the file in place if changed.
- **`--check`** With `--fmt`, exit 1 if the file is not in canonical
  form. CI gate.

---

## Subcommands

### `eml-compile init [DIR] [--name NAME] [--force]`

Scaffold a new EML-lang project in `DIR` (default: current
directory). Files created:

```
DIR/
  pyproject.toml          # dependency declaration
  main.eml                # starter program
  .vscode/settings.json   # eml-fmt-on-save + diagnostic wiring
  .gitignore
```

`--name` overrides the project name (default: directory name).
`--force` overwrites existing files.

### `eml-compile manpage`

Print the man page in roff(7) format. Pipe to a file and install
into your distribution's man path:

```
eml-compile manpage > /usr/local/share/man/man1/eml-compile.1
mandb
```

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Compile error, parse error, or invalid arguments |
| 2 | Target requested is not built yet (legacy; no current targets) |

---

## Examples

```
# Profile a file and exit
eml-compile sigmoid.eml --profile-only

# Compile to C
eml-compile sigmoid.eml --target c -o sigmoid.c

# Run every backend at once
eml-compile sigmoid.eml --target all -o build/

# Allocate FPGA resources for an iCE40 target
eml-compile motor_foc.eml --allocate --fpga-target lattice.ice40

# Format-on-save (CI gate)
eml-compile mymodule.eml --fmt --check

# Scaffold a new project
eml-compile init my_project --name my_project
```
