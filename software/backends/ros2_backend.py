"""ROS2 node generator backend.

Wraps the C++ backend's output in a complete ROS2 package
(CMakeLists.txt + package.xml + node source) so the EML-lang
controller can be dropped straight into a robot stack.

Picks the *primary* function to wrap as a node according to:

  1. The first function carrying ``@verify(lean, ...)`` — that's
     typically the production-shape entry-point.
  2. Else the first function with ``@target(fpga, ...)``.
  3. Else the last function in the module.

The node subscribes to one ``std_msgs/msg/Float64`` topic per
parameter and publishes the result on ``/<fn>/result``. Latest-
sample fan-in is used (each subscription updates a cached value;
the publisher fires whenever the last-arriving topic ticks).

Output shape
============

``Ros2Backend.compile_full(mod)`` returns a ``Ros2Artifact`` with
``cmakelists``, ``package_xml``, ``node_source``, and
``package_name`` strings. ``Ros2Backend.compile(mod)`` returns
the three concatenated with banner separators -- useful for a
single-file dump on stdout.

Reference: lang/spec/EML_LANG_DESIGN.md + Phase 3 backend roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass

from lang.parser.ast_nodes import (
    EMLFunction,
    EMLModule,
)
from software.backends.cpp_backend import CppBackend


@dataclass(frozen=True)
class Ros2Artifact:
    """Result of compile_full -- the three files of a ROS2 package."""
    cmakelists: str
    package_xml: str
    node_source: str
    package_name: str
    primary_fn: str


class CompileError(Exception):
    """Raised when no function in the module is wrappable."""


class Ros2Backend:
    """Compile an EMLModule to a ROS2 C++ node package."""

    name = "ros2"

    def __init__(self, *, optimize: bool = True) -> None:
        self.optimize = optimize

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule) -> str:
        art = self.compile_full(mod)
        sep = "─" * 70
        return (
            f"// {sep}\n"
            f"// CMakeLists.txt -- save as {art.package_name}/CMakeLists.txt\n"
            f"// {sep}\n\n"
            f"{art.cmakelists}\n"
            f"<!-- {sep} -->\n"
            f"<!-- package.xml -- save as {art.package_name}/package.xml -->\n"
            f"<!-- {sep} -->\n\n"
            f"{art.package_xml}\n"
            f"// {sep}\n"
            f"// src/{art.primary_fn}_node.cpp\n"
            f"// {sep}\n\n"
            f"{art.node_source}"
        )

    def compile_full(self, mod: EMLModule) -> Ros2Artifact:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        primary = self._pick_primary(mod)
        if primary is None:
            raise CompileError(
                "ROS2 backend: module has no functions "
                "(no candidate to wrap as a node)"
            )

        package_name = (mod.name or "forge_module") + "_pkg"

        # Hand the entire module to the C++ backend; the result
        # contains every helper plus the primary function. We
        # include it verbatim in the node source so the wrapper
        # has access to everything it needs.
        cpp_src = CppBackend(optimize=False).compile(mod)

        node_source = self._emit_node(mod, primary, cpp_src)
        cmakelists = self._emit_cmakelists(package_name, primary)
        package_xml = self._emit_package_xml(package_name, primary)
        return Ros2Artifact(
            cmakelists=cmakelists,
            package_xml=package_xml,
            node_source=node_source,
            package_name=package_name,
            primary_fn=primary.name,
        )

    # ── Primary picker ────────────────────────────────────────

    @staticmethod
    def _pick_primary(mod: EMLModule) -> EMLFunction | None:
        candidates = [f for f in mod.functions if not f.is_extern]
        if not candidates:
            return None

        def has_annot(fn: EMLFunction, kind: str, first_arg: str) -> bool:
            for a in fn.annotations:
                if a.kind == kind and a.args.get(0) == first_arg:
                    return True
            return False

        for fn in candidates:
            if has_annot(fn, "verify", "lean"):
                return fn
        for fn in candidates:
            if has_annot(fn, "target", "fpga"):
                return fn
        return candidates[-1]

    # ── Node source ───────────────────────────────────────────

    def _emit_node(
        self,
        mod: EMLModule,
        primary: EMLFunction,
        cpp_src: str,
    ) -> str:
        ns = f"forge::{mod.name or 'anon'}"
        fn = primary.name
        param_names = [p.name for p in primary.params]
        node_class = "".join(
            w.capitalize() for w in fn.split("_")
        ) + "Node"

        # Subscriber field declarations + cache fields.
        sub_decls = "\n".join(
            f"    rclcpp::Subscription<std_msgs::msg::Float64>::SharedPtr sub_{p};"
            for p in param_names
        )
        cache_decls = "\n".join(
            f"    double cache_{p} {{0.0}};"
            for p in param_names
        )
        ready_decls = "\n".join(
            f"    bool ready_{p} {{false}};"
            for p in param_names
        )

        # Per-param subscription wiring inside the constructor.
        sub_inits = []
        for p in param_names:
            sub_inits.append(
                f'        sub_{p} = create_subscription<std_msgs::msg::Float64>(\n'
                f'            "/{fn}/{p}", 10,\n'
                f'            [this](const std_msgs::msg::Float64::SharedPtr msg) {{\n'
                f'                cache_{p} = msg->data;\n'
                f'                ready_{p} = true;\n'
                f'                publish_if_ready();\n'
                f'            }});'
            )
        sub_init_block = "\n\n".join(sub_inits)

        ready_check = " && ".join(f"ready_{p}" for p in param_names)
        call_args = ", ".join(f"cache_{p}" for p in param_names)

        # Include the C++ backend's emit verbatim. We strip its
        # `#pragma once` (already triggered by the node's TU) but
        # keep everything else.
        cpp_body = cpp_src.replace("#pragma once\n", "", 1)

        return (
            f'// Generated by EML-lang ROS2 backend\n'
            f'// Source module: {mod.name or "(unnamed)"}\n'
            f'// Source file:   {mod.source_file}\n'
            f'// Primary fn:    {fn}  (auto-picked: '
            f'{"@verify(lean)" if any(a.kind == "verify" and a.args.get(0) == "lean" for a in primary.annotations) else "@target(fpga)" if any(a.kind == "target" and a.args.get(0) == "fpga" for a in primary.annotations) else "last function"})\n'
            f'\n'
            f'#include <memory>\n'
            f'#include "rclcpp/rclcpp.hpp"\n'
            f'#include "std_msgs/msg/float64.hpp"\n'
            f'\n'
            f'// ── Embedded controller (from EML-lang C++ backend) ────────\n'
            f'\n'
            f'{cpp_body}\n'
            f'// ── ROS2 node wrapper ──────────────────────────────────────\n'
            f'\n'
            f'class {node_class} : public rclcpp::Node {{\n'
            f'public:\n'
            f'    {node_class}() : Node("{fn}_node") {{\n'
            f'        pub_ = create_publisher<std_msgs::msg::Float64>(\n'
            f'            "/{fn}/result", 10);\n'
            f'\n'
            f'{sub_init_block}\n'
            f'\n'
            f'        RCLCPP_INFO(get_logger(), '
            f'"{fn}_node ready -- publishing on /{fn}/result");\n'
            f'    }}\n'
            f'\n'
            f'private:\n'
            f'    void publish_if_ready() {{\n'
            f'        if (!({ready_check})) return;\n'
            f'        const double r = {ns}::{fn}({call_args});\n'
            f'        std_msgs::msg::Float64 msg;\n'
            f'        msg.data = r;\n'
            f'        pub_->publish(msg);\n'
            f'    }}\n'
            f'\n'
            f'    rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr pub_;\n'
            f'{sub_decls}\n'
            f'\n'
            f'{cache_decls}\n'
            f'{ready_decls}\n'
            f'}};\n'
            f'\n'
            f'int main(int argc, char ** argv) {{\n'
            f'    rclcpp::init(argc, argv);\n'
            f'    rclcpp::spin(std::make_shared<{node_class}>());\n'
            f'    rclcpp::shutdown();\n'
            f'    return 0;\n'
            f'}}\n'
        )

    # ── CMakeLists.txt ────────────────────────────────────────

    def _emit_cmakelists(
        self, package_name: str, primary: EMLFunction,
    ) -> str:
        node_target = f"{primary.name}_node"
        return (
            f"# Generated by EML-lang ROS2 backend\n"
            f"cmake_minimum_required(VERSION 3.16)\n"
            f"project({package_name})\n"
            f"\n"
            f"if(NOT CMAKE_CXX_STANDARD)\n"
            f"  set(CMAKE_CXX_STANDARD 17)\n"
            f"endif()\n"
            f"\n"
            f"if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES \"Clang\")\n"
            f"  add_compile_options(-Wall -Wextra -Wpedantic)\n"
            f"endif()\n"
            f"\n"
            f"find_package(ament_cmake REQUIRED)\n"
            f"find_package(rclcpp REQUIRED)\n"
            f"find_package(std_msgs REQUIRED)\n"
            f"\n"
            f"add_executable({node_target} src/{node_target}.cpp)\n"
            f"ament_target_dependencies({node_target} rclcpp std_msgs)\n"
            f"\n"
            f"install(TARGETS {node_target}\n"
            f"  DESTINATION lib/${{PROJECT_NAME}})\n"
            f"\n"
            f"ament_package()\n"
        )

    # ── package.xml ───────────────────────────────────────────

    def _emit_package_xml(
        self, package_name: str, primary: EMLFunction,
    ) -> str:
        return (
            f'<?xml version="1.0"?>\n'
            f'<?xml-model href="http://download.ros.org/schema/package_format3.xsd"\n'
            f'            schematypens="http://www.w3.org/2001/XMLSchema"?>\n'
            f'<package format="3">\n'
            f'  <name>{package_name}</name>\n'
            f'  <version>0.1.0</version>\n'
            f'  <description>\n'
            f'    Auto-generated ROS2 node wrapping the EML-lang function '
            f'`{primary.name}`.\n'
            f'    Generated by Monogate Forge.\n'
            f'  </description>\n'
            f'  <maintainer email="forge@monogate.dev">Monogate Forge</maintainer>\n'
            f'  <license>Apache-2.0</license>\n'
            f'\n'
            f'  <buildtool_depend>ament_cmake</buildtool_depend>\n'
            f'\n'
            f'  <depend>rclcpp</depend>\n'
            f'  <depend>std_msgs</depend>\n'
            f'\n'
            f'  <test_depend>ament_lint_auto</test_depend>\n'
            f'  <test_depend>ament_lint_common</test_depend>\n'
            f'\n'
            f'  <export>\n'
            f'    <build_type>ament_cmake</build_type>\n'
            f'  </export>\n'
            f'</package>\n'
        )
