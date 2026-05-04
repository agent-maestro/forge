# Release process — forge repo

This repo publishes **two** artifacts:

| Artifact | Trigger tag | Workflow | Destination |
|---|---|---|---|
| `monogate-forge` Python package | `monogate-forge-v<version>` | `.github/workflows/release.yml` | PyPI |
| `monogate-forge-vscode` extension | `vscode-v<version>` | `.github/workflows/release-vscode.yml` | VS Code Marketplace |

Both fire on `git push --tags`. Tag patterns are disjoint so a wrong
push can't accidentally fire the wrong job.

---

## One-time setup — PyPI Trusted Publisher

`monogate-forge` is already on PyPI under a token-based publisher.
Switch it to a Trusted Publisher once and the `PYPI_TOKEN` repo
secret can be deleted forever.

1. Sign in at https://pypi.org/manage/project/monogate-forge/settings/publishing/
2. **Add a new pending publisher** with:
   - Owner: `agent-maestro`
   - Repository name: `forge`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. In GitHub → repo Settings → Environments → **New environment** `pypi`.
   Optional but recommended: tick "Required reviewers" and add yourself,
   so every PyPI publish requires manual approval before the OIDC
   token is minted.
4. Delete the `PYPI_TOKEN` repo secret. The workflow no longer reads it.

## One-time setup — VS Code Marketplace PAT

Marketplace publishing doesn't yet support OIDC for third-party
publishers, so the PAT lives as a single repo secret.

1. Generate a PAT at https://dev.azure.com/<your-org>/_usersSettings/tokens
   - Organization: **All accessible organizations** (REQUIRED)
   - Scopes: **Marketplace → Manage**
   - Expiration: 1 year max — set a calendar reminder
2. Settings → Secrets and variables → Actions → **New repository secret**
   - Name: `VSCE_PAT`
   - Value: the PAT (paste once — Azure shows it once)
3. Rotate annually: regenerate, update the secret, revoke the old PAT.

---

## Cutting a release

### `monogate-forge` (Python wheel)

```bash
# 1. Bump version in pyproject.toml (and CHANGELOG.md)
git commit -am "release: monogate-forge 0.2.0"

# 2. Tag + push
git tag monogate-forge-v0.2.0
git push origin master --tags
```

The workflow will:
- verify the pyproject version matches the tag suffix
- build sdist + wheel
- assert the wheel does NOT contain `industries/` (proprietary IP guard)
- upload via OIDC to PyPI

If you protected the `pypi` environment with required reviewers, the
publish job pauses until you click Approve in the Actions tab.

### `monogate-forge-vscode` (VS Code extension)

```bash
# 1. Bump version in tools/ide/vscode/package.json + CHANGELOG.md
git commit -am "release: vscode 0.10.0"

# 2. Tag + push
git tag vscode-v0.10.0
git push origin master --tags
```

The workflow will:
- verify the package.json version matches the tag suffix
- npm install + tsc compile
- vsce package → `.vsix`
- vsce publish to the marketplace using `VSCE_PAT`
- attach the `.vsix` to a GitHub Release for archival

---

## Coordinated four-package launches

When `monogate-forge` ships a feature that the other three packages
depend on (e.g., the LSP cache + hover work in `c65bab8` that
unlocks vscode 0.10.0's chain-order tooltips), the order is:

1. `monogate-forge-v<x>` — wait until live on PyPI (~30 s)
2. `efrog-v<y>` (in the efrog repo)
3. `forge-mcp-v<z>` (in the mcp-server repo) — depends on `efrog`
4. `vscode-v<w>` — assumes `monogate-forge-v<x>` is live on PyPI

Each step is a tag push from a different repo. There is no
cross-repo orchestration; you just don't push the next tag until the
previous workflow lands green.

## What used to be here

The previous `release.yml` used `secrets.PYPI_TOKEN` and a `v*`
tag pattern. That worked, but:

- the token had to be rotated by hand
- the `v*` pattern would have collided with the new vscode workflow
- a leaked token could publish anything; the OIDC token is scoped
  to `monogate-forge` only and lasts ~10 minutes

After Trusted Publisher is configured per the steps above,
`PYPI_TOKEN` should be deleted from the repo's secrets list.
