"""Cross-target equivalence proven on production-shape industry
vertical designs.

These are NOT toy stdlib functions -- each is a real control
function that ships in the corresponding industry vertical:

  aerospace      gravity_compensation  pitch-attitude autopilot piece
  automotive     pi_step               FOC d-axis PI controller
  energy         mppt_step             solar P&O MPPT
  medical        motor_command         infusion-pump rate motor
  defense        attitude_step         INS attitude integration
  robotics       arm_endpoint_x        6-DOF arm forward kinematics

We pick one representative function per vertical, run it through
`cross_target_check`, and assert agreement with the SymPy
reference within ULP tolerance. Cargo-required: tests skip the
Rust comparison when cargo isn't on PATH.

Why this matters: stdlib functions are tiny by design. The dual-
target patent claim covers production-shape designs. This file
is the operational evidence for that claim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.equivalence import cross_target_check
from tools.equivalence.rust_runner import cargo_available


REPO_ROOT = Path(__file__).resolve().parents[2]
INDUSTRY = REPO_ROOT / "industries"


# Each entry: (file, fn_name, vectors, tolerance)
# Inputs are picked to stay inside each function's domain.

VERTICAL_CASES: list[tuple[str, str, list[tuple[float, ...]], float]] = [
    # Aerospace -- gravity_compensation(pitch_measured)
    (
        "aerospace/flight_control/autopilot.eml",
        "gravity_compensation",
        [(0.0,), (0.1,), (-0.2,), (0.5,)],
        1e-12,
    ),
    # Automotive -- pi_step(error, integral, Kp, Ki)
    (
        "automotive/powertrain/motor_foc.eml",
        "pi_step",
        [
            (0.0, 0.0, 1.0, 0.1),
            (0.5, 1.0, 2.0, 0.5),
            (-0.3, -0.2, 1.5, 0.2),
        ],
        1e-12,
    ),
    # Energy -- mppt_step(power_now, power_prev, voltage_now)
    (
        "energy/renewable/mppt.eml",
        "mppt_step",
        [
            (100.0, 95.0, 24.0),
            (50.0, 60.0, 22.0),
            (10.0, 10.0, 20.0),
        ],
        1e-9,    # tanh involved -> looser tolerance
    ),
    # Medical -- motor_command(prescribed_rate, measured_rate, rate_integral)
    (
        "medical/devices/infusion_pump.eml",
        "motor_command",
        [
            (5.0, 5.0, 0.0),
            (10.0, 8.0, 1.5),
            (0.0, 0.5, -0.5),
        ],
        1e-12,
    ),
    # Defense -- attitude_step(attitude, rate_gyro)
    (
        "defense/navigation/ins.eml",
        "attitude_step",
        [
            (0.0, 0.0),
            (0.1, 0.05),
            (-0.2, 0.1),
        ],
        1e-12,
    ),
    # Robotics -- arm_endpoint_x(theta_1, theta_2)
    (
        "robotics/kinematics/arm_6dof.eml",
        "arm_endpoint_x",
        [
            (0.0, 0.0),
            (0.5, -0.5),
            (1.0, 0.7),
        ],
        1e-12,
    ),
    # ML -- classify(x1, x2). Inside the body sigmoid_tanh_form
    # gets SuperBEST-rewritten to the canonical sigmoid; the
    # rewrite is inside the optimizer's tolerance budget so output
    # agreement to ~1e-9 is the realistic bar (the rewrite saves
    # ~1.08 digits of precision, but introduces a different
    # rounding signature).
    (
        "ml/inference/binary_classifier.eml",
        "classify",
        [
            (0.0, 0.0),     # bias-only input
            (1.0, 1.0),
            (2.0, -1.0),
            (-3.0, 4.0),
        ],
        1e-9,
    ),
    # Audio -- biquad_lowpass_step(x, x1, x2, y1, y2,
    #                              b0, b1, b2, a1, a2)
    # 10 args; chain order 0 (pure linear combination via the
    # inlined stdlib::signal::biquad_step body).
    (
        "audio/dsp/biquad_lowpass.eml",
        "biquad_lowpass_step",
        [
            (0.5, 0.0, 0.0, 0.0, 0.0,
             0.25, 0.5, 0.25, -0.5, 0.25),
            (0.0, 0.5, 0.0, 0.0, 0.0,
             0.25, 0.5, 0.25, -0.5, 0.25),
            (1.0, 1.0, 1.0, 1.0, 1.0,
             0.0, 1.0, 0.0, 0.0, 0.0),
        ],
        1e-12,
    ),
    # Scientific -- psi_real_step (one explicit-Euler step of the
    # 1-D Schrödinger equation; pure linear combo).
    (
        "scientific/physics/schrodinger_step.eml",
        "psi_real_step",
        [
            (0.0, 0.0, 0.0, 0.0),
            (1.0, 0.0, 0.5, 0.0),
            (0.5, 0.1, 0.2, 0.3),
            (-0.5, -0.1, 0.0, 0.1),
        ],
        1e-12,
    ),
    # Manufacturing -- actuator_command (PI loop with
    # anti-windup + actuator clamp).
    (
        "manufacturing/process_control/plc_setpoint.eml",
        "actuator_command",
        [
            (50.0, 50.0, 0.0),    # at setpoint, zero integral
            (75.0, 50.0, 5.0),    # below setpoint, modest integral
            (25.0, 50.0, -2.0),   # above setpoint, slight wind-down
        ],
        1e-12,
    ),
]


@pytest.mark.parametrize(
    "filename,fn_name,vectors,tolerance",
    VERTICAL_CASES,
    ids=[f"{c[0]}::{c[1]}" for c in VERTICAL_CASES],
)
def test_vertical_python_reference_runs(
    filename: str,
    fn_name: str,
    vectors: list[tuple[float, ...]],
    tolerance: float,
) -> None:
    """The Python reference must produce a finite output for every
    vector, with module-level constants substituted from the source
    (not left as free symbols)."""
    path = INDUSTRY / filename
    r = cross_target_check(
        path, fn_name, vectors,
        tolerance=tolerance,
        targets=("python",),
    )
    py = r.targets["python"]
    assert py.available, (
        f"python reference unavailable on {fn_name}: {py.error}"
    )
    for out in py.outputs:
        # Numeric -- no leftover SymPy symbols.
        assert isinstance(out, (int, float)), (
            f"{fn_name}: non-numeric python output {out!r} -- "
            "module-level constants probably aren't substituting"
        )
        assert out == out  # not NaN


@pytest.mark.skipif(
    not cargo_available(),
    reason="cargo / rustc not on PATH",
)
@pytest.mark.parametrize(
    "filename,fn_name,vectors,tolerance",
    VERTICAL_CASES,
    ids=[f"{c[0]}::{c[1]}" for c in VERTICAL_CASES],
)
def test_vertical_rust_matches_python(
    filename: str,
    fn_name: str,
    vectors: list[tuple[float, ...]],
    tolerance: float,
) -> None:
    """Rust target must match the Python reference within tolerance
    -- the production-shape evidence for Patent #22."""
    path = INDUSTRY / filename
    r = cross_target_check(
        path, fn_name, vectors,
        tolerance=tolerance,
        targets=("python", "rust"),
    )
    rust = r.targets["rust"]
    assert rust.available, f"rust unavailable: {rust.error}"
    assert rust.error == "", (
        f"{filename}::{fn_name} rust runner error:\n{rust.error[:600]}"
    )
    assert rust.max_abs_err <= tolerance, (
        f"{filename}::{fn_name} diverged "
        f"(max_abs={rust.max_abs_err:.3g}, tol={tolerance:.3g})\n"
        + r.render()
    )
