# Monogate Forge — VS Code extension

EML-lang language support for VS Code. **Free forever** for writing
EML; install the licensed Forge CLI to unlock compile, analysis,
and verification.

## What you get for free (no CLI required)

- **Syntax highlighting** for `.eml` files (TextMate grammar)
  - Keywords: `module use as const type fn extern let mut where requires ensures while if else …`
  - Built-in transcendentals: `exp ln log sin cos tan sqrt pow eml abs clamp asin acos atan sinh cosh tanh`
- **Snippets** for the common patterns: `fn`, `fnverify`, `module`, `usestdlib`, `requires`, `ensures`, `targetfpga`, `verify`, plus the @verify Hoare-contract template with `requires`/`ensures` pre-filled
- **Bracket auto-close, comment toggle, indent rules**
- **Static completion**: keyword + builtin suggestions
- **Outline view**: regex-driven document symbols (fn, const, type)

## What unlocks with the Forge CLI

The licensed CLI (`monogateforge.com/get-started`) ships an LSP
server and the compiler. Once installed, the extension auto-detects
both binaries on PATH and lights up:

- **Real-time diagnostics** — lex, parse, and chain-order errors as you type
- **Hover** — chain order, cost class, FPGA cycles for fns; structural class + chain delta for builtin transcendentals
- **Rich completion** — local decls + 87 stdlib symbols (math, ml, signal, linalg, control, constants)
- **Cross-file goto-definition** — into bundled stdlib + sibling user `.eml` files
- **Find all references + workspace-wide rename** (rename blocks builtins; validates new names)
- **Document symbols + outline** — typed via the real parser, not regex
- **Document links** — ctrl-click `use stdlib::*` clauses to jump to source
- **Format-on-save** — re-emit canonical EML in-process via the LSP
- **Workspace symbol search** (Ctrl+T) — fuzzy match across every indexed file
- **FPGA status bar** — LUT / DSP / cycle estimates per file
- **Inline profile lenses** — chain order + cost class above each fn header
- **Compile commands** for all 36 targets (palette + right-click)

The compile commands are tier-gated:

| Tier | Targets |
|---|---|
| Free | C, C++, Rust, Python, Go, Java, Kotlin, C#, JavaScript, WebAssembly, MATLAB, Lean 4, zkproof |
| Pro  | Verilog, SystemVerilog, VHDL, Chisel, LLVM IR, HLSL, GLSL, GLSL ES, WGSL, Metal, Swift, Ada/SPARK, AUTOSAR, AADL, ROS 2, Coq, Isabelle/HOL, Solidity, Luau, GDScript, SPICE, KiCad, JLCPCB |

## Install

1. Install this extension from the VS Code marketplace.
2. Open any `.eml` file — syntax + snippets + outline work immediately.
3. To enable real-time diagnostics, hover, completion, format, and
   compile-to-anything: visit **<https://monogateforge.com/get-started>**
   for the licensed CLI.

## Architecture

| File | Role |
|------|------|
| `src/extension.ts` | Entry point — registers providers + commands |
| `src/forgeCli.ts` | Resolves `eml-compile` and `eml-lsp` on PATH |
| `src/lspClient.ts` | Spawns `eml-lsp` and connects vscode-languageclient |
| `src/editorOnly.ts` | Static completion + regex outline (free tier) |
| `src/profileProvider.ts` | CodeLens provider — runs `--profile-only`, parses dashboard |
| `src/diagnostics.ts` | Save-triggered diagnostics fallback when LSP unavailable |
| `language-configuration.json` | Bracket auto-close, comment toggle |
| `syntaxes/eml.tmLanguage.json` | TextMate grammar |
| `snippets/eml.json` | Snippet library |

The LSP discovery happens once per session (cached). When the LSP
isn't available, the extension falls back to: static completion
provider, regex outliner, and a one-shot install hint pointing at
the licensing page (no nag — appears once per session).
