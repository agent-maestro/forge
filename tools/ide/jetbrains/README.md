# Monogate Forge — JetBrains plugin

IntelliJ-platform support for `.eml` files: file-type registration,
syntax highlighting, and a "Compile to…" action that shells out to
the same `eml-compile` CLI used by the VS Code extension and CI.

## Status

**0.1.0 — scaffold.** Equivalent to the VS Code extension's surface
*before* the inline profile lenses + diagnostics layered on top. The
plugin compiles, registers the `.eml` file type, ships a stub
lexer/parser, and exposes `Tools → Monogate Forge: Compile to…`.

A grammar-driven lexer + per-function CodeVision (chain order, cost
class) lands in 0.2 once the JetBrains-side parser ports across.

## Build

```
cd tools/ide/jetbrains
./gradlew buildPlugin
```

The plugin zip lands in `build/distributions/` and can be installed
via *Settings → Plugins → ⚙ → Install Plugin from Disk*.

For development, `./gradlew runIde` spawns a sandbox IntelliJ with
the plugin pre-installed; opening any `.eml` file there triggers the
file-type registration.

## What this plugin does today

- Registers `.eml` as a recognized file type
- Stub lexer + parser (single-token; structure view is empty)
- Light syntax highlighter that defers to the IntelliJ default
  color scheme for `KEYWORD`, `NUMBER`, `STRING`, etc.
- `Tools → Monogate Forge: Compile to…` action — picks one of the
  9 live backends + `all`, then runs the CLI in the built-in terminal

## Why not full PSI from day one?

The Python `eml-compile` CLI is the source of truth for parsing,
profiling, and error reporting. Replicating that in Kotlin earns
us nothing on day one — the CLI is fast enough that calling it on
save matches the VS Code extension's behavior exactly. We will
port the lexer first (for color), then the parser (for structure
view), then bind diagnostics to the CLI's `--profile-only` JSON
output (for red squiggles).
