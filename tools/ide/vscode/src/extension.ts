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

import * as cp from 'child_process';
import * as path from 'path';
import * as vscode from 'vscode';
import { ChainOrderDiagnostics } from './diagnostics';
import { ProfileLensProvider } from './profileProvider';

const ALL_TARGETS: ReadonlyArray<{ id: string; description: string }> = [
    { id: 'c',       description: 'C99 source via libmonogate' },
    { id: 'rust',    description: 'Rust source via the monogate-sys crate' },
    { id: 'python',  description: 'Python module using math.* (Tool 5)' },
    { id: 'llvm',    description: 'Portable LLVM IR' },
    { id: 'wasm',    description: 'WebAssembly bytecode (or LLVM IR fallback)' },
    { id: 'verilog', description: 'Synthesizable Verilog (FPGA target)' },
    { id: 'vhdl',    description: 'VHDL-2008 (FPGA target)' },
    { id: 'chisel',  description: 'Chisel 3 / FIRRTL source' },
    { id: 'lean',    description: 'Lean 4 verification artifacts' },
    { id: 'all',     description: 'All live backends; writes to source dir' },
];

export function activate(context: vscode.ExtensionContext): void {
    const lensProvider = new ProfileLensProvider();
    context.subscriptions.push(
        vscode.languages.registerCodeLensProvider(
            { language: 'eml' },
            lensProvider,
        ),
    );

    const diagnostics = new ChainOrderDiagnostics();
    context.subscriptions.push(diagnostics);

    const fpgaStatus = new FpgaStatusBarItem();
    context.subscriptions.push(fpgaStatus);

    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument((doc) => {
            if (doc.languageId === 'eml') {
                diagnostics.refresh(doc);
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

    // Commands users can invoke from the palette.
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'monogate-forge.profile',
            () => lensProvider.refresh(),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.pick',
            () => compileToPicker(),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.c',       () => compileTo('c')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.rust',    () => compileTo('rust')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.python',  () => compileTo('python')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.llvm',    () => compileTo('llvm')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.wasm',    () => compileTo('wasm')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.verilog', () => compileTo('verilog')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.vhdl',    () => compileTo('vhdl')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.chisel',  () => compileTo('chisel')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.lean',    () => compileTo('lean')),
        vscode.commands.registerCommand(
            'monogate-forge.compile.all',     () => compileTo('all')),
    );

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
    const terminal = vscode.window.createTerminal({
        name: `eml-compile --target ${target}`,
    });
    terminal.show();
    terminal.sendText(
        `python tools/cli/main.py "${sourcePath}" --target ${target}`,
    );
}


/**
 * format-on-save / explicit format provider.
 *
 * Shells out to `python tools/cli/main.py <file> --fmt` and replaces
 * the entire document with the canonical output. Save-after-format is
 * handled by VS Code automatically.
 */
class EmlFormattingProvider implements vscode.DocumentFormattingEditProvider {
    public provideDocumentFormattingEdits(
        document: vscode.TextDocument,
    ): vscode.ProviderResult<vscode.TextEdit[]> {
        return new Promise((resolve) => {
            const cli = pythonCli();
            const repoRoot = workspaceRoot();
            cp.execFile(
                cli,
                ['tools/cli/main.py', document.uri.fsPath, '--fmt'],
                { cwd: repoRoot, encoding: 'utf-8', maxBuffer: 16 * 1024 * 1024 },
                (err, stdout) => {
                    if (err) {
                        // Surface the error in the output channel; don't
                        // mangle the document.
                        const out = vscode.window.createOutputChannel(
                            'Monogate Forge'
                        );
                        out.appendLine(`fmt error: ${err.message}`);
                        out.show(true);
                        resolve([]);
                        return;
                    }
                    const fullRange = new vscode.Range(
                        document.positionAt(0),
                        document.positionAt(document.getText().length),
                    );
                    resolve([vscode.TextEdit.replace(fullRange, stdout)]);
                },
            );
        });
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

    public refresh(doc: vscode.TextDocument): void {
        if (doc.languageId !== 'eml') {
            this.item.hide();
            return;
        }
        const cli = pythonCli();
        const repoRoot = workspaceRoot();
        const target = vscode.workspace
            .getConfiguration('eml.fpga')
            .get<string>('target', 'xilinx.artix7');

        const myToken = ++this.inflight;
        cp.execFile(
            cli,
            ['tools/cli/main.py', doc.uri.fsPath, '--allocate',
             '--fpga-target', target],
            { cwd: repoRoot, encoding: 'utf-8', maxBuffer: 4 * 1024 * 1024 },
            (err, stdout) => {
                if (myToken !== this.inflight) {
                    return;
                }
                if (err) {
                    this.item.hide();
                    return;
                }
                const summary = parseAllocationSummary(stdout);
                if (!summary) {
                    this.item.hide();
                    return;
                }
                this.item.text =
                    `$(circuit-board) ${summary.luts} LUT  ` +
                    `${summary.dsps} DSP  ${summary.cycles} cy`;
                this.item.tooltip =
                    `FPGA target: ${target}\n${stdout}`;
                this.item.show();
            },
        );
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


function pythonCli(): string {
    return vscode.workspace
        .getConfiguration('eml.compile')
        .get<string>('python', 'python');
}

function workspaceRoot(): string {
    const ws = vscode.workspace.workspaceFolders;
    if (ws && ws.length > 0) {
        return ws[0].uri.fsPath;
    }
    // Fallback: use the directory of the active editor.
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        return path.dirname(editor.document.uri.fsPath);
    }
    return process.cwd();
}
