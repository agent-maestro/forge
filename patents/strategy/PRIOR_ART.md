# Prior Art Notes

> Internal. Known prior art for each Forge-relevant patent claim.
> Maintained so the patent-strengthening review can see at a glance
> what's already been disclosed and what differentiates our claims.

## Patent #14 (FPGA resource allocator)

- **HDL Coder (MathWorks)** — generates HDL from Simulink/MATLAB
  but uses uniform precision; doesn't do per-unit precision +
  sharing decisions driven by Pfaffian profile.
- **Vivado HLS / Vitis HLS (Xilinx)** — schedules pragma-driven
  resource sharing but doesn't reason about chain-order
  complexity for transcendentals.
- **Spinal HDL / Chisel** — parametric HDL generation but no
  cost-class-driven allocator above it.

Differentiator: allocation decisions driven by the SuperBEST cost
class + Pfaffian chain order, with per-unit precision selection
that respects declared output tolerance.

## Patent #21 (chain-order types)

- **Refinement types (Liquid Haskell, F*, Dafny)** — type-level
  predicates over arithmetic; no Pfaffian chain semantics.
- **Stainless / Scala types** — closest in spirit but again no
  chain-order primitive.

Differentiator: chain order is a FIRST-CLASS type bound, inferred
mechanically from the operator dictionary, that ties directly
into Pfaffian zero-count theorems and FPGA allocation cost.

## Patent #22 (dual-target compilation)

- **HDL Coder, Vivado HLS, MyHDL** — single-target HDL generation
  from Python/MATLAB.
- **TensorFlow XLA / TVM** — multi-target ML compilation, but no
  hardware (HDL) target.

Differentiator: same source produces both an executable C/Rust
binary AND a synthesizable HDL file with PROVABLE precision
equivalence between them.

## Update protocol

Add to this file when:
1. A reviewer (attorney or patent-strengthening agent) flags new
   prior art.
2. A competitor releases something close.
3. A claim survives a search and the prior art mapping needs
   refinement.
