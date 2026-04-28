/*
 * libmonogate.c -- non-inline parts of the C runtime.
 *
 * Most operators are inline in libmonogate.h. This file holds
 * the diagnostics + any larger functions that aren't suitable
 * for inlining.
 */

#include "libmonogate.h"
#include <string.h>

/* ── Op decomposition lookup (stub) ─────────────────────────── */
const char *mg_op_decomposition(const char *op_name)
{
    if (!op_name) return "(null)";
    if (strcmp(op_name, "eml")  == 0) return "exp(x) - ln(y)";
    if (strcmp(op_name, "eal")  == 0) return "exp(x) + ln(y)";
    if (strcmp(op_name, "exl")  == 0) return "exp(x) * ln(y)";
    if (strcmp(op_name, "edl")  == 0) return "exp(x) / ln(y)";
    if (strcmp(op_name, "epl")  == 0) return "exp(x) ^ ln(y)";
    if (strcmp(op_name, "lediv")== 0) return "ln(exp(x) / y)";
    if (strcmp(op_name, "elsb") == 0) return "exp(x - ln(y)) = exp(x) / y";
    if (strcmp(op_name, "elad") == 0) return "exp(ln(x) + y) = x * exp(y)";
    if (strcmp(op_name, "deml") == 0) return "exp(-x) - ln(y)";
    return "(unknown op)";
}
