# Forge benchmark dashboard

## Overview

- Verticals: **81** functions across **26** modules
- Stdlib:    **58** functions across **5** modules
- Vertical worst-case: chain=4, cycles=76, nodes=54
- Stdlib worst-case:   chain=6, cycles=32

## Verticals

| Module | Function | Chain | Nodes | Cycles | MAC | Trig |
|--------|----------|------:|------:|-------:|----:|-----:|
| `additive_voice` | `envelope` | 1 | 8 | 8 | 4 | 0 |
| `additive_voice` | `partial` | 2 | 9 | 8 | 4 | 1 |
| `additive_voice` | `voice_sample` | 0 | 54 | 8 | 4 | 0 |
| `aes` | `aes_sbox` | 0 | 6 | 4 | 2 | 0 |
| `aes` | `affine_transform` | -1 | 0 | 0 | 0 | 0 |
| `aes` | `gf256_inverse` | 0 | 35 | 16 | 8 | 0 |
| `aes` | `gf256_mul` | -1 | 0 | 0 | 0 | 0 |
| `aes` | `gf256_square` | -1 | 0 | 0 | 0 | 0 |
| `arm_6dof` | `arm_endpoint_x` | 4 | 16 | 12 | 6 | 2 |
| `arm_6dof` | `joint_xy` | 2 | 14 | 16 | 8 | 0 |
| `autopilot` | `autopilot_step` | 0 | 24 | 12 | 6 | 0 |
| `autopilot` | `gravity_compensation` | 2 | 5 | 8 | 4 | 1 |
| `autopilot` | `rate_controller` | 0 | 13 | 4 | 2 | 0 |
| `biquad_lowpass` | `biquad_lowpass_step` | 0 | 20 | 2 | 1 | 0 |
| `chacha20` | `quarter_round` | 0 | 46 | 76 | 38 | 0 |
| `chacha20` | `rotl` | -1 | 0 | 0 | 0 | 0 |
| `chacha20` | `wadd` | -1 | 0 | 0 | 0 | 0 |
| `chacha20` | `wxor` | -1 | 0 | 0 | 0 | 0 |
| `dilithium` | `dilithium_butterfly` | -1 | 0 | 0 | 0 | 0 |
| `dilithium` | `ntt_butterfly` | 0 | 4 | 2 | 1 | 0 |
| `dilithium` | `verify_byte` | 0 | 5 | 2 | 1 | 0 |
| `dilithium` | `verify_dilithium3_byte` | -1 | 0 | 0 | 0 | 0 |
| `ecdsa` | `montgomery_ladder_p256_x` | -1 | 0 | 0 | 0 | 0 |
| `ecdsa` | `scalar_mul_x` | 0 | 4 | 2 | 1 | 0 |
| `ecdsa` | `sign_p256_r` | -1 | 0 | 0 | 0 | 0 |
| `ecdsa` | `sign_r` | 0 | 5 | 2 | 1 | 0 |
| `ed25519` | `edwards_add_complete_y` | -1 | 0 | 0 | 0 | 0 |
| `ed25519` | `edwards_add_y` | 0 | 4 | 2 | 1 | 0 |
| `ed25519` | `sign_ed25519_r` | -1 | 0 | 0 | 0 | 0 |
| `ed25519` | `sign_r` | 0 | 4 | 2 | 1 | 0 |
| `falcon` | `falcon_butterfly` | -1 | 0 | 0 | 0 | 0 |
| `falcon` | `gaussian_sample` | -1 | 0 | 0 | 0 | 0 |
| `falcon` | `ntt_butterfly` | 0 | 4 | 2 | 1 | 0 |
| `groth16` | `miller_loop_bls12_381_x` | -1 | 0 | 0 | 0 | 0 |
| `groth16` | `miller_loop_x` | 0 | 4 | 2 | 1 | 0 |
| `groth16` | `verify_byte` | 0 | 5 | 2 | 1 | 0 |
| `groth16` | `verify_groth16_byte` | -1 | 0 | 0 | 0 | 0 |
| `infusion_pump` | `motor_command` | 0 | 17 | 10 | 5 | 0 |
| `ins` | `attitude_step` | 0 | 22 | 8 | 4 | 0 |
| `kyber` | `cooley_tukey_butterfly` | -1 | 0 | 0 | 0 | 0 |
| `kyber` | `decapsulate_byte` | 0 | 4 | 2 | 1 | 0 |
| `kyber` | `decapsulate_kyber768_byte` | -1 | 0 | 0 | 0 | 0 |
| `kyber` | `ntt_butterfly` | 0 | 4 | 2 | 1 | 0 |
| `ml_binary_classifier` | `binary_cross_entropy` | 2 | 15 | 10 | 5 | 0 |
| `ml_binary_classifier` | `classify` | 0 | 17 | 4 | 2 | 0 |
| `ml_binary_classifier` | `score` | 0 | 10 | 4 | 2 | 0 |
| `ml_binary_classifier` | `sigmoid_tanh_form` | 1 | 9 | 8 | 4 | 0 |
| `motor_foc_automotive` | `foc_d_axis` | 0 | 18 | 8 | 4 | 0 |
| `motor_foc_automotive` | `pi_step` | 0 | 8 | 2 | 1 | 0 |
| `mppt` | `mppt_step` | 1 | 18 | 14 | 7 | 0 |
| `plc_setpoint` | `actuator_command` | 0 | 19 | 10 | 5 | 0 |
| `plonk` | `evaluate_gate` | 0 | 20 | 10 | 5 | 0 |
| `plonk` | `fadd` | -1 | 0 | 0 | 0 | 0 |
| `plonk` | `fmul` | -1 | 0 | 0 | 0 | 0 |
| `plonk` | `kzg_open_at` | 0 | 4 | 2 | 1 | 0 |
| `plonk` | `kzg_open_one` | -1 | 0 | 0 | 0 | 0 |
| `rsa` | `modexp_montgomery` | 0 | 5 | 2 | 1 | 0 |
| `rsa` | `montgomery_ladder` | -1 | 0 | 0 | 0 | 0 |
| `schrodinger_step` | `laplacian` | 0 | 10 | 6 | 3 | 0 |
| `schrodinger_step` | `psi_real_step` | 0 | 16 | 6 | 3 | 0 |
| `sha256` | `big_sigma0` | -1 | 0 | 0 | 0 | 0 |
| `sha256` | `big_sigma1` | -1 | 0 | 0 | 0 | 0 |
| `sha256` | `ch` | -1 | 0 | 0 | 0 | 0 |
| `sha256` | `maj` | -1 | 0 | 0 | 0 | 0 |
| `sha256` | `sha256_round` | 0 | 37 | 12 | 6 | 0 |
| `sha256` | `wadd` | -1 | 0 | 0 | 0 | 0 |
| `sha256` | `wadd5` | -1 | 0 | 0 | 0 | 0 |
| `sha3` | `chi_lane` | -1 | 0 | 0 | 0 | 0 |
| `sha3` | `iota_lane` | -1 | 0 | 0 | 0 | 0 |
| `sha3` | `keccak_round_lane` | 0 | 7 | 8 | 4 | 0 |
| `sha3` | `rho_pi_lane` | -1 | 0 | 0 | 0 | 0 |
| `sha3` | `theta_lane` | -1 | 0 | 0 | 0 | 0 |
| `stark` | `fri_fold` | -1 | 0 | 0 | 0 | 0 |
| `stark` | `fri_fold_step` | 0 | 5 | 2 | 1 | 0 |
| `stark` | `verify_byte` | 0 | 4 | 2 | 1 | 0 |
| `stark` | `verify_stark_byte` | -1 | 0 | 0 | 0 | 0 |
| `three_phase` | `clarke` | 0 | 18 | 8 | 4 | 0 |
| `three_phase` | `park` | 2 | 27 | 20 | 10 | 0 |
| `x25519` | `montgomery_ladder_x25519` | -1 | 0 | 0 | 0 | 0 |
| `x25519` | `scalar_clamp` | -1 | 0 | 0 | 0 | 0 |
| `x25519` | `x25519` | 0 | 5 | 4 | 2 | 0 |

## Stdlib

| Module | Function | Chain | Nodes | Cycles | MAC | Trig |
|--------|----------|------:|------:|-------:|----:|-----:|
| `control` | `complementary` | 0 | 12 | 8 | 4 | 0 |
| `control` | `dead_zone` | 0 | 8 | 10 | 5 | 0 |
| `control` | `hpf1` | 0 | 8 | 6 | 3 | 0 |
| `control` | `kalman1d_predict` | 0 | 6 | 2 | 1 | 0 |
| `control` | `kalman1d_update` | 0 | 24 | 18 | 9 | 0 |
| `control` | `lpf1` | 0 | 10 | 8 | 4 | 0 |
| `control` | `pid` | 0 | 12 | 4 | 2 | 0 |
| `control` | `pid_anti_windup` | 0 | 24 | 14 | 7 | 0 |
| `control` | `pid_integrate` | 0 | 10 | 8 | 4 | 0 |
| `control` | `rate_limit` | 0 | 12 | 10 | 5 | 0 |
| `control` | `saturate` | 0 | 6 | 6 | 3 | 0 |
| `control` | `slew` | 0 | 9 | 4 | 2 | 0 |
| `linalg` | `mat3_det` | 0 | 30 | 8 | 4 | 0 |
| `linalg` | `mat3_trace` | 0 | 6 | 2 | 1 | 0 |
| `linalg` | `mat3_vec3` | 0 | 35 | 12 | 6 | 0 |
| `linalg` | `quat_conj` | 0 | 9 | 6 | 3 | 0 |
| `linalg` | `quat_mul` | 0 | 62 | 16 | 8 | 0 |
| `linalg` | `quat_norm_sq` | 0 | 16 | 4 | 2 | 0 |
| `linalg` | `quat_normalize` | 1 | 35 | 32 | 16 | 0 |
| `linalg` | `vec3_cross` | 0 | 23 | 12 | 6 | 0 |
| `linalg` | `vec3_dot` | 0 | 12 | 4 | 2 | 0 |
| `linalg` | `vec3_norm` | 1 | 13 | 6 | 3 | 0 |
| `linalg` | `vec3_norm_sq` | 0 | 12 | 4 | 2 | 0 |
| `linalg` | `vec3_normalize` | 1 | 28 | 24 | 12 | 0 |
| `linalg` | `vec3_scale` | 0 | 11 | 6 | 3 | 0 |
| `math` | `atan2_pos_x` | 1 | 5 | 6 | 3 | 1 |
| `math` | `cube` | 0 | 6 | 2 | 1 | 0 |
| `math` | `degrees` | 0 | 4 | 2 | 1 | 0 |
| `math` | `exp10` | 1 | 5 | 4 | 2 | 0 |
| `math` | `exp2` | 1 | 5 | 4 | 2 | 0 |
| `math` | `hypot2` | 1 | 9 | 6 | 3 | 0 |
| `math` | `hypot3` | 1 | 13 | 6 | 3 | 0 |
| `math` | `lerp` | 0 | 8 | 8 | 4 | 0 |
| `math` | `log10` | 1 | 5 | 4 | 2 | 0 |
| `math` | `log2` | 1 | 5 | 4 | 2 | 0 |
| `math` | `log_b` | 2 | 6 | 6 | 3 | 0 |
| `math` | `radians` | 0 | 4 | 2 | 1 | 0 |
| `math` | `sign01` | 0 | 5 | 4 | 2 | 0 |
| `math` | `smoothstep` | 0 | 16 | 6 | 3 | 0 |
| `math` | `sq` | 0 | 4 | 2 | 1 | 0 |
| `ml` | `gelu` | 1 | 19 | 12 | 6 | 0 |
| `ml` | `leaky_relu` | 0 | 7 | 6 | 3 | 0 |
| `ml` | `relu` | 0 | 5 | 4 | 2 | 0 |
| `ml` | `sigmoid` | 1 | 8 | 4 | 2 | 0 |
| `ml` | `sigmoid_alt` | 1 | 9 | 8 | 4 | 0 |
| `ml` | `softplus` | 2 | 6 | 2 | 1 | 0 |
| `ml` | `swish` | 1 | 8 | 4 | 2 | 0 |
| `signal` | `biquad_state_update` | 0 | 6 | 0 | 0 | 0 |
| `signal` | `biquad_step` | 0 | 20 | 4 | 2 | 0 |
| `signal` | `box_muller` | 4 | 11 | 10 | 5 | 1 |
| `signal` | `box_muller_pair` | 4 | 20 | 20 | 10 | 0 |
| `signal` | `db_to_linear` | 1 | 7 | 4 | 2 | 0 |
| `signal` | `fir3` | 0 | 12 | 4 | 2 | 0 |
| `signal` | `fir5` | 0 | 20 | 4 | 2 | 0 |
| `signal` | `linear_to_db` | 1 | 7 | 4 | 2 | 0 |
| `signal` | `wave_cosine` | 2 | 11 | 12 | 6 | 1 |
| `signal` | `wave_sine` | 2 | 11 | 12 | 6 | 1 |
| `signal` | `wave_triangle` | 6 | 33 | 14 | 7 | 3 |

## Highest chain order (verticals)

| Function | chain_order |
|----------|------:|
| `arm_6dof::arm_endpoint_x` | 4 |
| `additive_voice::partial` | 2 |
| `arm_6dof::joint_xy` | 2 |
| `autopilot::gravity_compensation` | 2 |
| `ml_binary_classifier::binary_cross_entropy` | 2 |

## Highest FPGA cycles (verticals)

| Function | fpga_cycles |
|----------|------:|
| `chacha20::quarter_round` | 76 |
| `three_phase::park` | 20 |
| `aes::gf256_inverse` | 16 |
| `arm_6dof::joint_xy` | 16 |
| `mppt::mppt_step` | 14 |

## Highest node count (verticals)

| Function | node_count |
|----------|------:|
| `additive_voice::voice_sample` | 54 |
| `chacha20::quarter_round` | 46 |
| `sha256::sha256_round` | 37 |
| `aes::gf256_inverse` | 35 |
| `three_phase::park` | 27 |
