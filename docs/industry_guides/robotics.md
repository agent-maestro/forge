# Robotics — kinematics + control

> Forge Pro vertical. ROS 2 node skeletons for forward and
> inverse kinematics, IK Jacobians, manipulator-torque models,
> mobile-base steering, and the closed-loop control surface
> robotics programs build on.

---

## What robotics needs from a compiler

A robot's joint controller has to run at kilohertz with a hard
real-time budget. The forward/inverse kinematics has to round
to the same answer in your simulator and on hardware. Sensor
fusion has to be provably stable through the moving-frame trig.
Forge delivers:

- **Bounded joint commands** — `requires` / `ensures` clauses
  prove every joint stays inside its mechanical limit.
- **Stability under chain-2 trig** — the chain-order checker
  catches accidental nesting that would explode fp16 jacobians.
- **ROS 2 node skeletons** — emit the publisher / subscriber /
  parameter-server scaffolding alongside the math, all from one
  source.

---

## What ships in the Pro tier

The robotics pack covers the math that runs inside every modern
robot. Typical chain orders run 0–2 (controllers are chain 0;
trig-laden kinematics lift to chain 2). Every kernel ships with:

- A `@verify(lean)` contract on joint-limit bounds, energy
  conservation, or PID actuator clamping.
- An `@target(fpga, ...)` profile for hardware-accelerated
  inner loops (joint controllers, IMU complementary filters).
- The full backend matrix (C, Rust, Python, ROS 2, Lean) plus
  a per-cell ROS 2 node skeleton.

Coverage areas include:

- Forward + inverse kinematics for serial 6-DOF arms
- IK Jacobians + damped-least-squares solver
- Manipulator-torque models (gravity comp, dynamics)
- Mobile-base steering (Ackermann, mecanum, differential drive)
- Sensor fusion (IMU complementary filter, particle filter step,
  ICP iteration)

---

## Working with the kernels

Open a kernel and the LSP surfaces:

- Chain order + cost class on every fn header
- FPGA estimate for inner-loop kernels
- Lean joint-limit theorem next to `@verify` blocks
- ROS 2 message types in the right pane (Pro feature)

Compile to every backend in one command:

```
eml-compile <kernel>.eml --target all -o build/
```

The Python lands ready for SimPy / Drake; the ROS 2 node
skeleton drops into a colcon workspace; the C variant goes onto
the joint controller MCU.

---

## Get access

The robotics kernel pack ships with **Forge Pro**. Visit
<https://monogateforge.com/get-started> for the full library.

Free tier covers the compiler and 12 software backends — write
your own robotics `.eml` and compile to Python / C / Lean today.
