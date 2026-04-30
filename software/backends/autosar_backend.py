"""AUTOSAR Classic Platform backend (R20-11 schema).

Emits the two artefacts an automotive ECU integration team needs
to drop a Forge-derived controller into an AUTOSAR project:

  * ``<Module>_swc.arxml`` -- the AUTOSAR XML (ARXML) descriptor
    declaring an Application Software Component (SWC) with a
    sender-receiver port per parameter and one for the result,
    plus a runnable that wraps the EML function.
  * ``<Module>.c`` -- the AUTOSAR-style C implementation that
    reads each input via ``Rte_Read_<port>(...)``, calls the
    Forge-emitted function, and writes the result via
    ``Rte_Write_<port>(...)``.

The C body of the function itself is the existing ``CBackend``
output -- AUTOSAR doesn't change the math, only the integration
boilerplate.

Output shape
============

``AutosarBackend.compile_full(mod)`` returns an ``AutosarArtifact``
with ``arxml``, ``c_source``, ``swc_name``, and ``primary_fn``
strings. ``compile()`` returns both concatenated with banner
separators -- useful for stdout dump.

Reference: lang/spec/EML_LANG_DESIGN.md + Phase 4 backend roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass

from lang.parser.ast_nodes import (
    Annotation,
    EMLFunction,
    EMLModule,
    NodeKind,
)
from software.backends.c_backend import CBackend


@dataclass(frozen=True)
class AutosarArtifact:
    """ARXML descriptor + AUTOSAR-compliant C source pair."""
    arxml: str
    c_source: str
    swc_name: str
    primary_fn: str


class CompileError(Exception):
    """Raised when no function in the module is wrappable."""


def _swc_name(mod: EMLModule) -> str:
    """AUTOSAR component names use UpperCamelCase."""
    base = mod.name or "ForgeSwc"
    parts = base.split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts) or "ForgeSwc"


class AutosarBackend:
    """Compile an EMLModule to an AUTOSAR Classic SWC."""

    name = "autosar"

    def __init__(self, *, optimize: bool = True) -> None:
        self.optimize = optimize

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule) -> str:
        art = self.compile_full(mod)
        sep = "─" * 70
        return (
            f"<!-- {sep} -->\n"
            f"<!-- ARXML descriptor -- save as {art.swc_name}_swc.arxml -->\n"
            f"<!-- {sep} -->\n\n"
            f"{art.arxml}\n"
            f"/* {sep} */\n"
            f"/* C implementation -- save as {art.swc_name}.c */\n"
            f"/* {sep} */\n\n"
            f"{art.c_source}"
        )

    def compile_full(self, mod: EMLModule) -> AutosarArtifact:
        if self.optimize:
            from lang.optimizer import optimize_module
            mod = optimize_module(mod)

        primary = self._pick_primary(mod)
        if primary is None:
            raise CompileError(
                "AUTOSAR backend: module has no functions to wrap "
                "as a SWC runnable."
            )

        swc = _swc_name(mod)
        arxml = self._emit_arxml(mod, primary, swc)
        c_source = self._emit_c(mod, primary, swc)
        return AutosarArtifact(
            arxml=arxml,
            c_source=c_source,
            swc_name=swc,
            primary_fn=primary.name,
        )

    # ── Primary picker ────────────────────────────────────────

    @staticmethod
    def _pick_primary(mod: EMLModule) -> EMLFunction | None:
        candidates = [f for f in mod.functions if not f.is_extern]
        if not candidates:
            return None
        for fn in candidates:
            for a in fn.annotations:
                if a.kind == "verify" and a.args.get(0) == "lean":
                    return fn
        for fn in candidates:
            for a in fn.annotations:
                if a.kind == "target" and a.args.get(0) == "fpga":
                    return fn
        return candidates[-1]

    # ── ARXML descriptor ──────────────────────────────────────

    def _emit_arxml(
        self,
        mod: EMLModule,
        primary: EMLFunction,
        swc: str,
    ) -> str:
        """Generate a minimal AUTOSAR R20-11 ARXML SWC descriptor.

        The SWC has:
          - One ``ApplicationDataType`` of ``CONST_VALUE`` flavour
            (we use ``float64`` everywhere via a single shared type).
          - One ``RECEIVER`` port per parameter (sender-receiver
            interface, dataElement = parameter name).
          - One ``SENDER`` port for the result.
          - One ``RUNNABLE_ENTITY`` named ``Run_<fn>`` that the
            RTE invokes; mapped to the C function via the C body
            below.
        """
        runnable = f"Run_{primary.name}"
        fn = primary

        rdata = "\n".join(self._port_data_element(p.name) for p in fn.params)
        sdata = self._port_data_element("result")

        rports = "\n".join(self._receiver_port(p.name) for p in fn.params)
        sports = self._sender_port("result")

        access_reads = "\n".join(self._data_read_access(p.name) for p in fn.params)
        access_writes = self._data_write_access("result")

        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<AUTOSAR xmlns="http://autosar.org/schema/r4.0"\n'
            f'         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
            f'         xsi:schemaLocation="http://autosar.org/schema/r4.0 '
            f'AUTOSAR_00050.xsd">\n'
            f'  <AR-PACKAGES>\n'
            f'    <AR-PACKAGE>\n'
            f'      <SHORT-NAME>Forge</SHORT-NAME>\n'
            f'      <AR-PACKAGES>\n'
            f'        <AR-PACKAGE>\n'
            f'          <SHORT-NAME>Components</SHORT-NAME>\n'
            f'          <ELEMENTS>\n'
            f'            <APPLICATION-SW-COMPONENT-TYPE>\n'
            f'              <SHORT-NAME>{swc}</SHORT-NAME>\n'
            f'              <DESC>\n'
            f'                <L-2 L="EN">Auto-generated by Monogate Forge '
            f'from {mod.source_file}.</L-2>\n'
            f'              </DESC>\n'
            f'              <PORTS>\n'
            f'{rports}\n'
            f'{sports}\n'
            f'              </PORTS>\n'
            f'              <INTERNAL-BEHAVIORS>\n'
            f'                <SWC-INTERNAL-BEHAVIOR>\n'
            f'                  <SHORT-NAME>{swc}_IB</SHORT-NAME>\n'
            f'                  <DATA-TYPE-MAPPING-REFS/>\n'
            f'                  <RUNNABLES>\n'
            f'                    <RUNNABLE-ENTITY>\n'
            f'                      <SHORT-NAME>{runnable}</SHORT-NAME>\n'
            f'                      <SYMBOL>{runnable}</SYMBOL>\n'
            f'                      <DATA-READ-ACCESSS>\n'
            f'{access_reads}\n'
            f'                      </DATA-READ-ACCESSS>\n'
            f'                      <DATA-WRITE-ACCESSS>\n'
            f'{access_writes}\n'
            f'                      </DATA-WRITE-ACCESSS>\n'
            f'                    </RUNNABLE-ENTITY>\n'
            f'                  </RUNNABLES>\n'
            f'                </SWC-INTERNAL-BEHAVIOR>\n'
            f'              </INTERNAL-BEHAVIORS>\n'
            f'            </APPLICATION-SW-COMPONENT-TYPE>\n'
            f'          </ELEMENTS>\n'
            f'        </AR-PACKAGE>\n'
            f'      </AR-PACKAGES>\n'
            f'    </AR-PACKAGE>\n'
            f'  </AR-PACKAGES>\n'
            f'</AUTOSAR>\n'
        )

    @staticmethod
    def _receiver_port(name: str) -> str:
        return (
            f'                <R-PORT-PROTOTYPE>\n'
            f'                  <SHORT-NAME>{name}</SHORT-NAME>\n'
            f'                  <REQUIRED-INTERFACE-TREF DEST='
            f'"SENDER-RECEIVER-INTERFACE">'
            f'/Forge/Interfaces/{name}_IF</REQUIRED-INTERFACE-TREF>\n'
            f'                </R-PORT-PROTOTYPE>'
        )

    @staticmethod
    def _sender_port(name: str) -> str:
        return (
            f'                <P-PORT-PROTOTYPE>\n'
            f'                  <SHORT-NAME>{name}</SHORT-NAME>\n'
            f'                  <PROVIDED-INTERFACE-TREF DEST='
            f'"SENDER-RECEIVER-INTERFACE">'
            f'/Forge/Interfaces/{name}_IF</PROVIDED-INTERFACE-TREF>\n'
            f'                </P-PORT-PROTOTYPE>'
        )

    @staticmethod
    def _port_data_element(name: str) -> str:
        # Reserved for future expansion -- left in the file so the
        # interface package can be regenerated alongside the SWC.
        return f'<!-- dataElement {name} -->'

    @staticmethod
    def _data_read_access(name: str) -> str:
        return (
            f'                        <VARIABLE-ACCESS>\n'
            f'                          <SHORT-NAME>RA_{name}</SHORT-NAME>\n'
            f'                          <ACCESSED-VARIABLE>\n'
            f'                            <AUTOSAR-VARIABLE-IREF>\n'
            f'                              <PORT-PROTOTYPE-REF DEST='
            f'"R-PORT-PROTOTYPE">../../../../{name}</PORT-PROTOTYPE-REF>\n'
            f'                              <TARGET-DATA-PROTOTYPE-REF DEST='
            f'"VARIABLE-DATA-PROTOTYPE">/Forge/Interfaces/{name}_IF/{name}'
            f'</TARGET-DATA-PROTOTYPE-REF>\n'
            f'                            </AUTOSAR-VARIABLE-IREF>\n'
            f'                          </ACCESSED-VARIABLE>\n'
            f'                        </VARIABLE-ACCESS>'
        )

    @staticmethod
    def _data_write_access(name: str) -> str:
        return (
            f'                        <VARIABLE-ACCESS>\n'
            f'                          <SHORT-NAME>WA_{name}</SHORT-NAME>\n'
            f'                          <ACCESSED-VARIABLE>\n'
            f'                            <AUTOSAR-VARIABLE-IREF>\n'
            f'                              <PORT-PROTOTYPE-REF DEST='
            f'"P-PORT-PROTOTYPE">../../../../{name}</PORT-PROTOTYPE-REF>\n'
            f'                              <TARGET-DATA-PROTOTYPE-REF DEST='
            f'"VARIABLE-DATA-PROTOTYPE">/Forge/Interfaces/{name}_IF/{name}'
            f'</TARGET-DATA-PROTOTYPE-REF>\n'
            f'                            </AUTOSAR-VARIABLE-IREF>\n'
            f'                          </ACCESSED-VARIABLE>\n'
            f'                        </VARIABLE-ACCESS>'
        )

    # ── AUTOSAR-style C source ────────────────────────────────

    def _emit_c(
        self,
        mod: EMLModule,
        primary: EMLFunction,
        swc: str,
    ) -> str:
        """Embed the existing C backend's emit + an AUTOSAR-style
        ``Run_<fn>`` runnable that uses RTE Read/Write macros.

        The Run function's prototype matches the AUTOSAR contract:
        no parameters, no return value -- IO flows through the RTE.
        """
        runnable = f"Run_{primary.name}"
        c_body = CBackend(optimize=False).compile(mod)

        read_calls: list[str] = []
        for p in primary.params:
            read_calls.append(
                f"    /* read {p.name} via RTE sender-receiver port */\n"
                f"    double {p.name};\n"
                f"    Rte_Read_{primary.name}_{p.name}(&{p.name});"
            )
        reads_block = "\n".join(read_calls)

        call_args = ", ".join(p.name for p in primary.params)

        return (
            f"/* Generated by EML-lang AUTOSAR backend */\n"
            f"/* Source module: {mod.name or '(unnamed)'} */\n"
            f"/* Source file:   {mod.source_file} */\n"
            f"/* SWC:           {swc} */\n"
            f"/* Runnable:      {runnable} */\n"
            f"\n"
            f"#include \"Rte_{swc}.h\"  /* AUTOSAR RTE header for this SWC */\n"
            f"\n"
            f"/* ── Embedded controller (from EML-lang C backend) ───── */\n"
            f"\n"
            f"{c_body}\n"
            f"/* ── AUTOSAR runnable wrapper ───────────────────────── */\n"
            f"\n"
            f"FUNC(void, RTE_CODE) {runnable}(void) {{\n"
            f"{reads_block}\n"
            f"\n"
            f"    /* Call the Forge-emitted controller */\n"
            f"    const double result = {primary.name}({call_args});\n"
            f"\n"
            f"    /* Publish the result via the RTE sender port */\n"
            f"    Rte_Write_{primary.name}_result(result);\n"
            f"}}\n"
        )
