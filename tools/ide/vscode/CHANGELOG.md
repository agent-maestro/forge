# Changelog

All notable changes to the Monogate Forge VS Code extension are
documented here. Versioning follows the conventions in `PUBLISH.md`.

## [0.9.0] — 2026-05-02

Truth-gap close-out for the launch sprint. The extension's
description has claimed "32-target compile" since v0.8.x, but only
22 targets were actually exposed in the command palette. This
release closes that gap and adds multi-select compile.

### Added

- **10 new compile commands** — `csharp`, `javascript`, `hlsl`,
  `glsl`, `glsles`, `wgsl`, `metal`, `swift`, `gdscript`, `luau`.
  Every shipping Forge backend is now reachable from the palette
  and the right-click menu.
- **Tier badges in the QuickPick** — every entry shows `· Free`
  or `· Pro` so users see licensing before they hit a token check.
- **"Compile to multiple targets..."** — multi-select QuickPick
  for shipping bundles like Unity (HLSL + C# + WGSL) or Apple
  (Metal + Swift) in one go. Each selected target gets its own
  terminal so output stays separable.
- **9 new snippets** — `fnphysics`, `fnease`, `fnfresnel`,
  `easecubic`, `fnconsttime`, `targetmulti`, `extern`,
  `verifycoq`, `verifyisabelle`. Aligned with the gaming and
  cryptography kernel libraries that just shipped in
  `monogate-forge` 0.1.0.

### Changed

- **`ALL_TARGETS` table** in `extension.ts` now carries explicit
  `Tier` metadata — `Free`, `Pro`, or `Bulk`. The picker derives
  badges from this single source of truth.
- **Package keywords** include the new shader / engine targets
  (`metal`, `swift`, `hlsl`, `glsl`, `wgsl`, `gdscript`, `luau`)
  so the marketplace search picks up the extension for Unity /
  Unreal / Godot / Roblox / Apple developers.
- **Editor-context menu** order: pick → pickMany → all → profile.
  The single-target pick stays the default since it's still the
  most common flow.

### Notes

- The compile path itself is unchanged — each target still shells
  out to `eml-compile <file> --target <id>`. Pro-tier targets
  fail cleanly with the existing license error when no token is
  loaded; the badge is purely a UI hint.

## [0.8.1] — earlier

LSP polish (formatting + workspace/symbol), publisher rename to
`Monogate`, repo URL fixes, open-core editor fallbacks.

## [0.8.0] — earlier

Chain-order on hover, LSP MVP wiring, completion providers,
goto-definition into bundled stdlib, FPGA status bar.
