/**
 * Monogate Forge VS Code extension entry point.
 *
 * Registers two providers for `.eml` files:
 *
 *   ProfileLensProvider   CodeLens above each `fn` header showing
 *                         the inferred chain order, cost class,
 *                         and FPGA resource estimate. Invokes the
 *                         forge CLI's `--profile-only` mode.
 *
 *   ChainOrderDiagnostics On save, runs the profiler and surfaces
 *                         chain-order constraint violations as
 *                         VS Code diagnostics (red squiggles).
 *
 * The extension shells out to `python tools/cli/main.py` -- it
 * doesn't reimplement parsing in TypeScript. The Python CLI is
 * the source of truth.
 */

import * as vscode from 'vscode';
import { ProfileLensProvider } from './profileProvider';
import { ChainOrderDiagnostics } from './diagnostics';

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

    // Re-run diagnostics on save.
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument((doc) => {
            if (doc.languageId === 'eml') {
                diagnostics.refresh(doc);
                lensProvider.refresh();
            }
        }),
    );

    // Commands users can invoke from the palette.
    context.subscriptions.push(
        vscode.commands.registerCommand(
            'monogate-forge.profile',
            () => lensProvider.refresh(),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.c',
            () => compileTo('c'),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.rust',
            () => compileTo('rust'),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.lean',
            () => compileTo('lean'),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.verilog',
            () => compileTo('verilog'),
        ),
        vscode.commands.registerCommand(
            'monogate-forge.compile.all',
            () => compileTo('all'),
        ),
    );
}

export function deactivate(): void {
    // No cleanup needed; subscriptions clean up automatically.
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
    const cmd = (
        `python tools/cli/main.py "${sourcePath}" --target ${target}`
    );
    terminal.sendText(cmd);
}
