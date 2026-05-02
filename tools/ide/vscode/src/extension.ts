/**
 * Monogate Forge VS Code extension entry point.
 *
 * Surface today:
 *
 *   ProfileLensProvider     CodeLens above each `fn` header showing
 *                           inferred chain order + cost class + FPGA
 *                           resource estimate.
 *
 *   ChainOrderDiagnostics   On save, runs the profiler and surfaces
 *                           chain-order constraint violations.
 *
 *   FpgaStatusBarItem       Status-bar entry showing aggregate FPGA
 *                           resource usage (LUTs / DSPs / cycles)
 *                           for the active .eml when it has at least
 *                           one @target(fpga) function.
 *
 *   "Compile to..." picker  Single command palette entry that asks
 *                           the user to pick from the 9 live targets
 *                           (c / rust / python / llvm / wasm /
 *                           verilog / vhdl / chisel / lean) plus
 *                           "all".
 *
 *   format-on-save          DocumentFormattingEditProvider that
 *                           shells out to `eml-compile --fmt`.
 *
 * The extension shells out to `python tools/cli/main.py` rather than
 * reimplementing parsing in TypeScript -- the Python CLI is the
 * source of truth.
 */

import * as vscode from 'vscode';
import { ChainOrderDiagnostics } from './diagnostics';
import { ProfileLensProvider } from './profileProvider';
import { resolveForge, runForge } from './forgeCli';
import { startLspClient } from './lspClient';

const ALL_TARGETS: ReadonlyArray<{ id: string; description: string }> = [
    // Software
    { id: 'c',             description: 'C99 source via libmonogate' },
    { id: 'cpp',           description: 'C++17 source' },
    { id: 'rust',          description: 'Rust source via the monogate-sys crate' },
    { id: 'go',            description: 'Go source using math.* / gonum' },
    { id: 'java',          description: 'Java source (java.lang.Math)' },
    { id: 'kotlin',        description: 'Kotlin source (kotlin.math)' },
    { id: 'python',        description: 'Python module using math.* (Tool 5)' },
    { id: 'matlab',        description: 'MATLAB / Octave .m source' },
    // Low-level / bytecode
    { id: 'llvm',          description: 'Portable LLVM IR' },
    { id: 'wasm',          description: 'WebAssembly bytecode (LLVM IR fallback)' },
    // Hardware
    { id: 'verilog',       description: 'Synthesizable Verilog (FPGA target)' },
    { id: 'systemverilog', description: 'SystemVerilog with assertions' },
    { id: 'vhdl',          description: 'VHDL-2008 (FPGA target)' },
    { id: 'chisel',        description: 'Chisel 3 / FIRRTL source' },
    // Safety-critical / certification
    { id: 'ada',           description: 'Ada / SPARK 2014' },
    { id: 'autosar',       description: 'AUTOSAR Classic (.arxml + C)' },
    { id: 'aadl',          description: 'AADL architecture model' },
    { id: 'ros2',          description: 'ROS 2 node skeleton' },
    // Verification
    { id: 'lean',          description: 'Lean 4 verification artifacts' },
    { id: 'coq',           description: 'Coq / Rocq verification artifacts' },
    { id: 'isabelle',      description: 'Isabelle/HOL theory file' },
    // Smart contracts
    { id: 'solidity',      description: 'Solidity contract (PRBMath SD59x18)' },
    // Bulk
    { id: 'all',           description: 'All live backends; writes to source dir' },
];

export function activate(context: vscode.ExtensionContext): void {
    const lensProvider = new ProfileLensProvider();
    context.subscriptions.push(
        vscode.languages.registerCodeLensProvider(
            { language: 'eml' },
            lensProvider,
        ),
    );

    // Try to start the LSP server. When it succeeds, it owns the
    // diagnostics pipeline (real-time as you type). When it
    // doesn't (eml-lsp not on PATH), fall back to the legacy
    // save-triggered ChainOrderDiagnostics so the extension still
    // surfaces errors -- just only on save.
    const lsp = startLspClient(context);
    const diagnostics = lsp ? null : new ChainOrderDiagnostics();
    if (diagnostics) {
        context.subscriptions.push(diagnostics);
    }

    const fpgaStatus = new FpgaStatusBarItem();
    context.subscriptions.push(fpgaStatus);

    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument((doc) => {
            if (doc.languageId === 'eml') {
                // Lenses + FPGA status still refresh on save --
                // they're not diagnostics. The LSP (when present)
                // handles errors-as-you-type without our help.
                diagnostics?.refresh(doc);
                lensProvider.refresh();
                fpgaStatus.refresh(doc);
            }
        }),
        vscode.window.onDidChangeActiveTextEditor((editor) => {
            if (editor && editor.document.languageId === 'eml') {
                fpgaStatus.refresh(editor.document);
            } else {
                fpgaStatus.hide();
            }
        }),
    );

    // Format-on-save provider -- shells out to eml-compile --fmt.
    context.subscriptions.push(
        vscode.languages.registerDocumentFormattingEditProvider(
            'eml',
            new EmlFormattingProvider(),
        ),
    );

    // Commands users can invoke from the palette. Per-target shortcut
    // commands are registered in a loop so adding a 23rd backend only
    // means appending one entry to ALL_TARGETS (and contributes.commands
    // in package.json so the palette picks it up).
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'monogate-forge.profile',
            () => lensProvider.refresh(),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.pick',
            () => compileToPicker(),
        ),
    );
    for (const t of ALL_TARGETS) {
        context.subscriptions.push(
            vscode.commands.registerCommand(
                `monogate-forge.compile.${t.id}`,
                () => compileTo(t.id),
            ),
        );
    }

    // Refresh status bar for the editor that's already open at
    // activation, if any.
    if (vscode.window.activeTextEditor?.document.languageId === 'eml') {
        fpgaStatus.refresh(vscode.window.activeTextEditor.document);
    }
}

export function deactivate(): void {
    // No cleanup needed; subscriptions clean up automatically.
}

async function compileToPicker(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'eml') {
        vscode.window.showErrorMessage(
            'monogate-forge: open a .eml file first',
        );
        return;
    }
    const pick = await vscode.window.showQuickPick(
        ALL_TARGETS.map((t) => ({
            label: t.id,
            description: t.description,
        })),
        {
            placeHolder: 'Pick a target for eml-compile --target ...',
            matchOnDescription: true,
        },
    );
    if (!pick) {
        return;
    }
    await compileTo(pick.label);
}

async function compileTo(target: string): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'eml') {
        vscode.window.showErrorMessage(
            'monogate-forge: open a .eml file first',
        );
        return;
    }
    await editor.document.save();
    const sourcePath = editor.document.uri.fsPath;
    const inv = resolveForge(sourcePath);
    if (!inv) return;  // resolveForge already showed an install hint

    // Quote the source path so terminal users with spaces in their
    // paths don't end up with a confusing parse error.
    const quoted = `"${sourcePath}"`;
    const terminalCmd = inv.source === 'package'
        ? `eml-compile ${quoted} --target ${target}`
        : `${inv.cmd} ${inv.args.join(' ')} ${quoted} --target ${target}`;

    const terminal = vscode.window.createTerminal({
        name: `eml-compile --target ${target}`,
        cwd: inv.cwd,
    });
    terminal.show();
    terminal.sendText(terminalCmd);
}


/**
 * format-on-save / explicit format provider.
 *
 * Shells out to `python tools/cli/main.py <file> --fmt` and replaces
 * the entire document with the canonical output. Save-after-format is
 * handled by VS Code automatically.
 */
class EmlFormattingProvider implements vscode.DocumentFormattingEditProvider {
    public async provideDocumentFormattingEdits(
        document: vscode.TextDocument,
    ): Promise<vscode.TextEdit[]> {
        const inv = resolveForge(document.uri.fsPath);
        if (!inv) return [];
        try {
            const { stdout } = await runForge(
                inv,
                [document.uri.fsPath, '--fmt'],
                15_000,
            );
            const fullRange = new vscode.Range(
                document.positionAt(0),
                document.positionAt(document.getText().length),
            );
            return [vscode.TextEdit.replace(fullRange, stdout)];
        } catch (err) {
            const out = vscode.window.createOutputChannel('Monogate Forge');
            out.appendLine(`fmt error: ${(err as Error).message}`);
            out.show(true);
            return [];
        }
    }
}


/**
 * Status-bar entry showing FPGA allocation summary for the active .eml.
 *
 * Hidden when:
 *   - active editor is not .eml
 *   - the file has no @target(fpga) functions (allocator returns an error)
 *
 * On save / editor switch, re-runs `eml-compile --allocate --fpga-target=...`
 * in the workspace root.
 */
class FpgaStatusBarItem implements vscode.Disposable {
    private item: vscode.StatusBarItem;
    private inflight = 0;

    constructor() {
        this.item = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            100,
        );
        this.item.command = 'monogate-forge.profile';
    }

    public async refresh(doc: vscode.TextDocument): Promise<void> {
        if (doc.languageId !== 'eml') {
            this.item.hide();
            return;
        }
        const inv = resolveForge(doc.uri.fsPath);
        if (!inv) {
            this.item.hide();
            return;
        }
        const target = vscode.workspace
            .getConfiguration('eml.fpga')
            .get<string>('target', 'xilinx.artix7');

        const myToken = ++this.inflight;
        try {
            const { stdout } = await runForge(inv, [
                doc.uri.fsPath, '--allocate', '--fpga-target', target,
            ]);
            if (myToken !== this.inflight) return;
            const summary = parseAllocationSummary(stdout);
            if (!summary) {
                this.item.hide();
                return;
            }
            this.item.text =
                `$(circuit-board) ${summary.luts} LUT  ` +
                `${summary.dsps} DSP  ${summary.cycles} cy`;
            this.item.tooltip = `FPGA target: ${target}\n${stdout}`;
            this.item.show();
        } catch {
            if (myToken === this.inflight) this.item.hide();
        }
    }

    public hide(): void {
        this.item.hide();
    }

    public dispose(): void {
        this.item.dispose();
    }
}


function parseAllocationSummary(out: string):
    { luts: string; dsps: string; cycles: string } | null
{
    // Loose parser -- the exact output of plan.render() is small
    // enough that regexes are fine.
    const lutMatch = /(\d+)\s+LUTs?/i.exec(out);
    const dspMatch = /(\d+)\s+DSPs?/i.exec(out);
    const cyMatch  = /(\d+)\s+(?:cycles?|cy)\b/i.exec(out);
    if (!lutMatch || !dspMatch) {
        return null;
    }
    return {
        luts:   lutMatch[1],
        dsps:   dspMatch[1],
        cycles: cyMatch ? cyMatch[1] : '?',
    };
}


// pythonCli + workspaceRoot used to live here; both moved into
// forgeCli.resolveForge() so all CLI invocations share one
// discovery + caching path. The legacy `eml.compile.python`
// setting is still honored as the python executable in the
// checkout-fallback branch (see forgeCli.ts).
