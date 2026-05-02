# Marketplace publish playbook

Mechanical steps to push the extension to the VS Code marketplace
once you have an Azure DevOps PAT under the `Monogate`
publisher.

## One-time setup

### 1. Create the publisher (once per publisher account)

Go to https://marketplace.visualstudio.com/manage and sign in with
the same Microsoft account that owns the Azure DevOps org backing
the PAT. Create a publisher with `id = Monogate` (the
value already wired into `package.json`'s `publisher` field).

### 2. Generate the PAT

In Azure DevOps (`dev.azure.com/<your-org>`):

- User settings → Personal Access Tokens → New Token
- Organization: All accessible organizations (REQUIRED)
- Scopes: Marketplace → Manage
- Expiration: 1 year (max), set a calendar reminder

Copy the token — Azure shows it once. Store in your password
manager. The publish step will prompt for it (or read from
`VSCE_PAT` env var).

## Each release

```bash
cd tools/ide/vscode

# 1. Bump version in package.json (semver: bug = patch, feature
#    = minor, breaking = major)
#    e.g.  0.3.0  →  0.3.1

# 2. Recompile + repackage
npm install                     # one-time per machine
npm run compile                 # tsc -> out/
npx @vscode/vsce package        # produces .vsix in this dir

# 3. Verify the .vsix locally before publishing
code --install-extension monogate-forge-vscode-0.3.0.vsix
# Open a .eml file from anywhere on disk; lenses + diagnostics
# should light up. Uninstall when done:
code --uninstall-extension Monogate.monogate-forge-vscode

# 4. Publish (will prompt for PAT, or set VSCE_PAT env var)
npx @vscode/vsce publish
# OR for a specific bump:
npx @vscode/vsce publish patch  # 0.3.0 -> 0.3.1
npx @vscode/vsce publish minor  # 0.3.0 -> 0.4.0

# 5. Live at:
#    https://marketplace.visualstudio.com/items?itemName=Monogate.monogate-forge-vscode
```

## What the extension assumes about the user

The extension shells out to `eml-compile`. Document the install
path in the README and at the top of the marketplace page:

```
pip install monogate-forge
```

Without that, the extension still loads (syntax highlighting +
icon work), but the user gets a one-shot info message asking
them to install the CLI. Lenses, diagnostics, and compile
commands are no-ops until then.

## Pre-publish checklist

- [ ] Version bumped in `package.json`
- [ ] CHANGELOG entry added (TODO: file doesn't exist yet)
- [ ] `npm run compile` produces `out/*.js` with no errors
- [ ] `npx @vscode/vsce package` produces a .vsix with **zero
      warnings** (LICENSE present, repository field set,
      .vscodeignore catches src/)
- [ ] Manual install of the .vsix in VS Code → open a .eml file
      from a non-forge directory → lenses appear
- [ ] README has the `pip install monogate-forge` line above the
      fold

## Versioning conventions

- `0.x` → pre-1.0, breaking changes allowed in minor bumps
- Bump **patch** for: bug fixes, README/copy updates, new keywords
  in the grammar
- Bump **minor** for: new compile target, new code lens, new
  command, new configuration property
- Bump **major** when the LSP lands (1.0) — that's a real
  feature-level shift
