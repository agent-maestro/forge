# Getting Started

Monogate Forge is in SCAFFOLD state — the language spec, type
system, and example library are in place, but no backend produces
working output yet. This guide describes what's planned for users
once Phase 2 ships.

## Install (planned)

```bash
pip install monogate-forge
```

## Hello world (planned)

Create `hello.eml`:

```eml
module hello;

fn answer() -> f64
  where chain_order <= 0
{
    42.0
}
```

Compile to C:

```bash
eml-compile hello.eml --target c -o hello.c
gcc hello.c -lm -o hello
./hello   # prints 42.0
```

Compile the same source to Verilog:

```bash
eml-compile hello.eml --target verilog -o hello.v
# .v file ready for Vivado / Yosys / Verilator
```

## Today (SCAFFOLD)

- `eml-compile --version` works.
- The 10 example `.eml` files in `lang/spec/grammar/examples/`
  are syntactically valid (against `lang/spec/grammar/eml_lang.g4`).
- Backends print "SCAFFOLD" instead of producing output.

See `roadmap/phases/` for the implementation sequence.
