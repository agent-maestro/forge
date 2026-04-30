//! monogate-sys -- Rust runtime for EML-lang.
//!
//! Mirrors `software/runtime/c/libmonogate.h`. Same operator names,
//! same semantics; the EML-lang Rust backend (software/backends/
//! rust_backend.py) emits calls into this crate.
//!
//! Layout: core EML family, standard math wrappers, activation /
//! growth operators, SuperBEST routing variants (Patent #01),
//! and f32 mirrors for chain-precision selection (Phase 3).
//!
//! License: MIT.

#![no_std]

extern crate libm;

// ── Version ─────────────────────────────────────────────────────

pub const VERSION: &str = "0.1.0";

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

// ── Standard math wrappers ──────────────────────────────────────

#[inline] pub fn mg_exp(x: f64) -> f64 { libm::exp(x) }
#[inline] pub fn mg_ln(x: f64)  -> f64 { libm::log(x) }
#[inline] pub fn mg_log(x: f64) -> f64 { libm::log(x) }

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

// ── Division ────────────────────────────────────────────────────

/// `mg_div(x, y) = x / y`. Domain: `y != 0`.
#[inline] pub fn mg_div(x: f64, y: f64) -> f64 { x / y }

/// `mg_safe_div(x, y)` -- saturating, NaN-free. Returns sign(x)*sign(y)*MAX
/// when `|y| < 1e-300`, else `x / y`. Patent #14 hardware reference.
#[inline]
pub fn mg_safe_div(x: f64, y: f64) -> f64 {
    if libm::fabs(y) < 1e-300 {
        let sx = if x > 0.0 { 1.0 } else if x < 0.0 { -1.0 } else { 0.0 };
        let sy = if y >= 0.0 { 1.0 } else { -1.0 };
        return sx * sy * f64::MAX;
    }
    x / y
}

// ── Activation / growth operators ───────────────────────────────

#[inline] pub fn mg_sigmoid(x: f64) -> f64 { 1.0 / (1.0 + libm::exp(-x)) }
#[inline] pub fn mg_softplus(x: f64) -> f64 { libm::log(1.0 + libm::exp(x)) }
#[inline] pub fn mg_relu(x: f64) -> f64 { if x > 0.0 { x } else { 0.0 } }

/// `mg_logistic(t, K, r, x0) = K / (1 + exp(-r * (t - x0)))`.
#[inline]
pub fn mg_logistic(t: f64, k: f64, r: f64, x0: f64) -> f64 {
    k / (1.0 + libm::exp(-r * (t - x0)))
}

/// `mg_gompertz(t, K, r, x0) = K * exp(-exp(-r * (t - x0)))`.
#[inline]
pub fn mg_gompertz(t: f64, k: f64, r: f64, x0: f64) -> f64 {
    k * libm::exp(-libm::exp(-r * (t - x0)))
}

// ── SuperBEST routing variants (Patent #01) ─────────────────────

/// Pick the canonical tanh form by sub-domain.
#[inline]
pub fn mg_tanh_route(x: f64) -> f64 {
    let ax = libm::fabs(x);
    if ax < 1e-8 { return x; }
    if ax > 20.0 { return if x > 0.0 { 1.0 } else { -1.0 }; }
    let ex = libm::exp(x);
    let enx = libm::exp(-x);
    (ex - enx) / (ex + enx)
}

/// Overflow-safe sigmoid.
#[inline]
pub fn mg_sigmoid_route(x: f64) -> f64 {
    if x >= 0.0 {
        1.0 / (1.0 + libm::exp(-x))
    } else {
        let ex = libm::exp(x);
        ex / (1.0 + ex)
    }
}

/// Overflow-safe softplus.
#[inline]
pub fn mg_softplus_route(x: f64) -> f64 {
    if x > 20.0 { return x; }
    if x < -20.0 { return libm::exp(x); }
    libm::log(1.0 + libm::exp(x))
}

/// `ln(1 + x)`, accurate near zero.
#[inline] pub fn mg_log1p_route(x: f64) -> f64 { libm::log1p(x) }

/// `exp(x) - 1`, accurate near zero.
#[inline] pub fn mg_expm1_route(x: f64) -> f64 { libm::expm1(x) }

// ── f32 mirrors (chain-precision selection, Phase 3) ────────────

#[inline] pub fn mg_eml_f32(x: f32, y: f32) -> f32 { libm::expf(x) - libm::logf(y) }
#[inline] pub fn mg_exp_f32(x: f32) -> f32 { libm::expf(x) }
#[inline] pub fn mg_ln_f32(x: f32) -> f32 { libm::logf(x) }
#[inline] pub fn mg_log_f32(x: f32) -> f32 { libm::logf(x) }
#[inline] pub fn mg_sin_f32(x: f32) -> f32 { libm::sinf(x) }
#[inline] pub fn mg_cos_f32(x: f32) -> f32 { libm::cosf(x) }
#[inline] pub fn mg_tan_f32(x: f32) -> f32 { libm::tanf(x) }
#[inline] pub fn mg_sqrt_f32(x: f32) -> f32 { libm::sqrtf(x) }
#[inline] pub fn mg_abs_f32(x: f32) -> f32 { libm::fabsf(x) }
#[inline] pub fn mg_pow_f32(x: f32, y: f32) -> f32 { libm::powf(x, y) }
#[inline] pub fn mg_div_f32(x: f32, y: f32) -> f32 { x / y }

#[inline]
pub fn mg_tanh_f32(x: f32) -> f32 {
    let ex = libm::expf(x);
    let enx = libm::expf(-x);
    (ex - enx) / (ex + enx)
}

#[inline]
pub fn mg_sigmoid_f32(x: f32) -> f32 {
    1.0 / (1.0 + libm::expf(-x))
}

#[inline]
pub fn mg_softplus_f32(x: f32) -> f32 {
    libm::logf(1.0 + libm::expf(x))
}

#[inline]
pub fn mg_clamp_f32(x: f32, lo: f32, hi: f32) -> f32 {
    libm::fminf(libm::fmaxf(x, lo), hi)
}

// ── Tests --- runs in std mode only ─────────────────────────────

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
    fn exp_matches_libm() {
        for &x in &[-2.0_f64, -0.5, 0.0, 0.5, 1.0, 2.0] {
            assert!((mg_exp(x) - libm::exp(x)).abs() < 1e-15);
        }
    }

    #[test]
    fn ln_matches_libm() {
        for &x in &[0.5_f64, 1.0, 2.0, 10.0] {
            assert!((mg_ln(x) - libm::log(x)).abs() < 1e-15);
        }
    }

    #[test]
    fn sinh_matches_libm() {
        for &x in &[-2.0_f64, 0.0, 1.0, 2.0] {
            assert!((mg_sinh(x) - libm::sinh(x)).abs() < 1e-15);
        }
    }

    #[test]
    fn tanh_matches_libm() {
        for &x in &[-3.0_f64, -0.5, 0.0, 0.5, 3.0] {
            assert!((mg_tanh(x) - libm::tanh(x)).abs() < 1e-12);
        }
    }

    #[test]
    fn div_basic() {
        assert!((mg_div(6.0, 2.0) - 3.0).abs() < 1e-15);
    }

    #[test]
    fn safe_div_saturates() {
        let v = mg_safe_div(1.0, 0.0);
        assert!(v >= f64::MAX / 2.0);
        let v2 = mg_safe_div(-1.0, 0.0);
        assert!(v2 <= -f64::MAX / 2.0);
    }

    #[test]
    fn sigmoid_at_zero_is_half() {
        assert!((mg_sigmoid(0.0) - 0.5).abs() < 1e-15);
    }

    #[test]
    fn sigmoid_route_overflow_safe() {
        // exp(-large) would overflow if used naively; routed form returns ~0
        let v = mg_sigmoid_route(-1000.0);
        assert!(v.is_finite());
        assert!(v >= 0.0 && v <= 1e-300);
    }

    #[test]
    fn softplus_route_large_x() {
        // For x > 20, ln(1+exp(x)) ~= x; routed form returns exactly x
        let v = mg_softplus_route(50.0);
        assert!((v - 50.0).abs() < 1e-12);
    }

    #[test]
    fn softplus_route_negative_large() {
        // For x < -20, softplus ~= exp(x); routed form returns exp(x)
        let v = mg_softplus_route(-50.0);
        assert!(v.is_finite() && v > 0.0);
    }

    #[test]
    fn tanh_route_saturates() {
        assert!((mg_tanh_route(100.0) - 1.0).abs() < 1e-15);
        assert!((mg_tanh_route(-100.0) + 1.0).abs() < 1e-15);
    }

    #[test]
    fn tanh_route_near_zero_is_identity() {
        // For |x| < 1e-8, tanh(x) ~= x
        let x = 1e-12_f64;
        assert!((mg_tanh_route(x) - x).abs() < 1e-20);
    }

    #[test]
    fn logistic_at_x0_is_half_k() {
        // K / (1 + exp(0)) = K / 2
        let v = mg_logistic(5.0, 100.0, 1.0, 5.0);
        assert!((v - 50.0).abs() < 1e-12);
    }

    #[test]
    fn gompertz_at_x0_is_k_over_e() {
        // K * exp(-exp(0)) = K * exp(-1) = K / e
        let v = mg_gompertz(5.0, 100.0, 1.0, 5.0);
        assert!((v - 100.0 * libm::exp(-1.0)).abs() < 1e-12);
    }

    #[test]
    fn relu_basic() {
        assert!((mg_relu(-1.0) - 0.0).abs() < 1e-15);
        assert!((mg_relu(2.5) - 2.5).abs() < 1e-15);
    }

    #[test]
    fn f32_mirrors_present() {
        // Smoke-test that the f32 mirrors compile and produce sane values.
        let v = mg_sigmoid_f32(0.0_f32);
        assert!((v - 0.5_f32).abs() < 1e-7);
    }
}
