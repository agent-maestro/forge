/*
 * test_operators.c -- smoke tests for the C runtime.
 * Run via: gcc test_operators.c ../libmonogate.c -lm -o test && ./test
 */

#include "../libmonogate.h"
#include <stdio.h>
#include <math.h>
#include <assert.h>

static int approx_eq(double a, double b, double tol) {
    return fabs(a - b) <= tol;
}

int main(void) {
    /* eml(0, 1) = exp(0) - ln(1) = 1 - 0 = 1 */
    assert(approx_eq(mg_eml(0.0, 1.0), 1.0, 1e-15));

    /* exp(x) = EML(x, 1) */
    assert(approx_eq(mg_exp(1.0), exp(1.0), 1e-15));

    /* sinh(x) = (exp(x) - exp(-x)) / 2 */
    assert(approx_eq(mg_sinh(1.0), sinh(1.0), 1e-15));

    /* cosh(x) = (exp(x) + exp(-x)) / 2 */
    assert(approx_eq(mg_cosh(2.0), cosh(2.0), 1e-15));

    printf("OK\n");
    return 0;
}
