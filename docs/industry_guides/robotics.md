# Robotics — kinematics + control

> Forward + inverse kinematics for serial chains, IK Jacobians,
> and quaternion-based attitude control — same source compiles
> to ROS-style C++, embedded C, and FPGA-accelerated math
> coprocessors.

---

## Why robotics lives in EML-lang

The numerical floor for robotics is set by the kinematics
loop: a 1-degree drift in a 6-DOF arm's end-effector after a
few seconds of motion is the difference between a working
pick-and-place and a destroyed payload. The drift comes from
the same place every time — accumulated rounding in the
forward-kinematics chain or the IK iteration.

Forge's chain-order tag and the SuperBEST routing keep these
loops inside the fp32 safe band by construction. The
quaternion utilities in `stdlib::linalg` are SuperBEST-
canonical, so renormalization happens automatically and the
runtime never sees a quaternion that drifted off the unit
sphere.

---

## Shipping vertical

`industries/robotics/kinematics/arm_6dof.eml` is the canonical
demo. Imports `stdlib::linalg` (mat3, quat, vec3) and the
trig helpers from `stdlib::math`.

```bash
eml-compile industries/robotics/kinematics/arm_6dof.eml \
    --target all -o build/robotics/
```

---

## Recommended `where` clauses

Forward kinematics on a 6-DOF arm typically returns a
homogeneous transform — represented as a quaternion + vec3
pair. The end-effector pose stays on the unit sphere by
construction:

```eml
fn fk_6dof(q: (Real, Real, Real, Real, Real, Real))
    -> (Real, Real, Real, Real, Real, Real, Real)
  where chain_order <= 2,
        domain: q.0 > -3.1416 && q.0 < 3.1416,
        domain: q.1 > -3.1416 && q.1 < 3.1416,
        domain: q.2 > -3.1416 && q.2 < 3.1416,
        domain: q.3 > -3.1416 && q.3 < 3.1416,
        domain: q.4 > -3.1416 && q.4 < 3.1416,
        domain: q.5 > -3.1416 && q.5 < 3.1416
{
    // body
}
```

`chain_order <= 2` reflects the cos/sin nesting depth of a
classic Denavit-Hartenberg chain.

---

## FPGA target choice

For a Cartesian / SCARA loop, `lattice.ecp5` fits the whole
forward-kinematics + Jacobian loop and leaves room for a
trajectory generator. For a 6-DOF arm `xilinx.artix7` is the
safer default — the Jacobian alone wants ~30 MACs and 6 sin/cos
units.

```bash
eml-compile arm_6dof.eml --allocate --fpga-target lattice.ecp5
```

prints the LUT/DSP/BRAM budget; the allocator will fail
fast with `CompileError` if the design exceeds the device's
budget rather than silently producing unsynthesizable HDL.

---

## Common gotchas

- **Euler vs quaternion** — Euler angles are easier to read
  but trigger gimbal-lock branches that confuse the chain-
  order tag. Quaternions stay at chain_order ≤ 2 and have a
  SuperBEST canonical form for renormalization.
- **Singularity detection** — use the `condition_number`
  helper from `stdlib::linalg` instead of computing the
  determinant + eigenvalues by hand. The canonical form
  survives SuperBEST and gets a known cost class.
- **Trajectory blending** — `stdlib::math::smoothstep` is the
  recommended blend; the polynomial form keeps the chain
  order at 0 and the runtime is exactly four MACs.
