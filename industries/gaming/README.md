# gaming

> Industry vertical scaffold. SCAFFOLD -- per-application `.eml`
> files arrive as the vertical comes online.

**Certification target:** none (real-time interactive software;
soft real-time only)
**Typical chain orders:** 0-4 (most kernels are chain 0 polynomial
or chain 1 pow/exp; the analytical spring solution reaches chain 4
because of nested sqrt-under-cos)

## Subdirectories

| dir          | what                                           |
|--------------|------------------------------------------------|
| `physics/`   | rigid-body integrators, gravity, springs       |
| `rendering/` | BRDFs, Fresnel terms, tone mapping, fog        |
| `animation/` | tweening curves, camera shake, breathing       |
| `procedural/`| noise, fBm, Voronoi distance fields            |
| `audio/`     | game-engine reverb / Doppler / cutoff filters  |

## Sibling verticals

This vertical deliberately overlaps with `audio/` and `graphics/`.
The gaming kernels are tuned for soft real-time targets (clock_mhz
typically 500+, precision float32, drift_risk LOW because outputs
are immediately consumed by display/audio rather than logged or
chained). Where the math is identical to the canonical kernel in
the sibling vertical (e.g. biquad lowpass, Schlick Fresnel), the
gaming version is a thin alias documenting the game-specific
caller convention.

## Adding an application

1. Pick the right subdirectory
2. Write a `<name>.eml` with chain-order + domain + precision
   declarations
3. Compile-check with
   `python tools/cli/main.py industries/gaming/<sub>/<name>.eml --fmt --check`
4. If certification-relevant, add a matching theorem (gaming
   kernels typically aren't, but the analytical spring solution
   does carry a `damped_oscillator_amplitude_bound` proof)
