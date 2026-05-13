# Forge examples

Small, public `.eml` files that demonstrate language features
without revealing proprietary kernel content. Ship with the
PyPI wheel; reference these from the README, docs, and live
demo gallery.

## Quick tour

| File | Chain order | Teaches |
|---|---:|---|
| `hello.eml` | 0 | Module declaration, function, literal return |
| `lerp.eml` | 0 | Polynomial body, multiple inputs |
| `quadratic.eml` | 0 | `a*x^2 + b*x + c` — the canonical chain-0 polynomial |
| `pid_controller.eml` | 0 | `requires` / `ensures` clamp contract |
| `clamp_bounded.eml` | 0 | `clamp` builtin + `@verify` postcondition |
| `verified_add.eml` | 0 | The smallest `@verify` shape (two `requires`, one `ensures`) |
| `smoothstep.eml` | 0 | Polynomial smoothing curve with `@verify` |
| `exponential_decay.eml` | 1 | `exp(-k*t)` — the chain-1 archetype |
| `sine_oscillator.eml` | 1 | `sin(omega*t)` with amplitude `@verify` |
| `gaussian.eml` | 1 | `exp(-(x-mu)^2/...)` — the bell curve |
| `sigmoid.eml` | 2 | `1 / (1 + exp(-x))` — the chain-2 ML activation |
| `damped_wave.eml` | 2 | `exp(-zeta*t) * sin(omega*t)` — the chain-2 archetype |

## Running

Every file compiles to every backend in your tier:

```bash
# Free tier — 12 backends
eml-compile examples/hello.eml --target python
eml-compile examples/pid_controller.eml --target rust
eml-compile examples/sigmoid.eml --target lean

# Compile all Free targets at once
eml-compile examples/damped_wave.eml --target all
```

## What's not here

The full kernel library — aerospace flight control, automotive
powertrain, medical infusion, robotics, crypto, gaming, and a
dozen more domains — is the proprietary product. It ships with
Forge Pro plans at <https://monogateforge.com/get-started>.

The compiler is open. The kernels are the product. Anyone can
write their own `.eml`, profile it with `eml-cost`, and compile
to any of the 36 targets. The pre-verified domain library is
what's gated.
