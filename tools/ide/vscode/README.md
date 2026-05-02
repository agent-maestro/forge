# Monogate Forge — VS Code extension

EML-lang language support for VS Code:

- **Syntax highlighting** for `.eml` files (TextMate grammar in `syntaxes/`)
  - Keywords: `module use as const type fn extern let mut where requires ensures while if else …`
  - Built-in transcendentals: `exp ln log sin cos tan sqrt pow eml abs clamp asin acos atan sinh cosh tanh`
  - Stdlib activations + growth: `sigmoid softplus relu leaky_relu gelu swish logistic gompertz lerp …`
  - libmonogate runtime symbols: any `mg_*` call (matches the C / Rust runtime + the SuperBEST `mg_*_route` variants emitted by the `ml_routing` optimizer pass)
- **Inline profile lenses** above every `fn` header, e.g.
  `chain_order=2  p2-d4-w2-c0  4 MAC + 1 trig (8cy @ 32-bit)  drift=MEDIUM`
- **Chain-order diagnostics** on save (red squiggles + Problems-tab)
- **Compile commands** (palette + right-click) for all 22 backends:
  - **Software**: C, C++, Rust, Go, Java, Kotlin, Python, MATLAB
  - **Bytecode**: LLVM IR, WebAssembly
  - **Hardware**: Verilog, SystemVerilog, VHDL, Chisel
  - **Safety-critical**: Ada/SPARK, AUTOSAR, AADL, ROS 2
  - **Verification**: Lean 4, Coq, Isabelle/HOL
  - **Smart contracts**: Solidity

The extension shells out to the Forge CLI — the Python CLI is the
source of truth. No parsing logic is reimplemented in TypeScript.

## Install (users)

```bash
pip install 'monogate-forge[lsp]'
```

The `[lsp]` extra adds the `eml-lsp` Language Server (pygls)
that gives you **errors-as-you-type** + **hover-for-types**.
Without it the extension still works -- it falls back to
save-triggered diagnostics from `eml-compile`. Both binaries
go on `PATH`; install the extension from the VS Code
marketplace, open any `.eml` file anywhere on disk, lenses +
diagnostics light up. No clone of `monogate-forge` required.

If you only want the CLI without the LSP, drop the `[lsp]`:
```bash
pip install monogate-forge
```

## Install (contributors editing the language itself)

```bash
git clone https://github.com/agent-maestro/monogate-forge
cd monogate-forge/tools/ide/vscode
npm install
npm run compile
```

Then in VS Code: `F1 → Developer: Install Extension from Location…`
and point at this directory. The extension auto-detects whether
you're editing inside a forge checkout (uses `python tools/cli/main.py`
so your unbuilt local changes apply) or outside one (uses the
installed `eml-compile`).

## Architecture

| File | Role |
|------|------|
| `src/extension.ts` | Entry point — registers providers + commands |
| `src/forgeCli.ts` | Resolves `eml-compile` and `eml-lsp` on PATH |
| `src/lspClient.ts` | Spawns `eml-lsp` and connects vscode-languageclient |
| `src/profileProvider.ts` | CodeLens provider — runs `--profile-only`, parses dashboard |
| `src/diagnostics.ts` | Save-triggered diagnostics fallback (used when LSP unavailable) |
| `language-configuration.json` | Bracket auto-close, comment toggle |
| `syntaxes/eml.tmLanguage.json` | TextMate grammar |

The CLI discovery happens once per session (cached), then every
invocation prefers the installed binary and falls back to a forge
clone above the open file. If neither is available, the user gets
a one-shot install hint with a "Copy command" button.
