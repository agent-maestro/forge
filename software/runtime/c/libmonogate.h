/*
 * libmonogate.h -- C runtime for EML-lang.
 *
 * Status: SCAFFOLD. Real implementations land as backends
 * mature; current functions delegate to libm.
 *
 * The 23 EML operators (per data/operators.json) are exposed as
 * inline functions so the C backend can emit straight calls
 * without ABI overhead.
 *
 * License: MIT (see LICENSE).
 */

#ifndef LIBMONOGATE_H
#define LIBMONOGATE_H

#include <math.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── Versioning ─────────────────────────────────────────────── */
#define LIBMONOGATE_VERSION_MAJOR 0
#define LIBMONOGATE_VERSION_MINOR 0
#define LIBMONOGATE_VERSION_PATCH 1

/* ── The EML primitive ──────────────────────────────────────── */

/*
 * eml(x, y) = exp(x) - ln(y)
 * Domain: y > 0
 *
 * This is the universal EML operator. Every higher-level function
 * in the stdlib decomposes to this primitive (see stdlib/math.eml).
 */
static inline double mg_eml(double x, double y) {
    return exp(x) - log(y);
}

/* ── EML family operators (per data/operators.json) ─────────── */

static inline double mg_eal(double x, double y) {
    /* eal(x, y) = exp(x) + ln(y), y > 0 */
    return exp(x) + log(y);
}

static inline double mg_exl(double x, double y) {
    /* exl(x, y) = exp(x) * ln(y), y > 0 */
    return exp(x) * log(y);
}

static inline double mg_edl(double x, double y) {
    /* edl(x, y) = exp(x) / ln(y), y > 0, y != 1 */
    return exp(x) / log(y);
}

static inline double mg_epl(double x, double y) {
    /* epl(x, y) = exp(x) ^ ln(y) = exp(ln(y) * exp(x)), y > 0 */
    return pow(exp(x), log(y));
}

static inline double mg_lediv(double x, double y) {
    /* lediv(x, y) = ln(exp(x) / y), y > 0 */
    return log(exp(x) / y);
}

static inline double mg_elsb(double x, double y) {
    /* elsb(x, y) = exp(x - ln(y)) = exp(x) / y, y > 0 */
    return exp(x - log(y));
}

static inline double mg_elad(double x, double y) {
    /* elad(x, y) = exp(ln(x) + y) = x * exp(y), x > 0 */
    return exp(log(x) + y);
}

static inline double mg_deml(double x, double y) {
    /* deml(x, y) = exp(-x) - ln(y), y > 0 */
    return exp(-x) - log(y);
}

/* ── Convenience wrappers (one-arg) ─────────────────────────── */

static inline double mg_exp(double x) { return mg_eml(x, 1.0); }    /* exp(x) = EML(x, 1) */
static inline double mg_ln(double x)  { return -mg_eml(0.0, x) + 1.0; } /* ln(x) recovered */

/* Trig via complex Euler -- placeholder; the real path lives
 * in software/backends/c_backend.py which knows how to emit
 * the complex EML decomposition. For now, delegate to libm.
 */
static inline double mg_sin(double x) { return sin(x); }
static inline double mg_cos(double x) { return cos(x); }
static inline double mg_tan(double x) { return tan(x); }

/* Hyperbolic via real exp combinations */
static inline double mg_sinh(double x) { return (exp(x) - exp(-x)) * 0.5; }
static inline double mg_cosh(double x) { return (exp(x) + exp(-x)) * 0.5; }
static inline double mg_tanh(double x) {
    double ex = exp(x), enx = exp(-x);
    return (ex - enx) / (ex + enx);
}

/* Inverse trig / hyp -- delegate to libm for now */
static inline double mg_asin(double x)  { return asin(x); }
static inline double mg_acos(double x)  { return acos(x); }
static inline double mg_atan(double x)  { return atan(x); }
static inline double mg_asinh(double x) { return asinh(x); }
static inline double mg_acosh(double x) { return acosh(x); }
static inline double mg_atanh(double x) { return atanh(x); }

/* Sqrt + abs */
static inline double mg_sqrt(double x) { return sqrt(x); }
static inline double mg_abs(double x)  { return fabs(x); }

/* Pow + clamp -- needed by the C backend's NodeKind dispatch. */
static inline double mg_pow(double x, double y) { return pow(x, y); }
static inline double mg_clamp(double x, double lo, double hi) {
    return fmin(fmax(x, lo), hi);
}

/* ── Diagnostics (for debugging generated code) ─────────────── */

/*
 * Return a stable identifier for the EML decomposition of an op
 * name (matches keys in data/operators.json). Generated code
 * may include calls to this for runtime tracing under -DMG_TRACE.
 */
const char *mg_op_decomposition(const char *op_name);

#ifdef __cplusplus
}
#endif

#endif  /* LIBMONOGATE_H */
