"""Chemistry vertical integration tests.

Exercises every `.eml` file under `industries/chemistry/`:

  - parser produces a clean module
  - profiler labels every function with status `ok`
  - every primitive compiles to C and Rust
  - every primitive that carries `@verify(lean, ...)` compiles to Lean
  - the GMP / FDA PV / ICH Q8/Q9/Q10 / REACH certification docs are in place

The headline regulator-facing claim across this vertical is "one
.eml source compiles to multiple targets bit-exactly"; the
cross-target equivalence harness in `tools/equivalence/` is the
natural place to push numerical agreement; this file gates only
the structural pieces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.profiler import Profiler
from software.backends.c_backend import CBackend
from software.backends.rust_backend import RustBackend
from software.verification.lean.LeanBackend import LeanBackend


REPO_ROOT = Path(__file__).resolve().parents[2]
CHEM_DIR = REPO_ROOT / "industries" / "chemistry"


# Every .eml file the vertical ships, with the headline @verify(lean)
# theorem the file's primary function carries (or None when no
# headline @verify is present).
_CHEMISTRY_FILES: list[tuple[str, str | None]] = [
    # kinetics
    ("kinetics/arrhenius.eml",          "arrhenius_monotone_in_temperature"),
    ("kinetics/eyring.eml",             "eyring_rate_positive"),
    ("kinetics/michaelis_menten.eml",   "michaelis_menten_saturating"),
    ("kinetics/hill.eml",               "hill_monotone_in_substrate"),
    ("kinetics/first_order.eml",        "first_order_decay_monotone"),
    ("kinetics/second_order.eml",       "second_order_decay_monotone"),
    # thermodynamics
    ("thermodynamics/boltzmann.eml",          "boltzmann_ratio_positive"),
    ("thermodynamics/gibbs.eml",              "gibbs_linear_in_temperature"),
    ("thermodynamics/vant_hoff.eml",          "vant_hoff_predict_k"),
    ("thermodynamics/clausius_clapeyron.eml", "clausius_clapeyron_predict_p"),
    # electrochemistry
    ("electrochemistry/nernst.eml",        "nernst_monotone_in_q"),
    ("electrochemistry/butler_volmer.eml", "butler_volmer_zero_at_zero_overpotential"),
    ("electrochemistry/tafel.eml",         "tafel_monotone_in_current"),
    ("electrochemistry/cottrell.eml",      "cottrell_decays_with_time"),
    # spectroscopy
    ("spectroscopy/beer_lambert.eml",   "beer_lambert_linear_in_concentration"),
    ("spectroscopy/lorentzian.eml",     "lorentzian_peak_at_centre"),
    ("spectroscopy/gaussian_peak.eml",  "gaussian_peak_at_centre"),
    ("spectroscopy/voigt.eml",          "voigt_peak_at_centre"),
    # pharma
    ("pharma/one_compartment.eml",  "iv_bolus_decay_monotone"),
    ("pharma/two_compartment.eml",  "two_compartment_alpha_dominates_early"),
    ("pharma/dose_response.eml",    "dose_response_saturating"),
    ("pharma/drug_clearance.eml",   "clearance_proportional_to_dose"),
    ("pharma/pk_absorption.eml",    "po_absorption_rises_then_decays"),
    # diffusion
    ("diffusion/fick_first_law.eml",  "fick_flux_opposes_gradient"),
    ("diffusion/fick_second_law.eml", "diffusion_kernel_normalised"),
    # surface
    ("surface/langmuir.eml",   "langmuir_saturating"),
    ("surface/freundlich.eml", "freundlich_monotone_in_concentration"),
    ("surface/bet.eml",        "bet_diverges_at_p0"),
    # polymer
    ("polymer/flory_huggins.eml", "flory_huggins_symmetric_under_phi_swap"),
    ("polymer/mark_houwink.eml",  "mark_houwink_monotone_in_m"),
    # process control
    ("process_control/reactor_temperature.eml", "reaction_heat_monotone_in_temperature"),
    ("process_control/ph_control.eml",          "ph_decreases_with_proton_concentration"),
    ("process_control/distillation.eml",        "antoine_increases_with_temperature"),
    ("process_control/crystallization.eml",     "growth_rate_nonneg_above_solubility"),
]


# ── 1. Source files exist ───────────────────────────────────────────


@pytest.mark.parametrize(
    "rel_path,_thm",
    _CHEMISTRY_FILES,
    ids=[f[0] for f in _CHEMISTRY_FILES],
)
def test_chemistry_eml_file_exists(rel_path: str, _thm: str | None) -> None:
    p = CHEM_DIR / rel_path
    assert p.exists(), f"missing chemistry vertical file: {p}"


# ── 2. Parse + profile ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "rel_path,_thm",
    _CHEMISTRY_FILES,
    ids=[f[0] for f in _CHEMISTRY_FILES],
)
def test_chemistry_eml_parses_and_profiles(
    rel_path: str, _thm: str | None,
) -> None:
    mod = parse_file(str(CHEM_DIR / rel_path))
    Profiler().profile_module(mod)
    assert mod.functions, f"{rel_path}: no functions parsed"
    failures: list[str] = []
    for fn in mod.functions:
        prof = fn.profile or {}
        status = prof.get("status", "missing")
        if status not in ("ok", "tuple"):
            failures.append(f"{fn.name}: status={status}")
    assert not failures, "\n".join(failures)


# ── 3. Headline @verify(lean) annotation in place ───────────────────


@pytest.mark.parametrize(
    "rel_path,thm",
    [(p, t) for p, t in _CHEMISTRY_FILES if t is not None],
    ids=[f[0] for f in _CHEMISTRY_FILES if f[1] is not None],
)
def test_chemistry_verify_annotation_present(
    rel_path: str, thm: str,
) -> None:
    mod = parse_file(str(CHEM_DIR / rel_path))
    found = False
    for fn in mod.functions:
        for ann in fn.annotations:
            if ann.kind == "verify" and ann.args.get("theorem") == thm:
                found = True
                break
        if found:
            break
    assert found, (
        f"{rel_path}: expected @verify(lean, theorem = {thm!r}) "
        f"on some function, but no annotation matched"
    )


# ── 4. C + Rust + Lean compile cleanly for every file ───────────────


@pytest.mark.parametrize(
    "rel_path,_thm",
    _CHEMISTRY_FILES,
    ids=[f[0] for f in _CHEMISTRY_FILES],
)
def test_chemistry_compiles_to_c(rel_path: str, _thm: str | None) -> None:
    mod = parse_file(str(CHEM_DIR / rel_path))
    Profiler().profile_module(mod)
    src = CBackend().compile(mod)
    assert "Generated by EML-lang C backend" in src
    for fn in mod.functions:
        assert fn.name in src, f"{rel_path}: C source missing {fn.name}"


@pytest.mark.parametrize(
    "rel_path,_thm",
    _CHEMISTRY_FILES,
    ids=[f[0] for f in _CHEMISTRY_FILES],
)
def test_chemistry_compiles_to_rust(rel_path: str, _thm: str | None) -> None:
    mod = parse_file(str(CHEM_DIR / rel_path))
    Profiler().profile_module(mod)
    src = RustBackend().compile(mod)
    for fn in mod.functions:
        assert fn.name in src, f"{rel_path}: Rust source missing {fn.name}"


@pytest.mark.parametrize(
    "rel_path,thm",
    [(p, t) for p, t in _CHEMISTRY_FILES if t is not None],
    ids=[f[0] for f in _CHEMISTRY_FILES if f[1] is not None],
)
def test_chemistry_compiles_to_lean(rel_path: str, thm: str) -> None:
    mod = parse_file(str(CHEM_DIR / rel_path))
    Profiler().profile_module(mod)
    src = LeanBackend().compile_module(mod)
    assert f"theorem {thm}" in src, (
        f"{rel_path}: Lean output missing theorem {thm!r}"
    )


# ── 5. Spot-check chain orders match the documented expectation ─────


def test_arrhenius_chain_order_is_one():
    """Arrhenius rate constant: single exp -> chain 1."""
    mod = parse_file(str(CHEM_DIR / "kinetics/arrhenius.eml"))
    Profiler().profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "rate_constant")
    chain = fn.profile["chain_order"]
    assert chain == 1, f"arrhenius.rate_constant chain={chain}, expected 1"


def test_michaelis_menten_chain_order_is_zero():
    """Michaelis-Menten is rational -> chain 0."""
    mod = parse_file(str(CHEM_DIR / "kinetics/michaelis_menten.eml"))
    Profiler().profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "velocity")
    chain = fn.profile["chain_order"]
    assert chain == 0, f"michaelis_menten.velocity chain={chain}, expected 0"


def test_butler_volmer_chain_order_is_two():
    """Butler-Volmer has two distinct exponentials -> chain 2."""
    mod = parse_file(str(CHEM_DIR / "electrochemistry/butler_volmer.eml"))
    Profiler().profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "current_density")
    chain = fn.profile["chain_order"]
    assert chain == 2, f"butler_volmer.current_density chain={chain}, expected 2"


def test_langmuir_chain_order_is_zero():
    """Langmuir isotherm is rational -> chain 0."""
    mod = parse_file(str(CHEM_DIR / "surface/langmuir.eml"))
    Profiler().profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "coverage")
    chain = fn.profile["chain_order"]
    assert chain == 0, f"langmuir.coverage chain={chain}, expected 0"


def test_two_compartment_chain_order_is_two():
    """Two-compartment PK has bi-exponential decay -> chain 2."""
    mod = parse_file(str(CHEM_DIR / "pharma/two_compartment.eml"))
    Profiler().profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "plasma_concentration")
    chain = fn.profile["chain_order"]
    assert chain == 2, f"two_compartment chain={chain}, expected 2"


# ── 6. Certification docs in place ──────────────────────────────────


def test_gmp_compliance_doc_exists():
    p = CHEM_DIR / "certification" / "GMP_COMPLIANCE.md"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "21 CFR" in text
    # Theorem index lists every headline @verify theorem.
    for _path, thm in _CHEMISTRY_FILES:
        if thm is None:
            continue
        assert thm in text, f"GMP_COMPLIANCE.md missing theorem {thm}"


def test_fda_process_validation_doc_exists():
    p = CHEM_DIR / "certification" / "FDA_PROCESS_VALIDATION.md"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "Stage 1" in text and "Stage 2" in text and "Stage 3" in text


def test_ich_q8_q9_q10_doc_exists():
    p = CHEM_DIR / "certification" / "ICH_Q8_Q9_Q10.md"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "ICH Q8" in text and "ICH Q9" in text and "ICH Q10" in text


def test_reach_compliance_doc_exists():
    p = CHEM_DIR / "certification" / "REACH_COMPLIANCE.md"
    assert p.exists(), f"missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "REACH" in text
