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
 *   "Compile to..." picker  Single-target QuickPick across all 32
 *                           live backends, tagged [Free] / [Pro] in
 *                           the description so users see licensing
 *                           before they hit a token check.
 *
 *   "Compile to multiple    Multi-select QuickPick (canPickMany) for
 *    targets..."            shipping bundles like Unity (HLSL + C# +
 *                           WGSL) or Apple (Metal + Swift) in one go.
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
import {
    StaticCompletionProvider, RegexDocumentSymbolProvider,
} from './editorOnly';

type Tier = 'Free' | 'Pro' | 'Bulk';

interface Target {
    id: string;
    description: string;
    tier: Tier;
}

const ALL_TARGETS: ReadonlyArray<Target> = [
    // ────── Free tier (12) ──────
    // Software
    { id: 'c',             description: 'C99 source via libmonogate',            tier: 'Free' },
    { id: 'cpp',           description: 'C++17 source',                          tier: 'Free' },
    { id: 'rust',          description: 'Rust source via the monogate-sys crate',tier: 'Free' },
    { id: 'go',            description: 'Go source using math.* / gonum',        tier: 'Free' },
    { id: 'java',          description: 'Java source (java.lang.Math)',          tier: 'Free' },
    { id: 'kotlin',        description: 'Kotlin source (kotlin.math)',           tier: 'Free' },
    { id: 'csharp',        description: 'C# source (System.Math, Unity-ready)',  tier: 'Free' },
    { id: 'python',        description: 'Python module using math.*',            tier: 'Free' },
    { id: 'matlab',        description: 'MATLAB / Octave .m source',             tier: 'Free' },
    { id: 'javascript',    description: 'JavaScript ES2020+ (Node + browser)',   tier: 'Free' },
    { id: 'wasm',          description: 'WebAssembly bytecode',                  tier: 'Free' },
    // Verification (Free)
    { id: 'lean',          description: 'Lean 4 verification artifacts',         tier: 'Free' },

    // ────── Pro tier (20) ──────
    // Compiler IRs
    { id: 'llvm',          description: 'Portable LLVM IR',                      tier: 'Pro' },
    // Hardware
    { id: 'verilog',       description: 'Synthesizable Verilog (FPGA target)',   tier: 'Pro' },
    { id: 'systemverilog', description: 'SystemVerilog with assertions',         tier: 'Pro' },
    { id: 'vhdl',          description: 'VHDL-2008 (FPGA target)',               tier: 'Pro' },
    { id: 'chisel',        description: 'Chisel 3 / FIRRTL source',              tier: 'Pro' },
    // GPU shaders
    { id: 'hlsl',          description: 'HLSL — Unity / Unreal GPU shaders',     tier: 'Pro' },
    { id: 'glsl',          description: 'GLSL desktop — Godot / OpenGL',         tier: 'Pro' },
    { id: 'glsles',        description: 'GLSL ES — WebGL / mobile',              tier: 'Pro' },
    { id: 'wgsl',          description: 'WGSL — WebGPU / browser',               tier: 'Pro' },
    { id: 'metal',         description: 'Metal — Apple GPU (iOS / Mac)',         tier: 'Pro' },
    // Apple + game engines
    { id: 'swift',         description: 'Swift — iOS / macOS app code',          tier: 'Pro' },
    { id: 'gdscript',      description: 'GDScript — Godot 4.x game logic',       tier: 'Pro' },
    { id: 'luau',          description: 'Luau — Roblox game logic',              tier: 'Pro' },
    // Safety-critical / certification
    { id: 'ada',           description: 'Ada / SPARK 2014',                      tier: 'Pro' },
    { id: 'autosar',       description: 'AUTOSAR Classic (.arxml + C)',          tier: 'Pro' },
    { id: 'aadl',          description: 'AADL architecture model',               tier: 'Pro' },
    { id: 'ros2',          description: 'ROS 2 node skeleton',                   tier: 'Pro' },
    // Verification (Pro)
    { id: 'coq',           description: 'Coq / Rocq verification artifacts',     tier: 'Pro' },
    { id: 'isabelle',      description: 'Isabelle/HOL theory file',              tier: 'Pro' },
    // Smart contracts
    { id: 'solidity',      description: 'Solidity contract (PRBMath SD59x18)',   tier: 'Pro' },

    // ────── Bulk ──────
    { id: 'all',           description: 'All live backends in your tier; writes to source dir', tier: 'Bulk' },
];

export function activate(context: vscode.ExtensionContext): void {
    const lensProvider = new ProfileLensProvider();
    context.subscriptions.push(
        vscode.languages.registerCodeLensProvider(
            { language: 'eml' },
            lensProvider,
        ),
    );

    // Open core: the extension is fully usable for *writing*
    // EML without the licensed Forge CLI. When the LSP starts
    // (CLI installed), it owns diagnostics + completion + outline
    // and we skip the editor-only fallbacks. When the LSP isn't
    // available, register static-list completion and a regex
    // outliner so the user still gets keyword suggestions and
    // an outline view -- they just don't get type-aware analysis.
    const lsp = startLspClient(context);
    const diagnostics = lsp ? null : new ChainOrderDiagnostics();
    if (diagnostics) {
        context.subscriptions.push(diagnostics);
    }
    if (!lsp) {
        context.subscriptions.push(
            vscode.languages.registerCompletionItemProvider(
                { language: 'eml' },
                new StaticCompletionProvider(),
            ),
            vscode.languages.registerDocumentSymbolProvider(
                { language: 'eml' },
                new RegexDocumentSymbolProvider(),
            ),
        );
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

    // Format-on-save provider. The LSP owns formatting via
    // textDocument/formatting (in-process call to
    // tools.fmt.formatter); only register the legacy subprocess
    // path when the LSP isn't running.
    if (!lsp) {
        context.subscriptions.push(
            vscode.languages.registerDocumentFormattingEditProvider(
                'eml',
                new EmlFormattingProvider(),
            ),
        );
    }

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
        vscode.commands.registerCommand(
            'monogate-forge.compile.pickMany',
            () => compileToManyPicker(),
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

/**
 * Single-target picker. The QuickPick label is the bare target id
 * (so typing "metal" still matches), and the right-aligned detail
 * carries the tier badge -- separating these means matchOnDescription
 * stays useful for keyword search without leaking the badge into
 * fuzzy matching.
 */
async function compileToPicker(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'eml') {
        vscode.window.showErrorMessage(
            'monogate-forge: open a .eml file first',
        );
        return;
    }
    const pick = await vscode.window.showQuickPick(
        ALL_TARGETS.map(toQuickPickItem),
        {
            placeHolder: 'Pick a target for eml-compile --target ...',
            matchOnDescription: true,
            matchOnDetail: false,
        },
    );
    if (!pick) {
        return;
    }
    await compileTo(pick.label);
}

/**
 * Multi-target picker. Lets the user check several targets in one
 * shot -- useful for shipping bundles like Unity (HLSL + C# + WGSL)
 * or Apple (Metal + Swift). The bulk "all" entry is hidden here
 * because it has its own dedicated command.
 */
async function compileToManyPicker(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'eml') {
        vscode.window.showErrorMessage(
            'monogate-forge: open a .eml file first',
        );
        return;
    }
    const picks = await vscode.window.showQuickPick(
        ALL_TARGETS.filter((t) => t.tier !== 'Bulk').map(toQuickPickItem),
        {
            placeHolder: 'Pick one or more targets to compile...',
            canPickMany: true,
            matchOnDescription: true,
            matchOnDetail: false,
        },
    );
    if (!picks || picks.length === 0) {
        return;
    }
    // Sequential dispatch through the existing compileTo path. Each
    // target gets its own terminal (matching the single-target UX);
    // the user can collapse them after if the run is large.
    for (const pick of picks) {
        await compileTo(pick.label);
    }
}

function toQuickPickItem(t: Target): vscode.QuickPickItem {
    const badge = t.tier === 'Bulk' ? '· Bulk' : `· ${t.tier}`;
    return {
        label: t.id,
        description: `${t.description}  ${badge}`,
    };
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
