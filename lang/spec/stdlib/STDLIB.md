# EML-lang Standard Library

The stdlib is a set of `.eml` modules that ship with Forge. Every
backend can compile them. They serve double duty as canonical
implementations and as documentation for what's idiomatic.

| Module | Lines | Chain order range | Notes |
|--------|------:|-------------------|-------|
| `math` | TODO | 0-3 | Core: exp, ln, sqrt, pow, abs, trig, hyp, log_b |
| `control` | TODO | 0-2 | PID, state-space, observer (Kalman, Luenberger) |
| `signal` | TODO | 2-3 | FFT, biquad, FIR, IIR, convolution |
| `linalg` | TODO | 0-1 | matmul, transpose, inv, eigvals (small fixed sizes) |
| `constants` | 1 line each | 0 | Physical constants (c, h, k, pi, e, etc.) |

## Stability guarantee

Stdlib modules are NOT under the same "no breaking changes" rule
as the language spec. Functions can be deprecated, signatures
can evolve. But:

- Every change to a stdlib function MUST update the matching test
- Every backend MUST agree on every stdlib function's output
  (verified by `tests/integration/`)
- Stability bumps trigger a CHANGELOG entry

See each `.eml` file in this directory for its current contents.
