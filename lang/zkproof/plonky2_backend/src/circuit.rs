//! Circuit JSON deserialisation — mirrors `lang/zkproof/circuit.py`.
//!
//! The Python emitter produces `circuit_to_dict()` output that this
//! module reads back into Rust structs. Field names match the
//! Python emit (`k`, `i`, `v`, `fn`, `params`, `gates`, `chain`,
//! `public_in`, `out`) — keep in lockstep.

use serde::{Deserialize, Serialize};

/// One gate. `kind` is the GateKind string from the Python enum.
/// `inputs` are wire indices into the circuit's gate list.
/// `value` is the constant payload (CONST: float, INPUT: param name).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GateDescription {
    #[serde(rename = "k")]
    pub kind: String,
    #[serde(rename = "i", default)]
    pub inputs: Vec<usize>,
    #[serde(rename = "v", default)]
    pub value: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CircuitDescription {
    #[serde(rename = "fn")]
    pub function_name: String,
    pub params: Vec<String>,
    pub gates: Vec<GateDescription>,
    #[serde(rename = "chain")]
    pub chain_order: u32,
    #[serde(rename = "public_in")]
    pub public_input_indices: Vec<usize>,
    #[serde(rename = "out")]
    pub output_index: Option<usize>,
}

impl CircuitDescription {
    /// Returns the largest set of GateKinds the Plonky2 backend can
    /// natively handle (Phase 1.1 — pure arithmetic). When this
    /// returns false, the Python bridge falls back to the transparent
    /// stub prover so the integration is incremental.
    pub fn is_arithmetic_only(&self) -> bool {
        for g in &self.gates {
            match g.kind.as_str() {
                "CONST" | "INPUT" | "ADD" | "SUB" | "MUL"
                | "NEG"   | "OUTPUT" => continue,
                _ => return false,
            }
        }
        true
    }
}
