package research.monogate.forge.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.ui.popup.JBPopupFactory
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.terminal.TerminalShellCommandHandler
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import org.jetbrains.plugins.terminal.TerminalView

/**
 * "Monogate Forge: Compile to..." action. Pops a target picker, then
 * runs `python tools/cli/main.py <file> --target <pick>` in the
 * built-in terminal.
 *
 * The action is gated on the active editor having a `.eml` file open;
 * otherwise it is invisible from the Tools menu.
 */
class CompileToAction : AnAction() {

    private val targets: List<TargetChoice> = listOf(
        TargetChoice("c",       "C99 source via libmonogate"),
        TargetChoice("rust",    "Rust source via the monogate-sys crate"),
        TargetChoice("python",  "Python module using math.* (Tool 5)"),
        TargetChoice("llvm",    "Portable LLVM IR"),
        TargetChoice("wasm",    "WebAssembly bytecode (or LLVM IR fallback)"),
        TargetChoice("verilog", "Synthesizable Verilog (FPGA target)"),
        TargetChoice("vhdl",    "VHDL-2008 (FPGA target)"),
        TargetChoice("chisel",  "Chisel 3 / FIRRTL source"),
        TargetChoice("lean",    "Lean 4 verification artifacts"),
        TargetChoice("all",     "All live backends; writes to source dir"),
    )

    override fun update(e: AnActionEvent) {
        val file = e.getData(CommonDataKeys.VIRTUAL_FILE)
        e.presentation.isEnabledAndVisible =
            file != null && file.extension == "eml"
    }

    override fun actionPerformed(e: AnActionEvent) {
        val project = e.project ?: return
        val file = e.getData(CommonDataKeys.VIRTUAL_FILE) ?: return
        FileDocumentManager.getInstance()
            .saveAllDocuments()

        val popup = JBPopupFactory.getInstance().createPopupChooserBuilder(targets)
            .setItemChosenCallback { choice ->
                runCompile(project, file, choice.id)
            }
            .setTitle("eml-compile --target …")
            .createPopup()
        popup.showInFocusCenter()
    }

    private fun runCompile(project: Project, file: VirtualFile, target: String) {
        val command = """python tools/cli/main.py "${file.path}" --target $target"""
        try {
            val terminalView = TerminalView.getInstance(project)
            val terminal = terminalView.createLocalShellWidget(
                project.basePath,
                "eml-compile --target $target",
            )
            terminal.executeCommand(command)
        } catch (_: Throwable) {
            // Plugin-Terminal may not be available in every IDE flavor;
            // fall back to a simple notification.
            ToolWindowManager.getInstance(project)
                .notifyByBalloon(
                    "Terminal",
                    com.intellij.openapi.ui.MessageType.INFO,
                    "Run manually: $command",
                )
        }
    }

    private data class TargetChoice(val id: String, val description: String) {
        override fun toString() = "$id  -- $description"
    }
}
