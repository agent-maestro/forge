//! Plonky2 wiring — turns a `CircuitDescription` into a real
//! zero-knowledge proof over the Goldilocks field.
//!
//! ## Encoding contract
//!
//! Every wire carries a value of the form `real_value * 2^scale_bits`
//! where `scale_bits` starts at [`FIXED_POINT_BITS`] for INPUT and
//! CONST gates and grows by `a.scale_bits + b.scale_bits` after each
//! MUL. ADD/SUB rescale the lower-scale operand up to match. NEG
//! preserves scale.
//!
//! The OUTPUT gate publishes the final wire as a public input; its
//! `scale_bits` is recorded in [`Plonky2Proof::output_scale_bits`] so
//! the verifier (and the Python decoder) knows how to interpret it.
//!
//! Goldilocks is `2^64 - 2^32 + 1` (~64 bit), so a wire's
//! `scale_bits` must stay below [`MAX_OUTPUT_SCALE_BITS`] (= 56). A
//! deeper MUL chain is rejected with a structured error so the Python
//! bridge can fall back to the transparent stub.
//!
//! ## What's actually proved
//!
//! Plonky2 proves the *integer* arithmetic identity over Goldilocks.
//! Because the scale propagates honestly, a verifier who decodes
//! the public-input field elements back through `field_to_float`
//! recovers exactly the same fixed-point answer the prover claims.
//! Re-execution outside the proof is unnecessary — the field-side
//! identity *is* the proof.

use crate::circuit::CircuitDescription;
use anyhow::{anyhow, bail, Context, Result};
use plonky2::field::goldilocks_field::GoldilocksField;
use plonky2::field::types::{Field, PrimeField64};
use plonky2::iop::target::Target;
use plonky2::iop::witness::{PartialWitness, WitnessWrite};
use plonky2::plonk::circuit_builder::CircuitBuilder;
use plonky2::plonk::circuit_data::{CircuitConfig, CircuitData};
use plonky2::plonk::config::PoseidonGoldilocksConfig;
use plonky2::plonk::proof::ProofWithPublicInputs;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Bits of fractional precision used when encoding f64 inputs and
/// constants into the Goldilocks field. Capabilities advertise this
/// so the Python bridge can reject inputs that would round to zero.
pub const FIXED_POINT_BITS: u32 = 16;

/// Hard upper bound on a wire's accumulated scale. Goldilocks is
/// 64-bit; we keep 8 bits of headroom for sign and rounding so the
/// encoded value can't wrap modulo p.
const MAX_OUTPUT_SCALE_BITS: u32 = 56;

const GOLDILOCKS_P: u64 = 0xFFFF_FFFF_0000_0001;

const D: usize = 2;
type C = PoseidonGoldilocksConfig;
type F = GoldilocksField;

// ── Public artefact shape ─────────────────────────────────────────

/// Wire-protocol JSON written by `prove`, read by `verify`. Keeps
/// enough metadata that any third party with the matching circuit
/// JSON + fingerprint can run the verifier without prior state.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Plonky2Proof {
    pub spec: String,
    pub backend: String,
    pub circuit_hash: String,
    pub fingerprint_module_hash: String,
    pub function_name: String,
    /// Inputs in the clear (scaffolding — Phase 1 isn't yet input-hiding).
    pub public_inputs: BTreeMap<String, f64>,
    /// Decoded floating-point output (claim).
    pub output: f64,
    /// Bit count for the implicit `2^k` divisor used to decode the
    /// raw public-input field element back to a float.
    pub output_scale_bits: u32,
    pub fixed_point_bits: u32,
    pub n_gates: usize,
    pub chain_order: u32,
    /// `ProofWithPublicInputs::to_bytes()` hex-encoded.
    pub proof_bytes_hex: String,
}

#[derive(Debug)]
pub struct VerifyOutcome {
    pub is_valid: bool,
    pub reason: String,
}

// ── prove / verify entry points ───────────────────────────────────

pub fn prove(
    desc: &CircuitDescription,
    inputs: &serde_json::Map<String, serde_json::Value>,
    fingerprint: &str,
) -> Result<Plonky2Proof> {
    if !desc.is_arithmetic_only() {
        bail!(
            "Plonky2 backend supports arithmetic-only circuits in Phase 1; \
             function `{}` uses gates outside CONST/INPUT/ADD/SUB/MUL/NEG/OUTPUT \
             — route via the transparent fallback for transcendentals",
            desc.function_name
        );
    }

    let built = build_circuit(desc)?;

    let mut pw = PartialWitness::<F>::new();
    for (name, target) in desc.params.iter().zip(built.input_targets.iter()) {
        let v = inputs
            .get(name)
            .ok_or_else(|| anyhow!("missing input `{name}`"))?;
        let f = v
            .as_f64()
            .or_else(|| v.as_i64().map(|i| i as f64))
            .ok_or_else(|| anyhow!("input `{name}` is not numeric: {v:?}"))?;
        let fe = float_to_field(f, FIXED_POINT_BITS)?;
        pw.set_target(*target, fe)
            .map_err(|e| anyhow!("witness assignment failed for `{name}`: {e}"))?;
    }

    let proof = built
        .data
        .prove(pw)
        .map_err(|e| anyhow!("plonky2 prove failed: {e}"))?;

    let n_inputs = built.input_targets.len();
    let output_field = proof
        .public_inputs
        .get(n_inputs)
        .copied()
        .ok_or_else(|| anyhow!("proof has no output public input"))?;
    let output_float = field_to_float(output_field, built.output_scale_bits);

    let proof_bytes = proof.to_bytes();

    let mut public_inputs_map = BTreeMap::<String, f64>::new();
    for name in &desc.params {
        let f = inputs
            .get(name)
            .and_then(|v| v.as_f64().or_else(|| v.as_i64().map(|i| i as f64)))
            .ok_or_else(|| anyhow!("input `{name}` missing during proof packaging"))?;
        public_inputs_map.insert(name.clone(), f);
    }

    Ok(Plonky2Proof {
        spec: "monogate-zkproof/v1".into(),
        backend: "plonky2".into(),
        circuit_hash: canonical_circuit_hash(desc)?,
        fingerprint_module_hash: fingerprint.into(),
        function_name: desc.function_name.clone(),
        public_inputs: public_inputs_map,
        output: output_float,
        output_scale_bits: built.output_scale_bits,
        fixed_point_bits: FIXED_POINT_BITS,
        n_gates: desc.gates.len(),
        chain_order: desc.chain_order,
        proof_bytes_hex: hex::encode(proof_bytes),
    })
}

pub fn verify(
    desc: &CircuitDescription,
    proof: &Plonky2Proof,
    fingerprint: &str,
) -> Result<VerifyOutcome> {
    if proof.fingerprint_module_hash != fingerprint {
        return Ok(VerifyOutcome {
            is_valid: false,
            reason: format!(
                "fingerprint hash mismatch — proof was produced from a different module \
                 (proof carries `{}`, verifier expected `{}`)",
                proof.fingerprint_module_hash, fingerprint
            ),
        });
    }

    let expected_chash = canonical_circuit_hash(desc)?;
    if proof.circuit_hash != expected_chash {
        return Ok(VerifyOutcome {
            is_valid: false,
            reason: format!(
                "circuit hash mismatch — proof carries `{}`, verifier expected `{}`",
                proof.circuit_hash, expected_chash
            ),
        });
    }

    let built = build_circuit(desc)?;

    let proof_bytes =
        hex::decode(&proof.proof_bytes_hex).context("decoding proof_bytes_hex")?;
    let parsed: ProofWithPublicInputs<F, C, D> =
        ProofWithPublicInputs::from_bytes(proof_bytes, &built.data.common)
            .map_err(|e| anyhow!("plonky2 proof deserialisation failed: {e}"))?;

    // The proof's public inputs are in registration order:
    //   [INPUT(p0), INPUT(p1), ..., OUTPUT].
    // Re-encode the prover's claimed inputs and output and check
    // they are exactly what the proof committed to.
    let n_inputs = built.input_targets.len();
    if parsed.public_inputs.len() != n_inputs + 1 {
        return Ok(VerifyOutcome {
            is_valid: false,
            reason: format!(
                "public-input arity mismatch — proof has {} public inputs, \
                 circuit declares {} parameters + 1 output",
                parsed.public_inputs.len(),
                n_inputs
            ),
        });
    }

    for (i, name) in desc.params.iter().enumerate() {
        let claimed = proof.public_inputs.get(name).copied().ok_or_else(|| {
            anyhow!("proof missing claimed input `{name}` for cross-check")
        })?;
        let claimed_field = float_to_field(claimed, FIXED_POINT_BITS)?;
        if parsed.public_inputs[i] != claimed_field {
            return Ok(VerifyOutcome {
                is_valid: false,
                reason: format!(
                    "public input `{name}` in proof body ({claimed}) does not \
                     match the field element committed inside the proof"
                ),
            });
        }
    }

    // The verifier derives output_scale_bits from the circuit itself
    // (deterministic from the gate structure), so the value the
    // prover put in the JSON is informational only — the actual
    // decoding uses what we just computed.
    let scale_bits = built.output_scale_bits;
    let claimed_output_field = float_to_field(proof.output, scale_bits)?;
    if parsed.public_inputs[n_inputs] != claimed_output_field {
        // Honour float rounding — the field value is the source of
        // truth; report mismatch only when the decoded floats also
        // diverge meaningfully.
        let actual = field_to_float(parsed.public_inputs[n_inputs], scale_bits);
        if (actual - proof.output).abs() > 1e-6 * actual.abs().max(1.0) {
            return Ok(VerifyOutcome {
                is_valid: false,
                reason: format!(
                    "claimed output {} does not match committed output {} \
                     (decoded with scale 2^{})",
                    proof.output, actual, scale_bits
                ),
            });
        }
    }

    match built.data.verify(parsed) {
        Ok(()) => Ok(VerifyOutcome {
            is_valid: true,
            reason: "ok".into(),
        }),
        Err(e) => Ok(VerifyOutcome {
            is_valid: false,
            reason: format!("plonky2 verifier rejected the proof: {e}"),
        }),
    }
}

// ── Circuit construction ──────────────────────────────────────────

struct BuiltCircuit {
    data: CircuitData<F, C, D>,
    input_targets: Vec<Target>,
    output_scale_bits: u32,
}

#[derive(Clone, Copy)]
struct Wire {
    target: Target,
    scale_bits: u32,
}

fn build_circuit(desc: &CircuitDescription) -> Result<BuiltCircuit> {
    let config = CircuitConfig::standard_recursion_config();
    let mut builder = CircuitBuilder::<F, D>::new(config);

    let mut wires: Vec<Wire> = Vec::with_capacity(desc.gates.len());
    let mut input_targets: Vec<Target> = Vec::new();
    let mut output_scale: Option<u32> = None;

    for (gate_idx, g) in desc.gates.iter().enumerate() {
        let wire = match g.kind.as_str() {
            "CONST" => {
                let v = parse_const_value(&g.value).ok_or_else(|| {
                    anyhow!(
                        "CONST gate {gate_idx} value is not numeric: {:?}",
                        g.value
                    )
                })?;
                let fe = float_to_field(v, FIXED_POINT_BITS)?;
                Wire {
                    target: builder.constant(fe),
                    scale_bits: FIXED_POINT_BITS,
                }
            }
            "INPUT" => {
                let t = builder.add_virtual_target();
                builder.register_public_input(t);
                input_targets.push(t);
                Wire {
                    target: t,
                    scale_bits: FIXED_POINT_BITS,
                }
            }
            "ADD" | "SUB" => {
                let (a, b) = pair(&wires, g.inputs.as_slice(), &g.kind, gate_idx)?;
                let (a_t, b_t, scale) = align_scales(&mut builder, a, b)?;
                let target = if g.kind == "ADD" {
                    builder.add(a_t, b_t)
                } else {
                    builder.sub(a_t, b_t)
                };
                Wire {
                    target,
                    scale_bits: scale,
                }
            }
            "MUL" => {
                let (a, b) = pair(&wires, g.inputs.as_slice(), &g.kind, gate_idx)?;
                let new_scale = a.scale_bits + b.scale_bits;
                if new_scale > MAX_OUTPUT_SCALE_BITS {
                    bail!(
                        "MUL chain at gate {gate_idx} would push scale to {new_scale} bits — \
                         Goldilocks safe range is {MAX_OUTPUT_SCALE_BITS}; circuit exceeds Phase 1 \
                         backend limits, route via transparent fallback"
                    );
                }
                Wire {
                    target: builder.mul(a.target, b.target),
                    scale_bits: new_scale,
                }
            }
            "NEG" => {
                let a = unary(&wires, g.inputs.as_slice(), "NEG", gate_idx)?;
                Wire {
                    target: builder.neg(a.target),
                    scale_bits: a.scale_bits,
                }
            }
            "OUTPUT" => {
                let a = unary(&wires, g.inputs.as_slice(), "OUTPUT", gate_idx)?;
                builder.register_public_input(a.target);
                output_scale = Some(a.scale_bits);
                a
            }
            other => bail!(
                "Plonky2 backend cannot lower gate `{other}` at index {gate_idx} — \
                 only CONST/INPUT/ADD/SUB/MUL/NEG/OUTPUT are supported in Phase 1"
            ),
        };
        wires.push(wire);
    }

    let output_scale_bits =
        output_scale.ok_or_else(|| anyhow!("circuit has no OUTPUT gate"))?;
    let data = builder.build::<C>();

    Ok(BuiltCircuit {
        data,
        input_targets,
        output_scale_bits,
    })
}

fn pair(wires: &[Wire], inputs: &[usize], kind: &str, idx: usize) -> Result<(Wire, Wire)> {
    if inputs.len() != 2 {
        bail!(
            "{kind} gate at index {idx} expects 2 inputs, got {}",
            inputs.len()
        );
    }
    let a = *wires
        .get(inputs[0])
        .ok_or_else(|| anyhow!("{kind} gate {idx} references missing wire {}", inputs[0]))?;
    let b = *wires
        .get(inputs[1])
        .ok_or_else(|| anyhow!("{kind} gate {idx} references missing wire {}", inputs[1]))?;
    Ok((a, b))
}

fn unary(wires: &[Wire], inputs: &[usize], kind: &str, idx: usize) -> Result<Wire> {
    if inputs.len() != 1 {
        bail!(
            "{kind} gate at index {idx} expects 1 input, got {}",
            inputs.len()
        );
    }
    Ok(*wires
        .get(inputs[0])
        .ok_or_else(|| anyhow!("{kind} gate {idx} references missing wire {}", inputs[0]))?)
}

fn align_scales(
    builder: &mut CircuitBuilder<F, D>,
    a: Wire,
    b: Wire,
) -> Result<(Target, Target, u32)> {
    use std::cmp::Ordering;
    match a.scale_bits.cmp(&b.scale_bits) {
        Ordering::Equal => Ok((a.target, b.target, a.scale_bits)),
        Ordering::Less => {
            let diff = b.scale_bits - a.scale_bits;
            if diff >= 63 {
                bail!("scale gap {diff} bits exceeds u64 range");
            }
            let factor = F::from_canonical_u64(1u64 << diff);
            let new_a = builder.mul_const(factor, a.target);
            Ok((new_a, b.target, b.scale_bits))
        }
        Ordering::Greater => {
            let diff = a.scale_bits - b.scale_bits;
            if diff >= 63 {
                bail!("scale gap {diff} bits exceeds u64 range");
            }
            let factor = F::from_canonical_u64(1u64 << diff);
            let new_b = builder.mul_const(factor, b.target);
            Ok((a.target, new_b, a.scale_bits))
        }
    }
}

// ── Encoding ──────────────────────────────────────────────────────

fn parse_const_value(v: &serde_json::Value) -> Option<f64> {
    if let Some(n) = v.as_f64() {
        return Some(n);
    }
    if let Some(s) = v.as_str() {
        return s.parse::<f64>().ok();
    }
    if let Some(n) = v.as_i64() {
        return Some(n as f64);
    }
    None
}

fn float_to_field(x: f64, scale_bits: u32) -> Result<F> {
    if !x.is_finite() {
        bail!("non-finite value {x} cannot be encoded into the Goldilocks field");
    }
    let scale = (1u64 << scale_bits) as f64;
    let scaled = (x * scale).round();
    let half = (GOLDILOCKS_P / 2) as f64;
    if scaled.abs() >= half {
        bail!(
            "value {x} (scaled to {scaled}) overflows Goldilocks half-range; \
             reduce input magnitude or lower MUL depth"
        );
    }
    if scaled >= 0.0 {
        Ok(F::from_canonical_u64(scaled as u64))
    } else {
        Ok(F::ZERO - F::from_canonical_u64((-scaled) as u64))
    }
}

fn field_to_float(f: F, scale_bits: u32) -> f64 {
    let raw = f.to_canonical_u64();
    let half = GOLDILOCKS_P / 2;
    // i128 detour avoids the silent truncation that an `as i64` would
    // perform near the half-prime mark.
    let signed: f64 = if raw > half {
        -((GOLDILOCKS_P - raw) as i128 as f64)
    } else {
        raw as i128 as f64
    };
    signed / (1u64 << scale_bits) as f64
}

// ── Canonical circuit hash (matches lang/zkproof/circuit.py) ──────

/// Reproduce Python's `canonical_circuit_hash` byte for byte. Both
/// sides serialise to JSON with sorted keys, no whitespace, and
/// `ensure_ascii=False`; both sides hash the UTF-8 bytes with SHA-256.
fn canonical_circuit_hash(desc: &CircuitDescription) -> Result<String> {
    use sha2::{Digest, Sha256};
    let view = CircuitView {
        chain: desc.chain_order,
        function_name: &desc.function_name,
        gates: desc
            .gates
            .iter()
            .map(|g| GateView {
                i: &g.inputs,
                k: &g.kind,
                v: &g.value,
            })
            .collect(),
        out: desc.output_index,
        params: &desc.params,
        public_in: &desc.public_input_indices,
    };
    let bytes = serde_json::to_vec(&view).context("serialising circuit for hashing")?;
    let digest = Sha256::digest(&bytes);
    Ok(format!("sha256:{:x}", digest))
}

// Field order is alphabetical to match Python's `sort_keys=True`.
#[derive(Serialize)]
struct CircuitView<'a> {
    chain: u32,
    #[serde(rename = "fn")]
    function_name: &'a str,
    gates: Vec<GateView<'a>>,
    out: Option<usize>,
    params: &'a [String],
    public_in: &'a [usize],
}

#[derive(Serialize)]
struct GateView<'a> {
    i: &'a [usize],
    k: &'a str,
    v: &'a serde_json::Value,
}

// ── Tests ─────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn round_trip_encoding() {
        for x in [0.0, 1.5, -1.5, 100.25, -100.25, 0.0001] {
            let f = float_to_field(x, FIXED_POINT_BITS).unwrap();
            let back = field_to_float(f, FIXED_POINT_BITS);
            // Quantisation tolerance: half a least-significant bit at scale 16.
            let q = 1.0 / (1u64 << FIXED_POINT_BITS) as f64;
            assert!((back - x).abs() <= q, "x={x}, back={back}");
        }
    }

    #[test]
    fn linear_circuit_proves_and_verifies() {
        // y = 2*x + 3
        let desc: CircuitDescription = serde_json::from_value(json!({
            "fn": "linear",
            "params": ["x"],
            "chain": 0,
            "public_in": [0],
            "out": 4,
            "gates": [
                {"k": "INPUT", "i": [], "v": "x"},
                {"k": "CONST", "i": [], "v": "2.0"},
                {"k": "MUL",   "i": [0, 1], "v": null},
                {"k": "CONST", "i": [], "v": "3.0"},
                {"k": "ADD",   "i": [2, 3], "v": null},
                {"k": "OUTPUT","i": [4],    "v": null}
            ]
        }))
        .unwrap();

        let mut inputs = serde_json::Map::new();
        inputs.insert("x".into(), json!(1.5));
        let proof = prove(&desc, &inputs, "sha256:deadbeef").unwrap();
        assert!((proof.output - 6.0).abs() < 0.01);

        let res = verify(&desc, &proof, "sha256:deadbeef").unwrap();
        assert!(res.is_valid, "verify failed: {}", res.reason);

        let bad = verify(&desc, &proof, "sha256:cafe").unwrap();
        assert!(!bad.is_valid, "tampered fingerprint accepted");
    }
}
