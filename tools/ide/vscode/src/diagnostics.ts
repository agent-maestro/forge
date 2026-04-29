/**
 * Diagnostics provider for chain-order type-check violations.
 *
 * Runs `python tools/cli/main.py FILE --profile-only` on save,
 * parses the output for "Type error" messages emitted by the
 * type checker, and surfaces them as VS Code diagnostics
 * (red squiggles + Problems-tab entries).
 *
 * Companion of profileProvider.ts. Both shell out to the same
 * Python CLI; together they make `.eml` files feel native in
 * VS Code without any TypeScript reimplementation of parsing.
 */

import * as vscode from 'vscode';
import { promisify } from 'util';
import { exec as _exec } from 'child_process';
import * as path from 'path';

const exec = promisify(_exec);


export class ChainOrderDiagnostics implements vscode.Disposable {
    private collection = vscode.languages.createDiagnosticCollection(
        'monogate-forge',
    );

    dispose(): void {
        this.collection.dispose();
    }

    async refresh(doc: vscode.TextDocument): Promise<void> {
        const repoRoot = findRepoRoot(doc.uri.fsPath);
        if (!repoRoot) {
            this.collection.set(doc.uri, []);
            return;
        }
        try {
            const { stderr } = await exec(
                `python tools/cli/main.py "${doc.uri.fsPath}" --profile-only`,
                { cwd: repoRoot, timeout: 10000 },
            );
            const diagnostics = parseDiagnostics(stderr, doc);
            this.collection.set(doc.uri, diagnostics);
        } catch (e) {
            // Surface the parse error itself as a single diagnostic.
            const stderr = (e as { stderr?: string }).stderr ?? '';
            const stdout = (e as { stdout?: string }).stdout ?? '';
            const combined = stderr + stdout;
            const diagnostics = parseDiagnostics(combined, doc);
            // Fallback: surface the raw error on line 0 if regex
            // didn't match anything.
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
    // Matches "FILE:LINE:COL: MESSAGE" -- the lexer/parser/type-checker
    // error format.
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


function findRepoRoot(filePath: string): string | null {
    let dir = path.dirname(filePath);
    const fs = require('fs') as typeof import('fs');
    for (let i = 0; i < 8; i++) {
        const cliPath = path.join(dir, 'tools', 'cli', 'main.py');
        const specPath = path.join(dir, 'lang', 'spec', 'SPEC.md');
        if (fs.existsSync(cliPath) && fs.existsSync(specPath)) {
            return dir;
        }
        const parent = path.dirname(dir);
        if (parent === dir) break;
        dir = parent;
    }
    return null;
}
