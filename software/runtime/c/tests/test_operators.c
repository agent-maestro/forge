/*
 * test_operators.c -- C runtime smoke tests.
 *
 * Run via:
 *   gcc -O2 -Wall -lm test_operators.c ../libmonogate.c -o test && ./test
 *
 * Covers all 9 EML family operators, math wrappers, division
 * (safe + unsafe), activations, growth dynamics, and SuperBEST
 * routing edge cases.
 */

#include "../libmonogate.h"
#include <stdio.h>
#include <math.h>
#include <float.h>
#include <string.h>
#include <assert.h>

static int approx_eq(double a, double b, double tol) {
    return fabs(a - b) <= tol;
}

static void check(int cond, const char *label) {
    if (!cond) {
        fprintf(stderr, "FAIL: %s\n", label);
        exit(1);
    }
    printf("  ok  %s\n", label);
}

int main(void) {
    printf("libmonogate %s\n", mg_version());

    /* ── Core EML family ─────────────────────────────────────── */

    /* eml(0, 1) = exp(0) - ln(1) = 1 */
    check(approx_eq(mg_eml(0.0, 1.0), 1.0, 1e-15), "mg_eml(0,1) == 1");

    /* eal(0, 1) = exp(0) + ln(1) = 1 */
    check(approx_eq(mg_eal(0.0, 1.0), 1.0, 1e-15), "mg_eal(0,1) == 1");

    /* exl(0, 2) = exp(0) * ln(2) = ln(2) */
    check(approx_eq(mg_exl(0.0, 2.0), log(2.0), 1e-15), "mg_exl(0,2) == ln(2)");

    /* edl(0, 2) = exp(0) / ln(2) = 1/ln(2) */
    check(approx_eq(mg_edl(0.0, 2.0), 1.0 / log(2.0), 1e-15), "mg_edl(0,2) == 1/ln(2)");

    /* lediv(0, 2) = ln(exp(0) / 2) = ln(0.5) */
    check(approx_eq(mg_lediv(0.0, 2.0), log(0.5), 1e-15), "mg_lediv(0,2) == ln(0.5)");

    /* elsb(1, 1) = exp(1 - 0) = e */
    check(approx_eq(mg_elsb(1.0, 1.0), M_E, 1e-15), "mg_elsb(1,1) == e");

    /* elad(2, 1) = exp(ln(2) + 1) = 2e */
    check(approx_eq(mg_elad(2.0, 1.0), 2.0 * M_E, 1e-13), "mg_elad(2,1) == 2e");

    /* deml(0, 1) = exp(0) - ln(1) = 1 */
    check(approx_eq(mg_deml(0.0, 1.0), 1.0, 1e-15), "mg_deml(0,1) == 1");

    /* ── Standard math wrappers ──────────────────────────────── */

    check(approx_eq(mg_exp(1.0), exp(1.0), 1e-15), "mg_exp(1) matches libm");
    check(approx_eq(mg_ln(M_E), 1.0, 1e-15), "mg_ln(e) == 1");
    check(approx_eq(mg_log(M_E), 1.0, 1e-15), "mg_log(e) == 1 (alias)");
    check(approx_eq(mg_sin(M_PI / 2.0), 1.0, 1e-15), "mg_sin(pi/2) == 1");
    check(approx_eq(mg_cos(0.0), 1.0, 1e-15), "mg_cos(0) == 1");

    /* Hyperbolic */
    check(approx_eq(mg_sinh(1.0), sinh(1.0), 1e-15), "mg_sinh matches libm");
    check(approx_eq(mg_cosh(2.0), cosh(2.0), 1e-15), "mg_cosh matches libm");
    check(approx_eq(mg_tanh(1.0), tanh(1.0), 1e-12), "mg_tanh matches libm");

    /* Sqrt + abs */
    check(approx_eq(mg_sqrt(4.0), 2.0, 1e-15), "mg_sqrt(4) == 2");
    check(approx_eq(mg_abs(-3.5), 3.5, 1e-15), "mg_abs(-3.5) == 3.5");

    /* Pow + clamp */
    check(approx_eq(mg_pow(2.0, 10.0), 1024.0, 1e-12), "mg_pow(2,10) == 1024");
    check(approx_eq(mg_clamp(5.0, 0.0, 1.0), 1.0, 1e-15), "mg_clamp(5,0,1) == 1");
    check(approx_eq(mg_clamp(-5.0, 0.0, 1.0), 0.0, 1e-15), "mg_clamp(-5,0,1) == 0");

    /* ── Division ────────────────────────────────────────────── */

    check(approx_eq(mg_div(6.0, 2.0), 3.0, 1e-15), "mg_div(6,2) == 3");
    {
        double v = mg_safe_div(1.0, 0.0);
        check(v >= DBL_MAX / 2.0, "mg_safe_div(1,0) saturates positive");
    }
    {
        double v = mg_safe_div(-1.0, 0.0);
        check(v <= -DBL_MAX / 2.0, "mg_safe_div(-1,0) saturates negative");
    }
    check(approx_eq(mg_safe_div(8.0, 4.0), 2.0, 1e-15), "mg_safe_div(8,4) == 2");

    /* ── Activations ────────────────────────────────────────── */

    check(approx_eq(mg_sigmoid(0.0), 0.5, 1e-15), "mg_sigmoid(0) == 0.5");
    check(approx_eq(mg_softplus(0.0), log(2.0), 1e-15), "mg_softplus(0) == ln(2)");
    check(approx_eq(mg_relu(-1.0), 0.0, 1e-15), "mg_relu(-1) == 0");
    check(approx_eq(mg_relu(2.5), 2.5, 1e-15), "mg_relu(2.5) == 2.5");

    /* ── Growth dynamics ────────────────────────────────────── */

    /* logistic at midpoint -> K/2 */
    check(approx_eq(mg_logistic(5.0, 100.0, 1.0, 5.0), 50.0, 1e-12),
          "mg_logistic at midpoint == K/2");

    /* gompertz at midpoint -> K/e */
    check(approx_eq(mg_gompertz(5.0, 100.0, 1.0, 5.0), 100.0 * exp(-1.0), 1e-12),
          "mg_gompertz at midpoint == K/e");

    /* ── SuperBEST routing ──────────────────────────────────── */

    /* tanh saturates at large |x| */
    check(approx_eq(mg_tanh_route(100.0), 1.0, 1e-15), "mg_tanh_route(+inf) == 1");
    check(approx_eq(mg_tanh_route(-100.0), -1.0, 1e-15), "mg_tanh_route(-inf) == -1");

    /* tanh near zero -> identity */
    {
        double x = 1e-12;
        check(approx_eq(mg_tanh_route(x), x, 1e-20), "mg_tanh_route near 0 = x");
    }

    /* sigmoid_route overflow-safe on negative tail */
    {
        double v = mg_sigmoid_route(-1000.0);
        check(isfinite(v) && v >= 0.0 && v <= 1e-300, "mg_sigmoid_route(-1000) is finite & ~0");
    }

    /* sigmoid_route at zero == 0.5 */
    check(approx_eq(mg_sigmoid_route(0.0), 0.5, 1e-15), "mg_sigmoid_route(0) == 0.5");

    /* softplus_route saturates large +x to identity */
    check(approx_eq(mg_softplus_route(50.0), 50.0, 1e-12), "mg_softplus_route(50) == 50");

    /* softplus_route on large -x stays finite & positive */
    {
        double v = mg_softplus_route(-50.0);
        check(isfinite(v) && v > 0.0, "mg_softplus_route(-50) finite & positive");
    }

    /* log1p / expm1 routing forwards to libm */
    check(approx_eq(mg_log1p_route(0.0), 0.0, 1e-15), "mg_log1p_route(0) == 0");
    check(approx_eq(mg_expm1_route(0.0), 0.0, 1e-15), "mg_expm1_route(0) == 0");

    /* ── f32 mirrors (smoke test) ───────────────────────────── */

    {
        float v = mg_sigmoid_f32(0.0f);
        check(fabsf(v - 0.5f) < 1e-7f, "mg_sigmoid_f32(0) == 0.5");
    }
    {
        float v = mg_tanh_f32(1.0f);
        check(fabsf(v - tanhf(1.0f)) < 1e-6f, "mg_tanh_f32 matches libm");
    }
    {
        float v = mg_eml_f32(0.0f, 1.0f);
        check(fabsf(v - 1.0f) < 1e-7f, "mg_eml_f32(0,1) == 1");
    }

    /* ── Diagnostics ────────────────────────────────────────── */

    check(strcmp(mg_op_decomposition("eml"), "exp(x) - ln(y)") == 0,
          "decomp[eml] reads correctly");
    check(strcmp(mg_op_decomposition("sigmoid"), "1 / (1 + exp(-x))") == 0,
          "decomp[sigmoid] reads correctly");
    check(strcmp(mg_op_decomposition("safe_div"),
                 "saturating x/y at +/- DBL_MAX when |y| < 1e-300") == 0,
          "decomp[safe_div] reads correctly");
    check(strcmp(mg_op_decomposition("nonexistent"), "(unknown op)") == 0,
          "decomp[unknown] returns sentinel");
    check(strcmp(mg_op_decomposition(NULL), "(null)") == 0,
          "decomp[NULL] returns null sentinel");

    /* ── Version sanity ─────────────────────────────────────── */
    check(LIBMONOGATE_VERSION_MAJOR == 0 && LIBMONOGATE_VERSION_MINOR == 1,
          "version macros are 0.1.x");

    printf("\nALL OK (%s)\n", mg_version());
    return 0;
}
