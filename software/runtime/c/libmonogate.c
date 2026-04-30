/*
 * libmonogate.c -- non-inline parts of the C runtime.
 *
 * Most operators are inline in libmonogate.h. This file holds
 * diagnostics + any larger functions that aren't suitable
 * for inlining.
 */

#include "libmonogate.h"
#include <string.h>

/* ── Op decomposition lookup ────────────────────────────────── */
const char *mg_op_decomposition(const char *op_name)
{
    if (!op_name) return "(null)";

    /* 9-family core */
    if (strcmp(op_name, "eml")   == 0) return "exp(x) - ln(y)";
    if (strcmp(op_name, "eal")   == 0) return "exp(x) + ln(y)";
    if (strcmp(op_name, "exl")   == 0) return "exp(x) * ln(y)";
    if (strcmp(op_name, "edl")   == 0) return "exp(x) / ln(y)";
    if (strcmp(op_name, "epl")   == 0) return "exp(x) ^ ln(y)";
    if (strcmp(op_name, "lediv") == 0) return "ln(exp(x) / y)";
    if (strcmp(op_name, "elsb")  == 0) return "exp(x - ln(y)) = exp(x) / y";
    if (strcmp(op_name, "elad")  == 0) return "exp(ln(x) + y) = x * exp(y)";
    if (strcmp(op_name, "deml")  == 0) return "exp(-x) - ln(y)";

    /* Activation / growth */
    if (strcmp(op_name, "sigmoid")  == 0) return "1 / (1 + exp(-x))";
    if (strcmp(op_name, "softplus") == 0) return "ln(1 + exp(x))";
    if (strcmp(op_name, "logistic") == 0) return "K / (1 + exp(-r * (t - x0)))";
    if (strcmp(op_name, "gompertz") == 0) return "K * exp(-exp(-r * (t - x0)))";
    if (strcmp(op_name, "relu")     == 0) return "max(0, x)";

    /* SuperBEST routing forms */
    if (strcmp(op_name, "tanh_route")     == 0) return "Taylor (|x|<1e-8) | sign (|x|>20) | exp form";
    if (strcmp(op_name, "sigmoid_route")  == 0) return "1/(1+exp(-x)) for x>=0, exp(x)/(1+exp(x)) else";
    if (strcmp(op_name, "softplus_route") == 0) return "x (x>20) | exp(x) (x<-20) | ln(1+exp(x))";

    /* Division */
    if (strcmp(op_name, "div")      == 0) return "x / y";
    if (strcmp(op_name, "safe_div") == 0) return "saturating x/y at +/- DBL_MAX when |y| < 1e-300";

    return "(unknown op)";
}
