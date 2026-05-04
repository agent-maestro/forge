//! `monogate-zk` — CLI front-end to the Plonky2 prover for the
//! Monogate Verification Network.
//!
//! Two subcommands:
//!
//!   monogate-zk prove   --circuit foo.zkc.json --inputs '{"x":1.5}' \
//!                       --fingerprint sha256:... --out proof.json
//!
//!   monogate-zk verify  --circuit foo.zkc.json --proof proof.json \
//!                       --fingerprint sha256:...
//!
//! The CLI is the contract surface that `lang/zkproof/prover.py`
//! shells out to. Both subcommands speak JSON in / JSON out so the
//! Python bridge can stay subprocess-based without parsing binary
//! formats.

use anyhow::{anyhow, Context, Result};
use clap::{Parser, Subcommand};
use std::fs;
use std::path::PathBuf;

mod circuit;
mod proof_io;

use circuit::CircuitDescription;

#[derive(Parser)]
#[command(name = "monogate-zk", version, about)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// Build a Plonky2 circuit from a `.zkc.json`, prove it on the
    /// given inputs, write a proof JSON.
    Prove {
        /// Path to a circuit JSON.
        #[arg(long)]
        circuit: PathBuf,
        /// JSON object of inputs, e.g. `{"x": 1.5, "mu": 0.0}`.
        #[arg(long)]
        inputs: String,
        /// `sha256:…` of the producing module's fingerprint.
        #[arg(long)]
        fingerprint: String,
        /// Where to write the proof JSON. Defaults to stdout.
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// Verify a proof JSON against a circuit JSON.
    Verify {
        #[arg(long)]
        circuit: PathBuf,
        #[arg(long)]
        proof: PathBuf,
        #[arg(long)]
        fingerprint: String,
    },
    /// Print a JSON summary of capabilities — used by the Python
    /// bridge to decide which proofs to route to this backend vs
    /// the transparent fallback.
    Capabilities,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Cmd::Prove { circuit, inputs, fingerprint, out } => {
            let desc = load_circuit(&circuit)?;
            let inputs_obj: serde_json::Map<String, serde_json::Value> =
                serde_json::from_str(&inputs).context("parsing --inputs")?;
            let proof = proof_io::prove(&desc, &inputs_obj, &fingerprint)?;
            let payload = serde_json::to_string_pretty(&proof)?;
            match out {
                Some(p) => fs::write(p, payload + "\n")?,
                None    => println!("{}", payload),
            }
        }
        Cmd::Verify { circuit, proof, fingerprint } => {
            let desc = load_circuit(&circuit)?;
            let proof_obj: proof_io::Plonky2Proof =
                serde_json::from_str(&fs::read_to_string(&proof)?)
                    .context("parsing proof JSON")?;
            let result = proof_io::verify(&desc, &proof_obj, &fingerprint)?;
            let env = serde_json::json!({
                "is_valid": result.is_valid,
                "reason":   result.reason,
            });
            println!("{}", serde_json::to_string_pretty(&env)?);
            if !result.is_valid {
                std::process::exit(1);
            }
        }
        Cmd::Capabilities => {
            let caps = serde_json::json!({
                "spec":              "monogate-zkproof/v1",
                "backend":           "plonky2",
                "field":             "Goldilocks",
                "fixed_point_bits":  proof_io::FIXED_POINT_BITS,
                "transcendental_strategy": "lookup-table-stub",
                "supported_gates": [
                    "CONST", "INPUT", "ADD", "SUB", "MUL", "NEG", "OUTPUT"
                ],
                "deferred_gates": [
                    "DIV", "MOD", "POW",
                    "EXP", "LN", "SIN", "COS", "TAN",
                    "SQRT", "ASIN", "ACOS", "ATAN",
                    "SINH", "COSH", "TANH",
                    "ABS", "CLAMP", "MIN", "MAX"
                ],
            });
            println!("{}", serde_json::to_string_pretty(&caps)?);
        }
    }
    Ok(())
}

fn load_circuit(path: &PathBuf) -> Result<CircuitDescription> {
    let text = fs::read_to_string(path)
        .with_context(|| format!("reading {}", path.display()))?;
    let v: serde_json::Value = serde_json::from_str(&text)?;
    // Accept either a circuit object directly OR `{circuit: {...}}`
    // wrapper from the bundled `--target zkproof` output.
    let inner = if let Some(c) = v.get("circuit") { c.clone() } else { v };
    let desc: CircuitDescription = serde_json::from_value(inner)
        .map_err(|e| anyhow!("circuit JSON did not match the expected shape: {e}"))?;
    Ok(desc)
}
