# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| Latest minor on PyPI (`pip install monogate-forge`) | ✅ |
| One minor back | ✅ (security fixes only) |
| Older | ❌ — please upgrade |

## Reporting a vulnerability

**Please do NOT open a public GitHub issue for security
vulnerabilities.** We use email + GitHub Security Advisories for
coordinated disclosure.

Email: **contact@monogate.dev** with the subject `[forge security]`.
PGP key fingerprint forthcoming; reach out via the listed email
first and we'll coordinate from there.

In your report, please include:

1. The version of `monogate-forge` you tested against (`eml-compile --version`).
2. A minimal reproducer (`.eml` file + `eml-compile` invocation),
   or a description of the misuse / abuse path.
3. The impact you've observed (incorrect codegen, license-token
   bypass, parser DoS, file-read outside the workspace, etc.).
4. Whether you'd like credit in the eventual advisory + a name to
   credit by.

We aim to acknowledge new reports within **72 hours** and ship a
fix within **30 days** for high-severity issues, **90 days** for
medium / low. We will keep you informed of progress and credit
your work in the [advisory](https://github.com/agent-maestro/forge/security/advisories)
on resolution unless you ask otherwise.

## Scope

In scope:

- Bugs in the `eml-compile` codegen that produce incorrect output
  (the published Lean / @verify contract holds in EML but is
  violated by a backend's lowering).
- License-token verification bypass in `tools/license/` that
  unlocks Pro-tier backends without a valid Ed25519-signed token.
- Parser / loader code paths that allow path traversal outside
  the workspace, arbitrary file write, or arbitrary code
  execution from a malicious `.eml` source.
- Cryptographic regressions in the license-token verification
  flow (downgrade attacks, signature-malleability, etc.).
- Supply-chain attacks against the published wheel (typosquats,
  dependency confusion).

Out of scope:

- Generated-output runtime safety after Forge has emitted it
  (e.g. an unsafe Rust pattern that the user wrote into their EML
  source). The contract is "Forge faithfully lowers EML to the
  target language"; what the target language does at runtime is
  the user's responsibility.
- Lean obligations marked `@sorry` in upstream MachLib — these
  are documented gaps tracked in MachLib's own roadmap and are
  not security issues against Forge.

## Coordinated-disclosure window

We follow a **90-day** coordinated-disclosure window from receipt
of the report. If the issue is being actively exploited in the
wild, we may shorten that window and ship an advisory immediately.
If we need longer (e.g. complex multi-backend codegen fix), we'll
discuss the extension with the reporter ahead of the deadline.

## Hall of fame

Reporters credited with confirmed vulnerabilities will be listed
here once we have any to acknowledge. Welcome.
