"""Tests for Phase 4 backends — Java, Kotlin, Go, AUTOSAR, AADL."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.aadl_backend import AadlBackend
from software.backends.aadl_backend import CompileError as AadlErr
from software.backends.autosar_backend import AutosarBackend, AutosarArtifact
from software.backends.autosar_backend import CompileError as AutoErr
from software.backends.go_backend import GoBackend
from software.backends.java_backend import JavaBackend
from software.backends.kotlin_backend import KotlinBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
AUTOPILOT = REPO_ROOT / "industries" / "aerospace" / "flight_control" / "autopilot.eml"


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Java backend ───────────────────────────────────────────────


class TestJavaBackend:
    def test_class_name_is_camel_cased(self):
        mod = _profile(AUTOPILOT)
        out = JavaBackend().compile(mod)
        assert "public final class Autopilot {" in out
        assert "private Autopilot() {}" in out  # utility class pattern

    def test_constants_are_static_final(self):
        mod = _profile(AUTOPILOT)
        out = JavaBackend().compile(mod)
        assert "public static final double Kp = 2.5;" in out
        assert "public static final double ELEVATOR_MAX = 0.349;" in out

    def test_function_uses_math_package(self):
        mod = _profile(AUTOPILOT)
        out = JavaBackend().compile(mod)
        assert "Math.cos(pitch)" in out
        # Math.max / Math.min from clamp lowering.
        assert "Math.max(ELEVATOR_MIN, Math.min(ELEVATOR_MAX," in out

    def test_javadoc_emits_pre_post_and_verify(self):
        mod = _profile(AUTOPILOT)
        out = JavaBackend().compile(mod)
        # Phase F migrated the input requires clauses to parameter
        # refinements; these now lower to runtime guards in the body
        # rather than @forge.requires javadoc lines.
        assert "@forge.ensures" in out
        assert "@forge.verify lean theorem=autopilot_command_within_limits" in out

    def test_let_emits_final_double(self):
        mod = _profile(AUTOPILOT)
        out = JavaBackend().compile(mod)
        assert "final double pitch_error =" in out
        assert "final double rate_target =" in out


# ── Kotlin backend ─────────────────────────────────────────────


class TestKotlinBackend:
    def test_package_and_import(self):
        mod = _profile(AUTOPILOT)
        out = KotlinBackend().compile(mod)
        assert "package forge.autopilot" in out
        assert "import kotlin.math.*" in out

    def test_pure_expression_body_form(self):
        # gravity_compensation has a single pure expression body.
        mod = _profile(AUTOPILOT)
        out = KotlinBackend().compile(mod)
        assert "fun gravity_compensation(pitch: Double): Double = " in out

    def test_block_form_with_require_for_contracts(self):
        # autopilot_step has requires → block-form with require()
        mod = _profile(AUTOPILOT)
        out = KotlinBackend().compile(mod)
        assert "fun autopilot_step(" in out
        assert "require((abs(pitch_setpoint) < 1.5708))" in out
        assert "coerceIn(ELEVATOR_MIN, ELEVATOR_MAX)" in out

    def test_constants_use_val(self):
        mod = _profile(AUTOPILOT)
        out = KotlinBackend().compile(mod)
        assert "val Kp: Double = 2.5" in out
        assert "val ELEVATOR_MAX: Double = 0.349" in out

    def test_kdoc_has_no_template_debris(self):
        # Regression: an early version had `chain_order=$co=2` debris.
        mod = _profile(AUTOPILOT)
        out = KotlinBackend().compile(mod)
        assert "$co=" not in out

    def test_pow_uses_kotlin_math(self):
        mod = _profile_source(
            "fn p(x: Real, y: Real) -> Real { pow(x, y) }\n"
        )
        out = KotlinBackend().compile(mod)
        assert ".pow(" in out


# ── Go backend ─────────────────────────────────────────────────


class TestGoBackend:
    def test_package_name_lowercase(self):
        mod = _profile(AUTOPILOT)
        out = GoBackend().compile(mod)
        assert "package autopilot" in out

    def test_math_import(self):
        mod = _profile(AUTOPILOT)
        out = GoBackend().compile(mod)
        assert 'import (' in out
        assert '"math"' in out

    def test_capitalised_math_names(self):
        # Go capitalises exports: math.Cos, math.Exp, math.Abs.
        mod = _profile(AUTOPILOT)
        out = GoBackend().compile(mod)
        assert "math.Cos(pitch)" in out
        assert "math.Abs" in out
        assert "math.Max" in out
        assert "math.Min" in out

    def test_let_uses_short_var_decl(self):
        mod = _profile(AUTOPILOT)
        out = GoBackend().compile(mod)
        assert "pitch_error := " in out
        assert "rate_target := " in out

    def test_requires_emits_panic_guard(self):
        mod = _profile(AUTOPILOT)
        out = GoBackend().compile(mod)
        # Phase F migrated input requires clauses to parameter
        # refinements; the panic message tag flipped to
        # "refinement violated".
        assert 'panic("autopilot_step: refinement violated' in out

    def test_function_doc_comment(self):
        mod = _profile(AUTOPILOT)
        out = GoBackend().compile(mod)
        assert "// autopilot_step -- compiled from EML-lang." in out
        assert "// @verify lean theorem=" in out


# ── AUTOSAR backend ────────────────────────────────────────────


class TestAutosarBackend:
    def test_empty_module_raises(self):
        mod = _profile_source("// nothing here\n")
        with pytest.raises(AutoErr):
            AutosarBackend().compile_full(mod)

    def test_swc_name_camel_cased(self):
        mod = _profile(AUTOPILOT)
        art = AutosarBackend().compile_full(mod)
        assert art.swc_name == "Autopilot"

    def test_arxml_has_correct_namespace(self):
        mod = _profile(AUTOPILOT)
        art = AutosarBackend().compile_full(mod)
        assert 'xmlns="http://autosar.org/schema/r4.0"' in art.arxml
        assert "<APPLICATION-SW-COMPONENT-TYPE>" in art.arxml
        assert "<SHORT-NAME>Autopilot</SHORT-NAME>" in art.arxml

    def test_per_param_receiver_ports(self):
        mod = _profile(AUTOPILOT)
        art = AutosarBackend().compile_full(mod)
        for p in ("pitch_setpoint", "pitch_measured", "pitch_integral"):
            assert f"<SHORT-NAME>{p}</SHORT-NAME>" in art.arxml
            # R-PORT-PROTOTYPE entries are receiver ports.
            assert f"<REQUIRED-INTERFACE-TREF DEST=\"SENDER-RECEIVER-INTERFACE\">/Forge/Interfaces/{p}_IF" in art.arxml

    def test_result_sender_port(self):
        mod = _profile(AUTOPILOT)
        art = AutosarBackend().compile_full(mod)
        assert "<P-PORT-PROTOTYPE>" in art.arxml
        assert "<PROVIDED-INTERFACE-TREF DEST=\"SENDER-RECEIVER-INTERFACE\">/Forge/Interfaces/result_IF" in art.arxml

    def test_runnable_has_read_and_write_access(self):
        mod = _profile(AUTOPILOT)
        art = AutosarBackend().compile_full(mod)
        assert "<RUNNABLE-ENTITY>" in art.arxml
        assert "<SHORT-NAME>Run_autopilot_step</SHORT-NAME>" in art.arxml
        assert "<DATA-READ-ACCESSS>" in art.arxml
        assert "<DATA-WRITE-ACCESSS>" in art.arxml

    def test_c_source_calls_rte_macros(self):
        mod = _profile(AUTOPILOT)
        art = AutosarBackend().compile_full(mod)
        c = art.c_source
        # Reads via Rte_Read_<fn>_<port>(&local).
        assert "Rte_Read_autopilot_step_pitch_setpoint(&pitch_setpoint);" in c
        assert "Rte_Read_autopilot_step_pitch_measured(&pitch_measured);" in c
        assert "Rte_Read_autopilot_step_pitch_integral(&pitch_integral);" in c
        # Writes via Rte_Write_<fn>_result(value).
        assert "Rte_Write_autopilot_step_result(result);" in c
        # FUNC(void, RTE_CODE) is the AUTOSAR signature macro.
        assert "FUNC(void, RTE_CODE) Run_autopilot_step(void)" in c


# ── AADL backend ───────────────────────────────────────────────


class TestAadlBackend:
    def test_empty_module_raises(self):
        mod = _profile_source("// nothing here\n")
        with pytest.raises(AadlErr):
            AadlBackend().compile(mod)

    def test_package_block(self):
        mod = _profile(AUTOPILOT)
        out = AadlBackend().compile(mod)
        assert out.startswith(
            "-- Generated by EML-lang AADL backend"
        ) or "-- Generated by EML-lang AADL backend" in out
        assert "package Autopilot" in out
        assert "public" in out
        assert "with Base_Types;" in out
        assert "end Autopilot;" in out

    def test_top_level_system(self):
        mod = _profile(AUTOPILOT)
        out = AadlBackend().compile(mod)
        assert "system Autopilot_System" in out
        assert "system implementation Autopilot_System.impl" in out
        assert "subcomponents" in out

    def test_thread_per_function(self):
        mod = _profile(AUTOPILOT)
        out = AadlBackend().compile(mod)
        assert "thread GravityCompensation_T" in out
        assert "thread RateController_T" in out
        assert "thread AutopilotStep_T" in out

    def test_thread_features_have_data_ports(self):
        mod = _profile(AUTOPILOT)
        out = AadlBackend().compile(mod)
        # autopilot_step has 3 input ports and 1 result port.
        assert "pitch_setpoint : in data port Base_Types::Float_64;" in out
        assert "pitch_measured : in data port Base_Types::Float_64;" in out
        assert "pitch_integral : in data port Base_Types::Float_64;" in out
        assert "result : out data port Base_Types::Float_64;" in out

    def test_target_fpga_emits_periodic_dispatch(self):
        # autopilot_step has @target(fpga, clock_mhz = 100)
        mod = _profile(AUTOPILOT)
        out = AadlBackend().compile(mod)
        assert "Dispatch_Protocol => Periodic;" in out
        assert "Period =>" in out

    def test_compute_execution_time_uses_fpga_estimate(self):
        mod = _profile(AUTOPILOT)
        out = AadlBackend().compile(mod)
        assert "Compute_Execution_Time => 0 us .." in out

    def test_thread_implementation_lists_source_language(self):
        mod = _profile(AUTOPILOT)
        out = AadlBackend().compile(mod)
        assert "thread implementation AutopilotStep_T.impl" in out
        assert "Source_Language => (C);" in out
