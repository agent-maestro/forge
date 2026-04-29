//! monogate-sys -- Rust runtime for EML-lang.
//!
//! Mirrors `software/runtime/c/libmonogate.h`. Same operator names,
//! same semantics; the EML-lang Rust backend (software/backends/
//! rust_backend.py) emits calls into this crate.
//!
//! License: MIT.

#![no_std]

extern crate libm;

// ── EML primitive ───────────────────────────────────────────────

/// `eml(x, y) = exp(x) - ln(y)`. Domain: `y > 0`.
#[inline]
pub fn mg_eml(x: f64, y: f64) -> f64 {
    libm::exp(x) - libm::log(y)
}

// ── EML family operators (per data/operators.json) ──────────────

#[inline] pub fn mg_eal(x: f64, y: f64) -> f64 { libm::exp(x) + libm::log(y) }
#[inline] pub fn mg_exl(x: f64, y: f64) -> f64 { libm::exp(x) * libm::log(y) }
#[inline] pub fn mg_edl(x: f64, y: f64) -> f64 { libm::exp(x) / libm::log(y) }
#[inline] pub fn mg_epl(x: f64, y: f64) -> f64 { libm::pow(libm::exp(x), libm::log(y)) }
#[inline] pub fn mg_lediv(x: f64, y: f64) -> f64 { libm::log(libm::exp(x) / y) }
#[inline] pub fn mg_elsb(x: f64, y: f64) -> f64 { libm::exp(x - libm::log(y)) }
#[inline] pub fn mg_elad(x: f64, y: f64) -> f64 { libm::exp(libm::log(x) + y) }
#[inline] pub fn mg_deml(x: f64, y: f64) -> f64 { libm::exp(-x) - libm::log(y) }

// ── One-arg convenience wrappers ────────────────────────────────

#[inline] pub fn mg_exp(x: f64) -> f64 { mg_eml(x, 1.0) }
#[inline] pub fn mg_ln(x: f64)  -> f64 { -mg_eml(0.0, x) + 1.0 }

#[inline] pub fn mg_sin(x: f64) -> f64 { libm::sin(x) }
#[inline] pub fn mg_cos(x: f64) -> f64 { libm::cos(x) }
#[inline] pub fn mg_tan(x: f64) -> f64 { libm::tan(x) }

#[inline] pub fn mg_sinh(x: f64) -> f64 { (libm::exp(x) - libm::exp(-x)) * 0.5 }
#[inline] pub fn mg_cosh(x: f64) -> f64 { (libm::exp(x) + libm::exp(-x)) * 0.5 }
#[inline]
pub fn mg_tanh(x: f64) -> f64 {
    let ex = libm::exp(x);
    let enx = libm::exp(-x);
    (ex - enx) / (ex + enx)
}

#[inline] pub fn mg_asin(x: f64)  -> f64 { libm::asin(x) }
#[inline] pub fn mg_acos(x: f64)  -> f64 { libm::acos(x) }
#[inline] pub fn mg_atan(x: f64)  -> f64 { libm::atan(x) }
#[inline] pub fn mg_asinh(x: f64) -> f64 { libm::asinh(x) }
#[inline] pub fn mg_acosh(x: f64) -> f64 { libm::acosh(x) }
#[inline] pub fn mg_atanh(x: f64) -> f64 { libm::atanh(x) }

#[inline] pub fn mg_sqrt(x: f64) -> f64 { libm::sqrt(x) }
#[inline] pub fn mg_abs(x: f64)  -> f64 { libm::fabs(x) }
#[inline] pub fn mg_pow(x: f64, y: f64) -> f64 { libm::pow(x, y) }

#[inline]
pub fn mg_clamp(x: f64, lo: f64, hi: f64) -> f64 {
    libm::fmin(libm::fmax(x, lo), hi)
}

// ── Test --- runs in std mode only ──────────────────────────────

#[cfg(test)]
mod tests {
    extern crate std;
    use super::*;

    #[test]
    fn eml_zero_one_is_one() {
        // eml(0, 1) = exp(0) - ln(1) = 1 - 0 = 1
        assert!((mg_eml(0.0, 1.0) - 1.0).abs() < 1e-15);
    }

    #[test]
    fn exp_via_eml_matches_libm() {
        for &x in &[-2.0_f64, -0.5, 0.0, 0.5, 1.0, 2.0] {
            let from_eml = mg_exp(x);
            let from_libm = libm::exp(x);
            assert!((from_eml - from_libm).abs() < 1e-15);
        }
    }

    #[test]
    fn sinh_matches_libm() {
        for &x in &[-2.0_f64, 0.0, 1.0, 2.0] {
            let ours = mg_sinh(x);
            let theirs = libm::sinh(x);
            assert!((ours - theirs).abs() < 1e-15);
        }
    }
}
