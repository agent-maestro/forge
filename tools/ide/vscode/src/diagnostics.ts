/**
 * Diagnostics provider for chain-order type-check violations.
 *
 * Runs the Forge CLI with `--profile-only` on save, parses the
 * output for "Type error" messages emitted by the type checker,
 * and surfaces them as VS Code diagnostics (red squiggles +
 * Problems-tab entries).
 *
 * Companion of profileProvider.ts. Both shell out via
 * forgeCli.resolveForge(), which prefers the installed
 * `eml-compile` binary and falls back to a forge clone.
 */

import * as vscode from 'vscode';
import { resolveForge, runForge } from './forgeCli';


export class ChainOrderDiagnostics implements vscode.Disposable {
    private collection = vscode.languages.createDiagnosticCollection(
        'monogate-forge',
    );

    dispose(): void {
        this.collection.dispose();
    }

    async refresh(doc: vscode.TextDocument): Promise<void> {
        const inv = resolveForge(doc.uri.fsPath);
        if (!inv) {
            this.collection.set(doc.uri, []);
            return;
        }
        try {
            const { stderr } = await runForge(inv, [
                doc.uri.fsPath, '--profile-only',
            ]);
            this.collection.set(doc.uri, parseDiagnostics(stderr, doc));
        } catch (e) {
            const stderr = (e as { stderr?: string }).stderr ?? '';
            const stdout = (e as { stdout?: string }).stdout ?? '';
            const combined = stderr + stdout;
            const diagnostics = parseDiagnostics(combined, doc);
            // Fallback: surface the raw error on line 0 if no
            // FILE:LINE:COL match was found.
            if (diagnostics.length === 0 && combined.trim()) {
                diagnostics.push(new vscode.Diagnostic(
                    new vscode.Range(0, 0, 0, 1),
                    `eml-compile error:\n${combined.trim().slice(0, 500)}`,
                    vscode.DiagnosticSeverity.Error,
                ));
            }
            this.collection.set(doc.uri, diagnostics);
        }
    }
}


/**
 * Parse the CLI's stderr/stdout for messages of the form
 *
 *   <file>:<line>:<col>: <message>
 *
 * and return one Diagnostic per match.
 */
export function parseDiagnostics(
    text: string,
    doc: vscode.TextDocument,
): vscode.Diagnostic[] {
    const diagnostics: vscode.Diagnostic[] = [];
    const errRegex = /^([^:\n]+):(\d+):(\d+):\s*(.+)$/gm;
    let m: RegExpExecArray | null;
    while ((m = errRegex.exec(text)) !== null) {
        const line = parseInt(m[2], 10) - 1;
        const col = parseInt(m[3], 10) - 1;
        const message = m[4];
        const range = new vscode.Range(
            line, col,
            line, Math.max(col + 1, doc.lineAt(
                Math.min(line, doc.lineCount - 1),
            ).text.length),
        );
        diagnostics.push(new vscode.Diagnostic(
            range, message, vscode.DiagnosticSeverity.Error,
        ));
    }
    return diagnostics;
}
