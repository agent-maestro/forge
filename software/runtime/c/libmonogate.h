/*
 * libmonogate.h -- C runtime for EML-lang.
 *
 * Header-only inline runtime for code emitted by the EML-lang
 * compiler (software/backends/c_backend.py). Every operator
 * either decomposes to libm primitives or routes through a
 * SuperBEST canonical form that minimizes precision loss for
 * the input sub-domain (Patent #01).
 *
 * Layout
 * ======
 *
 *   1. EML primitive (mg_eml) and the 8 sibling family operators
 *      from data/operators.json (eal, exl, edl, epl, lediv, elsb,
 *      elad, deml).
 *
 *   2. Standard math wrappers (mg_exp, mg_ln, mg_sin, ...) that
 *      delegate to libm. These are what the C backend emits for
 *      every NodeKind in _BUILTIN_TO_C.
 *
 *   3. Activation / growth operators (mg_sigmoid, mg_softplus,
 *      mg_logistic, mg_gompertz). Used by ML inference + the
 *      G-series biological-growth verticals.
 *
 *   4. SuperBEST routing variants (mg_*_route). Pick the canonical
 *      form by sub-domain. Slower than the direct path; emitted
 *      when the optimizer marks a node as drift-risky.
 *
 *   5. f32 mirrors. Phase 3 chain-precision selection emits these
 *      when chain_order < 1 (low cost-class -> safe to demote).
 *
 *   6. Diagnostics + version macros.
 *
 * License: MIT (see LICENSE).
 */

#ifndef LIBMONOGATE_H
#define LIBMONOGATE_H

#include <math.h>
#include <stdint.h>
#include <float.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── Versioning ─────────────────────────────────────────────── */
#define LIBMONOGATE_VERSION_MAJOR 0
#define LIBMONOGATE_VERSION_MINOR 1
#define LIBMONOGATE_VERSION_PATCH 0
#define LIBMONOGATE_VERSION_STRING "0.1.0"

/* ── Domain-check macros (debug-only) ───────────────────────── */
/*
 * In debug builds, these abort on domain violation. In release,
 * they vanish to zero overhead -- generated code stays inline.
 * Define MG_DEBUG to enable runtime checks.
 */
#ifdef MG_DEBUG
  #include <assert.h>
  #define MG_REQUIRE_POSITIVE(x) assert((x) > 0.0)
  #define MG_REQUIRE_FINITE(x)   assert(isfinite(x))
  #define MG_REQUIRE_NONZERO(x)  assert((x) != 0.0)
#else
  #define MG_REQUIRE_POSITIVE(x) ((void)0)
  #define MG_REQUIRE_FINITE(x)   ((void)0)
  #define MG_REQUIRE_NONZERO(x)  ((void)0)
#endif

/* ── The EML primitive ──────────────────────────────────────── */

/*
 * eml(x, y) = exp(x) - ln(y)
 * Domain: y > 0
 *
 * The universal EML operator. Every higher-level function in
 * the stdlib decomposes to this primitive (see stdlib/math.eml).
 */
static inline double mg_eml(double x, double y) {
    MG_REQUIRE_POSITIVE(y);
    return exp(x) - log(y);
}

/* ── EML family operators (per data/operators.json) ─────────── */

static inline double mg_eal(double x, double y) {
    /* eal(x, y) = exp(x) + ln(y), y > 0 */
    MG_REQUIRE_POSITIVE(y);
    return exp(x) + log(y);
}

static inline double mg_exl(double x, double y) {
    /* exl(x, y) = exp(x) * ln(y), y > 0 */
    MG_REQUIRE_POSITIVE(y);
    return exp(x) * log(y);
}

static inline double mg_edl(double x, double y) {
    /* edl(x, y) = exp(x) / ln(y), y > 0, y != 1 */
    MG_REQUIRE_POSITIVE(y);
    return exp(x) / log(y);
}

static inline double mg_epl(double x, double y) {
    /* epl(x, y) = exp(x) ^ ln(y) = exp(ln(y) * exp(x)), y > 0 */
    MG_REQUIRE_POSITIVE(y);
    return pow(exp(x), log(y));
}

static inline double mg_lediv(double x, double y) {
    /* lediv(x, y) = ln(exp(x) / y), y > 0 */
    MG_REQUIRE_POSITIVE(y);
    return log(exp(x) / y);
}

static inline double mg_elsb(double x, double y) {
    /* elsb(x, y) = exp(x - ln(y)) = exp(x) / y, y > 0 */
    MG_REQUIRE_POSITIVE(y);
    return exp(x - log(y));
}

static inline double mg_elad(double x, double y) {
    /* elad(x, y) = exp(ln(x) + y) = x * exp(y), x > 0 */
    MG_REQUIRE_POSITIVE(x);
    return exp(log(x) + y);
}

static inline double mg_deml(double x, double y) {
    /* deml(x, y) = exp(-x) - ln(y), y > 0 */
    MG_REQUIRE_POSITIVE(y);
    return exp(-x) - log(y);
}

/* ── Standard math wrappers ─────────────────────────────────── */

static inline double mg_exp(double x) { return exp(x); }
static inline double mg_ln(double x)  { MG_REQUIRE_POSITIVE(x); return log(x); }
static inline double mg_log(double x) { return mg_ln(x); }  /* alias */

/* Trig */
static inline double mg_sin(double x) { return sin(x); }
static inline double mg_cos(double x) { return cos(x); }
static inline double mg_tan(double x) { return tan(x); }

/* Hyperbolic via real-exp combinations (matches Lean reference) */
static inline double mg_sinh(double x) { return (exp(x) - exp(-x)) * 0.5; }
static inline double mg_cosh(double x) { return (exp(x) + exp(-x)) * 0.5; }
static inline double mg_tanh(double x) {
    double ex = exp(x), enx = exp(-x);
    return (ex - enx) / (ex + enx);
}

/* Inverse trig / hyp -- libm */
static inline double mg_asin(double x)  { return asin(x); }
static inline double mg_acos(double x)  { return acos(x); }
static inline double mg_atan(double x)  { return atan(x); }
static inline double mg_asinh(double x) { return asinh(x); }
static inline double mg_acosh(double x) { return acosh(x); }
static inline double mg_atanh(double x) { return atanh(x); }

/* Sqrt + abs */
static inline double mg_sqrt(double x) { return sqrt(x); }
static inline double mg_abs(double x)  { return fabs(x); }

/* Pow + clamp */
static inline double mg_pow(double x, double y) { return pow(x, y); }
static inline double mg_clamp(double x, double lo, double hi) {
    return fmin(fmax(x, lo), hi);
}

/* ── Division ───────────────────────────────────────────────── */

/*
 * mg_div(x, y) = x / y -- the bare division operator.
 * Domain: y != 0. Caller is responsible for the guard.
 */
static inline double mg_div(double x, double y) {
    MG_REQUIRE_NONZERO(y);
    return x / y;
}

/*
 * mg_safe_div(x, y) -- saturating division, NaN-free.
 * Returns sign(x)*sign(y)*DBL_MAX when |y| < 1e-300, else x / y.
 * Used by Patent #14 hardware reference where division-by-zero
 * must produce a well-defined fixed-point output.
 */
static inline double mg_safe_div(double x, double y) {
    if (fabs(y) < 1e-300) {
        double sx = (x > 0.0) - (x < 0.0);
        double sy = (y >= 0.0) ? 1.0 : -1.0;
        return sx * sy * DBL_MAX;
    }
    return x / y;
}

/* ── Activation / growth operators ──────────────────────────── */

/*
 * mg_sigmoid(x) = 1 / (1 + exp(-x))
 * Naive form -- see mg_sigmoid_route for overflow-safe variant.
 */
static inline double mg_sigmoid(double x) {
    return 1.0 / (1.0 + exp(-x));
}

/*
 * mg_softplus(x) = ln(1 + exp(x))
 * Naive form -- see mg_softplus_route for overflow-safe variant.
 */
static inline double mg_softplus(double x) {
    return log(1.0 + exp(x));
}

/*
 * mg_logistic(t, K, r, x0) = K / (1 + exp(-r * (t - x0)))
 * Verhulst growth -- chain order 1 (the K-divisor folds into
 * the canonical sigmoid scaling).
 */
static inline double mg_logistic(double t, double K, double r, double x0) {
    return K / (1.0 + exp(-r * (t - x0)));
}

/*
 * mg_gompertz(t, K, r, x0) = K * exp(-exp(-r * (t - x0)))
 * Gompertz growth -- chain order 2 (nested exp).
 */
static inline double mg_gompertz(double t, double K, double r, double x0) {
    return K * exp(-exp(-r * (t - x0)));
}

/*
 * mg_relu(x) = max(0, x). Cost class p0-d0-w0-c0.
 */
static inline double mg_relu(double x) {
    return x > 0.0 ? x : 0.0;
}

/* ── SuperBEST routing variants (Patent #01) ────────────────── */

/*
 * mg_tanh_route(x) -- pick the canonical tanh form by sub-domain.
 *
 *   |x| < 1e-8  -> x  (Taylor series, avoids catastrophic cancellation)
 *   |x| > 20    -> sign(x)  (saturates within f64 epsilon)
 *   else        -> standard exp formulation
 *
 * Picks up ~1.5 ULPs near zero vs naive (exp(x)-exp(-x))/(exp(x)+exp(-x)).
 */
static inline double mg_tanh_route(double x) {
    double ax = fabs(x);
    if (ax < 1e-8)  return x;
    if (ax > 20.0)  return (x > 0.0) ? 1.0 : -1.0;
    double ex = exp(x), enx = exp(-x);
    return (ex - enx) / (ex + enx);
}

/*
 * mg_sigmoid_route(x) -- overflow-safe sigmoid.
 *
 *   x >= 0  -> 1 / (1 + exp(-x))
 *   x <  0  -> exp(x) / (1 + exp(x))
 *
 * Avoids exp(large) overflow on the negative tail.
 */
static inline double mg_sigmoid_route(double x) {
    if (x >= 0.0) {
        return 1.0 / (1.0 + exp(-x));
    } else {
        double ex = exp(x);
        return ex / (1.0 + ex);
    }
}

/*
 * mg_softplus_route(x) -- overflow-safe softplus.
 *
 *   x > 20   -> x  (1 + exp(x) saturates to exp(x); ln(exp(x)) = x)
 *   x < -20  -> exp(x)  (1 + exp(x) ~= 1; ln(1+e) ~= e for tiny e)
 *   else     -> ln(1 + exp(x))
 */
static inline double mg_softplus_route(double x) {
    if (x > 20.0)  return x;
    if (x < -20.0) return exp(x);
    return log(1.0 + exp(x));
}

/*
 * mg_log1p_route(x) -- ln(1 + x), accurate near zero.
 * Delegates to libm log1p which uses series near 0.
 */
static inline double mg_log1p_route(double x) {
    return log1p(x);
}

/*
 * mg_expm1_route(x) -- exp(x) - 1, accurate near zero.
 * Delegates to libm expm1 which uses series near 0.
 */
static inline double mg_expm1_route(double x) {
    return expm1(x);
}

/* ── f32 mirrors (chain-precision selection, Phase 3) ───────── */

static inline float mg_eml_f32(float x, float y) {
    return expf(x) - logf(y);
}
static inline float mg_exp_f32(float x)   { return expf(x); }
static inline float mg_ln_f32(float x)    { return logf(x); }
static inline float mg_log_f32(float x)   { return logf(x); }
static inline float mg_sin_f32(float x)   { return sinf(x); }
static inline float mg_cos_f32(float x)   { return cosf(x); }
static inline float mg_tan_f32(float x)   { return tanf(x); }
static inline float mg_sqrt_f32(float x)  { return sqrtf(x); }
static inline float mg_abs_f32(float x)   { return fabsf(x); }
static inline float mg_pow_f32(float x, float y) { return powf(x, y); }
static inline float mg_div_f32(float x, float y) { return x / y; }

static inline float mg_tanh_f32(float x) {
    float ex = expf(x), enx = expf(-x);
    return (ex - enx) / (ex + enx);
}
static inline float mg_sigmoid_f32(float x) {
    return 1.0f / (1.0f + expf(-x));
}
static inline float mg_softplus_f32(float x) {
    return logf(1.0f + expf(x));
}

static inline float mg_clamp_f32(float x, float lo, float hi) {
    return fminf(fmaxf(x, lo), hi);
}

/* ── Diagnostics (for debugging generated code) ─────────────── */

/*
 * Return a stable identifier for the EML decomposition of an op
 * name (matches keys in data/operators.json). Generated code
 * may include calls to this for runtime tracing under -DMG_TRACE.
 */
const char *mg_op_decomposition(const char *op_name);

/*
 * Return the runtime version string ("MAJOR.MINOR.PATCH").
 * Useful for generated code that needs to detect runtime ABI.
 */
static inline const char *mg_version(void) {
    return LIBMONOGATE_VERSION_STRING;
}

#ifdef __cplusplus
}
#endif

#endif  /* LIBMONOGATE_H */
