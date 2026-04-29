# ROS 2 Integration Guide

> Robotics doesn't have a single regulatory cert standard the way
> aerospace (DO-178C) and automotive (ISO 26262) do — most
> industrial robots ship under ISO 9001 quality-management with
> ISO 10218 (industrial robot safety) overlays. ISO 13482 covers
> personal-care robots (collaborative arms, exoskeletons).
>
> This guide covers how forge-compiled control laws drop into a
> ROS 2 node — the de-facto integration target for modern
> robotics codebases.

---

## The integration shape

```
.eml source ──┬──→ forge --target c -o joint_controller.c
              │
              └──→ forge --target lean -o joint_controller.lean

C source compiles into a ROS 2 node:

  rclcpp::Node ─→ subscribe `/joint_command` (sensor_msgs::JointState)
              ─→ each tick: call joint_controller(theta, ...)
                            ↑ generated from the .eml
              ─→ publish `/joint_torque` (sensor_msgs::JointState)
```

The Lean theorem stays in `monogate-lean/` for separate
verification — its presence (and the `lake build` PASS) is
your evidence file for the safety case.

## Minimal ROS 2 wrapper

```cpp
// joint_controller_node.cpp
#include "joint_controller.h"     // ← forge's --target c output
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/joint_state.hpp"

class JointControllerNode : public rclcpp::Node {
public:
  JointControllerNode() : Node("joint_controller") {
    sub_ = create_subscription<sensor_msgs::msg::JointState>(
      "/joint_command", 10,
      [this](sensor_msgs::msg::JointState::SharedPtr msg) {
        // Call the forge-generated function. forge guarantees the
        // result respects the @ensures clause (arm reach < 1 m).
        const double torque = arm_endpoint_x(
          msg->position[0], msg->position[1]);
        publish_torque(torque);
      });
    pub_ = create_publisher<sensor_msgs::msg::JointState>(
      "/joint_torque", 10);
  }
  // ... rest of the node
};
```

## Per-application chain-order budget

| Application | Chain order budget | Notes |
|-------------|-------------------|-------|
| Velocity loops | `<= 1` | Tight stability requirement; pure exp/PI is enough |
| Position loops | `<= 2` | sin/cos for orientation transforms |
| Trajectory planning | `<= 3` | atan2 for orientation interpolation |
| Inverse kinematics (numerical) | `<= 6` | Newton iteration; chain order grows per step |
| Task-space control | `<= 4` | Quaternion math |
| Vision-based control | `<= 4` | Camera projection involves transcendentals |

If your motion-control loop sits at the high end (chain ≥ 4),
fp16 will drift unacceptably (per E-193); deploy at f32 minimum.
The forge profiler's `fp16_drift_risk = HIGH` warning catches
this at compile time.

## What forge does NOT (yet) do for robotics

- ROS 2 message-type code generation (you write the `.cpp`
  wrapper by hand).
- URDF integration (joint limits live in URDF, not in `.eml`).
- Real-time scheduling (the forge produces deterministic code;
  the RT scheduler is your problem — `chrt`, `cyclictest`, etc.).

## Testing pattern

```bash
$ # Build the forge output for a single joint
$ eml-compile industries/robotics/kinematics/arm_6dof.eml --target c \
    -o arm_6dof.c
$ gcc arm_6dof.c -lm -shared -fPIC -o libarm_6dof.so

$ # Run the ROS 2 node integration test
$ colcon build --packages-select joint_controller
$ ros2 launch joint_controller controller.launch.py
```
