# Changelog

All notable changes to the Monogate Forge VS Code extension are
documented here. Versioning follows the conventions in `PUBLISH.md`.

## [0.10.0] — 2026-05-04

LSP responsiveness + hover quality. The extension itself ships no
new commands, no new snippets, and no grammar changes — every
improvement is delivered through the upstream `eml-lsp` server
that the extension spawns from `pip install monogate-forge`. To
get the new behavior end-to-end, users must upgrade
`monogate-forge` to **≥ 0.2.0** (forthcoming on PyPI). Pinned to
0.9.x of the extension, the experience continues to work; pinned
to 0.10.0 against an older `monogate-forge`, the experience is
identical to 0.9.0 (no regressions, no surfaced new behavior).

### Changed (delivered through upstream LSP)

- **Hover cards now carry real numbers.** Pre-0.10.0 the chain
  order, depth, cost class, fp16 drift risk, and FPGA estimate
  fields displayed `?` because the parser left
  `EMLFunction.profile = None` and the LSP didn't run the
  profiler on demand. The upstream LSP now lazily profiles on
  first hover per source revision and surfaces every field
  including stability warnings.
- **Per-keystroke responsiveness.** The LSP previously reparsed
  the open document for every hover, completion, definition,
  references, document-symbol, and document-link request. It now
  caches a parsed module per `(uri, source-hash)` and seeds the
  cache from the diagnostics pass, collapsing N reparses per
  request into one per source revision.

### Notes

- No publish-blocker changes between 0.9.0 and 0.10.0 in the
  extension's own TypeScript — `out/extension.js` is identical
  byte-for-byte under the same tsconfig. The version bump exists
  to track the upstream `monogate-forge` minor that contains the
  hover/cache improvements.
- The `pip install monogate-forge` line in the README and welcome
  card is unchanged. Users who don't have the CLI installed get
  the same Free editor experience (syntax + snippets + completion
  + outline) as before.

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
