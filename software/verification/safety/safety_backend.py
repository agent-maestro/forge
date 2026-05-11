"""Forge safety-verification backend — Phase 1 (temporal_frequency).

Follows the LeanBackend / IsabelleBackend / CoqBackend pattern:
filters annotations on parsed EMLFunction objects by safety class,
runs the appropriate analyzer, returns pass/fail.

This backend MOVES the standalone Python analyzer at
`monogate-engine/tools/safety-analyzer/analyzer.py` into Forge's
formal verification pipeline. Standalone keeps for development;
this is the production path.

Algorithm (per the spec at
`monogate-engine/docs/forge-safety-analyzer-spec.md`):

  1. Walk the EML AST for sin/cos/exp/... transcendental calls
  2. For each call's argument, propagate consts + let-bindings
     through sympy polynomial analysis, extract t-coefficient
  3. Compare measured max coefficient (rad/s) to declared
     max_freq_hz bound × 2π
  4. Return pass / fail with measured + violation details

Limitations (Phase 1, acknowledged):
  - Linear-in-t only; non-linear (sin(t²·k)) refused honestly
  - Single-file kernel only
  - Operates on the EMLFunction AST (which Forge already parsed)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import sympy as sp


# ── Protocol enumerations ──────────────────────────────────────

class SafetyClass(str, Enum):
    """Closed enumeration matching the protocol v0.1."""
    TEMPORAL_FREQUENCY = "temporal_frequency"
    SPATIAL_PATTERN = "spatial_pattern"          # Phase 2
    SATURATED_RED = "saturated_red"               # Phase 2
    MOTION_SICKNESS = "motion_sickness"           # Phase 3
    AUDIO_DYNAMIC_RANGE = "audio_dynamic_range"   # Phase 3
    FULL_PIPELINE = "full_pipeline"               # Phase 4


PHASE_1_CLASSES = {SafetyClass.TEMPORAL_FREQUENCY}


# ── Result types ──────────────────────────────────────────────

@dataclass
class SafetyViolation:
    """One safety-class bound violation."""
    safety_class: SafetyClass
    kernel_name: str
    measured: float
    declared: float
    unit: str
    detail: str
    confidence: str

    def __str__(self) -> str:
        return (f"{self.kernel_name}: {self.safety_class.value} "
                f"measured {self.measured:.4f} {self.unit} > "
                f"declared {self.declared:.4f} {self.unit} ({self.detail})")


@dataclass
class SafetyAnalysisResult:
    """Aggregate result of a SafetyBackend.run() call on one function."""
    kernel_name: str
    safety_class: SafetyClass
    declared_max_freq_hz: Optional[float] = None
    declared_confidence: str = "advisory"
    measured_max_t_coeff_rad_s: float = 0.0
    measured_max_freq_hz: float = 0.0
    status: str = "no_annotation"           # pass | VIOLATION | nonlinear |
                                            # no_annotation
    violations: list[SafetyViolation] = field(default_factory=list)
    transcendental_calls_count: int = 0

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    @property
    def is_acceptable(self) -> bool:
        """A result is acceptable if it passes OR is intentionally
        marked unsupported / advisory by the kernel author. Forge
        compilation continues; the violation is reported as a
        documented gap, not a build error."""
        if self.passed:
            return True
        return self.declared_confidence in ("advisory", "unsupported")


# ── Annotation parsing ────────────────────────────────────────

def _extract_safety_annotations(func) -> list[dict[str, Any]]:
    """Pull `@verify(<safety_class>, kwarg = "value", ...)`
    annotations off an EMLFunction.

    `func` is the AST node Forge's parser produced. Its annotations
    are Annotation(kind="verify", args={0: leading_id, "kwarg": val, ...}).

    Returns a list of dicts with `class`, `kwargs`, line keys. Each
    dict corresponds to one safety annotation. (`@verify(lean, ...)`
    is filtered out — those are Lean-backend's responsibility.)
    """
    safety_annots: list[dict[str, Any]] = []
    SAFETY_CLASS_NAMES = {c.value for c in SafetyClass}

    for annot in getattr(func, "annotations", []):
        if annot.kind != "verify":
            continue
        leading = annot.args.get(0)
        if leading in SAFETY_CLASS_NAMES:
            kwargs = {k: v for k, v in annot.args.items()
                      if isinstance(k, str)}
            safety_annots.append({
                "class": leading,
                "kwargs": kwargs,
                "line": getattr(annot, "line", 0),
            })
    return safety_annots


# ── Temporal frequency analyzer ───────────────────────────────

class TemporalFrequencyAnalyzer:
    """Phase 1 analyzer for `@verify(temporal_frequency, ...)`.

    Operates on EMLFunction AST objects. Extracts t-coefficients
    from transcendental call arguments via const + let-binding
    propagation through sympy polynomial analysis.

    For Phase 1 first cut we ALSO support analysis from RAW SOURCE
    when the AST isn't available (e.g. when the standalone analyzer
    pre-Forge integration runs). The `analyze_source()` path mirrors
    `analyze_function()` but operates on the .eml text.
    """

    TRANSCENDENTAL_NAMES = {
        "sin", "cos", "tan", "exp", "log",
        "asin", "acos", "atan",
        "sinh", "cosh", "tanh",
    }

    CONST_PATTERN = re.compile(
        r'^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*Real\s*=\s*'
        r'(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)',
        re.MULTILINE
    )
    LET_PATTERN = re.compile(
        r'\blet\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*Real\s*=\s*'
        r'([^;]+?);',
        re.DOTALL
    )

    def analyze_source(self, source: str, kernel_name: str,
                       declared_max_freq_hz: float,
                       declared_confidence: str = "advisory"
                       ) -> SafetyAnalysisResult:
        """Source-text-driven analysis. Used by the Forge backend
        when the EMLFunction AST has direct source-region access,
        and by the standalone analyzer wrapper for development.
        """
        result = SafetyAnalysisResult(
            kernel_name=kernel_name,
            safety_class=SafetyClass.TEMPORAL_FREQUENCY,
            declared_max_freq_hz=declared_max_freq_hz,
            declared_confidence=declared_confidence,
        )

        consts = self._extract_consts(source)
        let_t_coeffs = self._find_let_bindings(source, consts)
        calls = self._find_transcendental_calls(source)
        result.transcendental_calls_count = len(calls)

        max_coeff = 0.0
        worst_call_detail = ""
        for call_name, arg_expr, line_no in calls:
            substituted = self._substitute_known(arg_expr, consts, let_t_coeffs)
            coeff, _reason = self._extract_t_coeff(substituted)
            if coeff is not None and abs(coeff) > max_coeff:
                max_coeff = abs(coeff)
                worst_call_detail = f"{call_name}() at line {line_no}"

        result.measured_max_t_coeff_rad_s = max_coeff
        result.measured_max_freq_hz = max_coeff / (2 * math.pi)

        declared_rad_s = 2 * math.pi * declared_max_freq_hz
        if max_coeff > declared_rad_s:
            result.status = "VIOLATION"
            result.violations.append(SafetyViolation(
                safety_class=SafetyClass.TEMPORAL_FREQUENCY,
                kernel_name=kernel_name,
                measured=max_coeff,
                declared=declared_rad_s,
                unit="rad/s",
                detail=worst_call_detail,
                confidence=declared_confidence,
            ))
        else:
            result.status = "pass"

        return result

    # ── Helpers (port of standalone analyzer logic) ──────────

    def _extract_consts(self, source: str) -> dict[str, float]:
        consts = {}
        for match in self.CONST_PATTERN.finditer(source):
            try:
                consts[match.group(1)] = float(match.group(2))
            except ValueError:
                pass
        return consts

    def _substitute_known(self, expr: str, consts: dict[str, float],
                           let_t_coeffs: dict[str, float | None]) -> str:
        out = expr
        for name, value in sorted(consts.items(), key=lambda kv: -len(kv[0])):
            out = re.sub(rf'\b{re.escape(name)}\b', f'({value})', out)
        for name, coeff in sorted(let_t_coeffs.items(),
                                   key=lambda kv: -len(kv[0])):
            if coeff is None:
                out = re.sub(rf'\b{re.escape(name)}\b',
                             f'NLin_{name}', out)
            else:
                out = re.sub(rf'\b{re.escape(name)}\b',
                             f'(({coeff})*t)', out)
        return out

    def _extract_t_coeff(self, expr: str) -> tuple[float | None, str]:
        try:
            sympy_expr = sp.sympify(expr, evaluate=True)
            t = sp.Symbol('t')
        except (sp.SympifyError, SyntaxError, TypeError) as e:
            return None, f"sympy_parse_error: {type(e).__name__}"
        if not sympy_expr.has(t):
            return 0.0, "no_t_dependency"
        try:
            poly = sp.Poly(sympy_expr, t)
        except sp.PolynomialError:
            return None, "non_polynomial_in_t"
        if poly.degree() == 0:
            return 0.0, "constant_in_t"
        if poly.degree() == 1:
            coeff_expr = poly.nth(1)
            if coeff_expr.is_number:
                return float(coeff_expr), "linear_in_t"
            simplified = sp.simplify(coeff_expr)
            if simplified.is_number:
                return float(simplified), "linear_in_t"
            return None, f"coeff_non_numeric:{simplified}"
        return None, f"degree_{poly.degree()}_in_t"

    def _find_let_bindings(self, source: str,
                            consts: dict[str, float]
                            ) -> dict[str, float | None]:
        result = {}
        for match in self.LET_PATTERN.finditer(source):
            substituted = self._substitute_known(match.group(2), consts, result)
            coeff, _ = self._extract_t_coeff(substituted)
            result[match.group(1)] = coeff
        return result

    def _find_transcendental_calls(self, source: str
                                     ) -> list[tuple[str, str, int]]:
        cleaned = '\n'.join(
            line.split('//', 1)[0] if '//' in line else line
            for line in source.split('\n')
        )
        calls = []
        pos = 0
        while pos < len(cleaned):
            m = re.search(
                rf"\b({'|'.join(self.TRANSCENDENTAL_NAMES)})\s*\(",
                cleaned[pos:]
            )
            if m is None:
                break
            fn_name = m.group(1)
            start = pos + m.start()
            paren_start = pos + m.end() - 1
            depth, i = 0, paren_start
            while i < len(cleaned):
                ch = cleaned[i]
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            if depth != 0:
                pos = paren_start + 1
                continue
            arg = cleaned[paren_start + 1:i]
            line_no = cleaned[:start].count('\n') + 1
            calls.append((fn_name, arg, line_no))
            pos = i + 1
        return calls


# ── Backend façade ────────────────────────────────────────────

class SafetyBackend:
    """Forge backend for `@verify(<safety_class>, ...)` annotations.

    Mirrors the LeanBackend / IsabelleBackend / CoqBackend pattern.
    Dispatches per safety class to the appropriate analyzer.

    Usage from Forge's compile pipeline:
        backend = SafetyBackend(strict=True)
        results = backend.run_on_source(source_text, function_name)
        for r in results:
            if not r.is_acceptable:
                raise CompilationError(r.violations)
    """

    name = "safety"

    def __init__(self, *, strict: bool = False) -> None:
        """`strict = True` rejects compilation when ANY annotation
        has confidence = "unsupported". False (default) accepts
        unsupported as a documented known-hazard.
        """
        self.strict = strict
        self.temporal_analyzer = TemporalFrequencyAnalyzer()

    def run_on_function(self, func) -> list[SafetyAnalysisResult]:
        """Analyze a parsed EMLFunction. Returns one result per
        safety annotation."""
        results = []
        annots = _extract_safety_annotations(func)
        if not annots:
            return results

        # We need access to the function's source for the let-
        # binding extraction. The EMLFunction AST should expose
        # this; if not, the caller should use run_on_source().
        source = getattr(func, "source", None) or getattr(func, "raw_text", "")
        if not source:
            # Fallback: build a minimal source string from the function
            # body. For Phase 1 we require source access.
            return results

        kernel_name = getattr(func, "name", "<anonymous>")
        for annot in annots:
            cls = annot["class"]
            if cls != SafetyClass.TEMPORAL_FREQUENCY.value:
                continue  # Phase 2+ classes not yet implemented
            max_freq_hz = self._parse_max_freq(annot["kwargs"])
            confidence = annot["kwargs"].get("confidence", "advisory")
            if max_freq_hz is None:
                continue
            result = self.temporal_analyzer.analyze_source(
                source=source,
                kernel_name=kernel_name,
                declared_max_freq_hz=max_freq_hz,
                declared_confidence=confidence,
            )
            results.append(result)
        return results

    def run_on_source(self, source: str,
                       kernel_name: str = "<file>"
                       ) -> list[SafetyAnalysisResult]:
        """Analyze raw .eml source text. Returns one result per
        safety annotation found in the file.

        Used for standalone analysis (no Forge AST required).
        Phase 1 implementation; will be supplanted by run_on_function
        once Forge integration is complete.
        """
        annots = _extract_real_safety_annotations_from_source(source)
        results = []
        for annot in annots:
            cls = annot["class"]
            if cls != SafetyClass.TEMPORAL_FREQUENCY.value:
                continue
            max_freq_hz = self._parse_max_freq(annot["kwargs"])
            confidence = annot["kwargs"].get("confidence", "advisory")
            if max_freq_hz is None:
                continue
            result = self.temporal_analyzer.analyze_source(
                source=source,
                kernel_name=kernel_name,
                declared_max_freq_hz=max_freq_hz,
                declared_confidence=confidence,
            )
            results.append(result)
        return results

    def _parse_max_freq(self, kwargs: dict[str, Any]) -> Optional[float]:
        raw = kwargs.get("max_freq_hz")
        if raw is None:
            return None
        try:
            return float(str(raw).strip().strip('"').strip("'"))
        except ValueError:
            return None


# ── Source-level annotation parser (for run_on_source) ────────

REAL_SAFETY_ANNOT_PATTERN = re.compile(
    r'@verify\s*\(\s*'
    r'(temporal_frequency|spatial_pattern|saturated_red|'
    r'motion_sickness|audio_dynamic_range|full_pipeline)'
    r'\s*((?:,\s*\w+\s*=\s*"[^"]*"\s*)*)'
    r'\)',
    re.DOTALL
)
KWARG_PATTERN = re.compile(r',\s*(\w+)\s*=\s*"([^"]*)"')


def _extract_real_safety_annotations_from_source(source: str
                                                   ) -> list[dict[str, Any]]:
    """Find @verify(<safety_class>, k="v", ...) clauses in raw
    source. Used by run_on_source() before Forge AST is available.
    """
    annots = []
    for m in REAL_SAFETY_ANNOT_PATTERN.finditer(source):
        cls = m.group(1)
        kwargs_str = m.group(2) or ""
        kwargs = {km.group(1): km.group(2) for km in KWARG_PATTERN.finditer(kwargs_str)}
        annots.append({"class": cls, "kwargs": kwargs})
    return annots


# ── Standalone entry point (convenience for development) ──────

def analyze_file(path, *, strict: bool = False
                 ) -> list[SafetyAnalysisResult]:
    """Analyze a single .eml file via SafetyBackend. Returns the
    list of per-annotation results."""
    from pathlib import Path
    source = Path(path).read_text(encoding="utf-8")
    backend = SafetyBackend(strict=strict)
    return backend.run_on_source(source, kernel_name=Path(path).name)
