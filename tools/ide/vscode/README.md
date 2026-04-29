# Monogate Forge — VS Code extension

EML-lang language support for VS Code:

- **Syntax highlighting** for `.eml` files (TextMate grammar in `syntaxes/`)
- **Inline profile lenses** above every `fn` header, e.g.
  `chain_order=2  p2-d4-w2-c0  4 MAC + 1 trig (8cy @ 32-bit)  drift=MEDIUM`
- **Chain-order diagnostics** on save (red squiggles + Problems-tab)
- **Compile commands** (palette + right-click): C / Rust / Lean / Verilog / all

The extension shells out to `python tools/cli/main.py` — the Python CLI
is the source of truth. No parsing logic is reimplemented in TypeScript.

## Local install (dev)

```bash
cd tools/ide/vscode
npm install
npm run compile
```

Then in VS Code: `F1 → Developer: Install Extension from Location…` and
point at this directory. Open any `.eml` file from a monogate-forge
checkout — the lenses and diagnostics light up automatically on save.

## Architecture

| File | Role |
|------|------|
| `src/extension.ts` | Entry point, registers providers + commands |
| `src/profileProvider.ts` | CodeLens provider — runs `--profile-only`, parses dashboard |
| `src/diagnostics.ts` | DiagnosticCollection — surfaces type-errors as squiggles |
| `language-configuration.json` | Bracket auto-close, comment toggle |
| `syntaxes/eml.tmLanguage.json` | TextMate grammar |

Both providers walk up from the open file to find the repo root
(identified by `tools/cli/main.py` + `lang/spec/SPEC.md`). Files outside
a forge checkout are silently ignored.
