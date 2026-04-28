# Go-to-Market

## Positioning

> "One source. Software AND hardware. Provably precise."

Single source compiles to both executable code (C / Rust / WASM)
and synthesizable HDL (Verilog / VHDL / Chisel) with formal
precision bounds. Replaces the MATLAB → C → HDL hand-translation
pipeline that every regulated industry currently maintains.

## Per-vertical entry strategy

| Vertical | Entry product | Beachhead customer profile |
|----------|---------------|----------------------------|
| Aerospace | Autopilot control loop with DO-178C theorem package | Tier-2 supplier doing custom flight control |
| Automotive | Motor FOC + ISO 26262 ASIL evidence | EV startup or motor controller IP licensor |
| Robotics | 6-DOF kinematics library targeting both ROS 2 (CPU) AND Spartan-7 (FPGA) | Industrial robot OEM with a co-pro design |
| Manufacturing | CNC interpolation library | CNC controller OEM |
| Energy | Inverter control law (renewable / EV charging) | Inverter manufacturer |
| Medical | Infusion pump dose calculation with IEC 62304 trace | Medical device startup |
| Defense | INS / Kalman fusion with MIL-STD-882 evidence | Defense contractor R&D group |
| Audio | DX7-class FM synthesis on iCE40 (open FPGA) | Boutique synth maker |
| ML | Activation function library (sigmoid/SiLU/GELU) for FPGA inference | ML accelerator startup |
| Scientific | Hodgkin-Huxley neuron / climate model on FPGA | University research lab |

## Sequencing

1. Phase 4 ships → public launch on monogate.org/forge
2. First-class blog series: one industry vertical per month
3. Conference targets: FPGA conferences first (low cost,
   technical audience), then industry-specific (e.g. Embedded
   World, ICRA, ISSCC) as verticals harden
4. Open-source first; paid tiers come once we have 10+ Pro
   inquiries unsolicited
