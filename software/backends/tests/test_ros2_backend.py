"""Tests for the ROS2 node generator backend (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.ros2_backend import (
    Ros2Backend,
    Ros2Artifact,
    CompileError,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
AUTOPILOT = REPO_ROOT / "industries" / "aerospace" / "flight_control" / "autopilot.eml"


@pytest.fixture
def backend() -> Ros2Backend:
    return Ros2Backend()


def _compile(path: Path, backend: Ros2Backend) -> Ros2Artifact:
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return backend.compile_full(mod)


# ── Empty module raises ─────────────────────────────────────


def test_empty_module_raises_compile_error():
    src = "// no functions here\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    with pytest.raises(CompileError):
        Ros2Backend().compile_full(mod)


# ── Primary picker ──────────────────────────────────────────


def test_primary_picker_prefers_verify_lean():
    src = (
        "fn helper(x: Real) -> Real { x }\n"
        "@verify(lean, theorem = \"f_bound\")\n"
        "fn entry(x: Real) -> Real ensures (result >= 0.0) { x }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    art = Ros2Backend().compile_full(mod)
    assert art.primary_fn == "entry"


def test_primary_picker_falls_back_to_target_fpga():
    src = (
        "fn helper(x: Real) -> Real { x }\n"
        "@target(fpga, clock_mhz = 100)\n"
        "fn fpga_fn(x: Real) -> Real { x * 2.0 }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    art = Ros2Backend().compile_full(mod)
    assert art.primary_fn == "fpga_fn"


def test_primary_picker_falls_back_to_last_function():
    src = (
        "fn helper_a(x: Real) -> Real { x }\n"
        "fn helper_b(x: Real) -> Real { x + 1.0 }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    art = Ros2Backend().compile_full(mod)
    assert art.primary_fn == "helper_b"


# ── Autopilot full package ──────────────────────────────────


def test_autopilot_package_name(backend):
    art = _compile(AUTOPILOT, backend)
    assert art.package_name == "autopilot_pkg"
    assert art.primary_fn == "autopilot_step"


def test_cmakelists_uses_ament_cmake(backend):
    art = _compile(AUTOPILOT, backend)
    cm = art.cmakelists
    assert "cmake_minimum_required" in cm
    assert "find_package(ament_cmake REQUIRED)" in cm
    assert "find_package(rclcpp REQUIRED)" in cm
    assert "find_package(std_msgs REQUIRED)" in cm
    assert "ament_target_dependencies(autopilot_step_node rclcpp std_msgs)" in cm
    assert "ament_package()" in cm


def test_package_xml_has_format_3(backend):
    art = _compile(AUTOPILOT, backend)
    px = art.package_xml
    assert '<package format="3">' in px
    assert "<buildtool_depend>ament_cmake</buildtool_depend>" in px
    assert "<depend>rclcpp</depend>" in px
    assert "<depend>std_msgs</depend>" in px


def test_node_class_camelcase_from_function_name(backend):
    art = _compile(AUTOPILOT, backend)
    assert "class AutopilotStepNode : public rclcpp::Node" in art.node_source


def test_node_subscribes_to_each_param(backend):
    art = _compile(AUTOPILOT, backend)
    src = art.node_source
    for p in ("pitch_setpoint", "pitch_measured", "pitch_integral"):
        assert f'create_subscription<std_msgs::msg::Float64>(\n            "/autopilot_step/{p}"' in src
        assert f"cache_{p}" in src
        assert f"ready_{p}" in src


def test_node_publishes_on_result_topic(backend):
    art = _compile(AUTOPILOT, backend)
    src = art.node_source
    assert 'create_publisher<std_msgs::msg::Float64>(\n            "/autopilot_step/result"' in src
    assert "pub_->publish(msg)" in src


def test_publish_if_ready_calls_namespaced_function(backend):
    art = _compile(AUTOPILOT, backend)
    src = art.node_source
    assert "void publish_if_ready()" in src
    # All inputs must be ready before the node fires.
    assert "ready_pitch_setpoint && ready_pitch_measured && ready_pitch_integral" in src
    # The C++ call uses the namespaced symbol from the embedded backend.
    assert "forge::autopilot::autopilot_step(cache_pitch_setpoint, cache_pitch_measured, cache_pitch_integral)" in src


def test_main_function_present(backend):
    art = _compile(AUTOPILOT, backend)
    src = art.node_source
    assert "int main(int argc, char ** argv)" in src
    assert "rclcpp::init(argc, argv);" in src
    assert "rclcpp::spin(std::make_shared<AutopilotStepNode>())" in src
    assert "rclcpp::shutdown();" in src


def test_node_includes_embedded_cpp_controller(backend):
    art = _compile(AUTOPILOT, backend)
    src = art.node_source
    # The embedded C++ output is included verbatim (sans #pragma once).
    assert "namespace forge::autopilot" in src
    assert "double autopilot_step" in src
    # `#pragma once` is stripped because the node is its own TU.
    assert "#pragma once" not in src


# ── Combined stdout form ────────────────────────────────────


def test_compile_combined_string_has_all_three_sections(backend):
    mod = parse_file(AUTOPILOT)
    Profiler().profile_module(mod)
    combined = backend.compile(mod)
    assert "save as autopilot_pkg/CMakeLists.txt" in combined
    assert "save as autopilot_pkg/package.xml" in combined
    assert "src/autopilot_step_node.cpp" in combined
