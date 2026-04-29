/**
 * CodeLens provider that decorates each `fn` header in an `.eml`
 * file with the function's profile (chain order, cost class,
 * FPGA estimate, drift risk).
 *
 * Implementation: shells out to `python tools/cli/main.py FILE
 * --profile-only`, parses the per-function dashboard, matches
 * each block against the corresponding `fn NAME` line in the
 * editor.
 *
 * Result: above every `fn` header you see a one-line lens like
 *
 *   chain_order=2  p2-d4-w2-c0  4 MAC + 1 trig (8cy @ 32-bit)  drift=MEDIUM
 */

import * as vscode from 'vscode';
import { promisify } from 'util';
import { exec as _exec } from 'child_process';
import * as path from 'path';

const exec = promisify(_exec);


interface FnProfile {
    name: string;
    chainOrder: number | string;
    costClass: string;
    eml_depth: number | string;
    drift: string;
    macUnits: number;
    expUnits: number;
    lnUnits: number;
    trigUnits: number;
    latencyCycles: number;
    precisionBits: number;
    status: string;
}


export class ProfileLensProvider implements vscode.CodeLensProvider {
    private _onDidChange = new vscode.EventEmitter<void>();
    public readonly onDidChangeCodeLenses = this._onDidChange.event;

    refresh(): void {
        this._onDidChange.fire();
    }

    async provideCodeLenses(
        document: vscode.TextDocument,
        _token: vscode.CancellationToken,
    ): Promise<vscode.CodeLens[]> {
        if (document.languageId !== 'eml') {
            return [];
        }
        const profiles = await this.runProfiler(document.uri.fsPath);
        if (profiles === null) {
            return [];
        }
        const profileByName = new Map<string, FnProfile>();
        for (const p of profiles) {
            profileByName.set(p.name, p);
        }

        // Walk lines looking for `fn NAME(...)` headers and emit a
        // CodeLens per match.
        const lenses: vscode.CodeLens[] = [];
        const fnRegex = /^\s*(?:@\w+\([^)]*\)\s*)*\s*fn\s+([A-Za-z_][\w]*)\s*\(/;
        for (let line = 0; line < document.lineCount; line++) {
            const text = document.lineAt(line).text;
            const m = fnRegex.exec(text);
            if (!m) continue;
            const fnName = m[1];
            const profile = profileByName.get(fnName);
            if (!profile) continue;
            const range = new vscode.Range(line, 0, line, text.length);
            const title = renderProfileLensTitle(profile);
            lenses.push(new vscode.CodeLens(range, {
                title,
                command: '',  // No-op click; the lens is just info.
                arguments: [],
            }));
        }
        return lenses;
    }

    private async runProfiler(filePath: string): Promise<FnProfile[] | null> {
        const repoRoot = findRepoRoot(filePath);
        if (!repoRoot) return null;
        try {
            const { stdout } = await exec(
                `python tools/cli/main.py "${filePath}" --profile-only`,
                { cwd: repoRoot, timeout: 10000 },
            );
            return parseProfileOutput(stdout);
        } catch (e) {
            // Profiler failed (parse error in source, etc.). Surface
            // nothing -- the diagnostics provider handles errors.
            return null;
        }
    }
}


function renderProfileLensTitle(p: FnProfile): string {
    if (p.status === 'complex_body') {
        return `[complex body — Phase 2 will analyze]`;
    }
    if (p.status !== 'ok' && p.status !== 'tuple') {
        return `[${p.status}]`;
    }
    const fpgaPart = (
        `${p.macUnits} MAC` +
        (p.expUnits > 0 ? ` + ${p.expUnits} exp` : '') +
        (p.lnUnits > 0 ? ` + ${p.lnUnits} ln` : '') +
        (p.trigUnits > 0 ? ` + ${p.trigUnits} trig` : '')
    );
    return (
        `chain_order=${p.chainOrder}  ${p.costClass}  ` +
        `${fpgaPart} (${p.latencyCycles}cy @ ${p.precisionBits}-bit)  ` +
        `drift=${p.drift}`
    );
}


/**
 * Parse the dashboard format emitted by `python tools/cli/main.py
 * FILE --profile-only`. Returns one FnProfile per parsed function,
 * or [] if the output didn't parse.
 */
export function parseProfileOutput(stdout: string): FnProfile[] {
    const profiles: FnProfile[] = [];
    let current: Partial<FnProfile> | null = null;

    const lines = stdout.split('\n');
    for (const line of lines) {
        // A function header is two leading spaces + the name.
        // (The dashboard prefixes "  ", "    ", "    " for the
        // three lines per function.)
        const headerMatch = /^  ([A-Za-z_][\w]*)\s*$/.exec(line);
        if (headerMatch) {
            if (current && current.name) {
                profiles.push(fillDefaults(current));
            }
            current = { name: headerMatch[1] };
            continue;
        }
        if (!current) continue;

        const statusMatch = /status:\s*(\S+)/.exec(line);
        if (statusMatch) current.status = statusMatch[1];

        const coMatch = /chain_order:\s*(-?\d+)/.exec(line);
        if (coMatch) current.chainOrder = parseInt(coMatch[1], 10);

        const ccMatch = /cost_class:\s*(\S+)/.exec(line);
        if (ccMatch) current.costClass = ccMatch[1].replace(/,$/, '');

        const depthMatch = /eml_depth:\s*(\d+)/.exec(line);
        if (depthMatch) current.eml_depth = parseInt(depthMatch[1], 10);

        const driftMatch = /drift:\s*(\w+)/.exec(line);
        if (driftMatch) current.drift = driftMatch[1];

        const fpgaMatch = (
            /(\d+)\s+MAC,\s*(\d+)\s+exp,\s*(\d+)\s+ln,\s*(\d+)\s+trig\s+\((\d+)\s+cy\s+@\s+(\d+)-bit\)/
        ).exec(line);
        if (fpgaMatch) {
            current.macUnits = parseInt(fpgaMatch[1], 10);
            current.expUnits = parseInt(fpgaMatch[2], 10);
            current.lnUnits = parseInt(fpgaMatch[3], 10);
            current.trigUnits = parseInt(fpgaMatch[4], 10);
            current.latencyCycles = parseInt(fpgaMatch[5], 10);
            current.precisionBits = parseInt(fpgaMatch[6], 10);
        }
    }
    if (current && current.name) {
        profiles.push(fillDefaults(current));
    }
    return profiles;
}


function fillDefaults(p: Partial<FnProfile>): FnProfile {
    return {
        name: p.name ?? '?',
        chainOrder: p.chainOrder ?? '?',
        costClass: p.costClass ?? '?',
        eml_depth: p.eml_depth ?? '?',
        drift: p.drift ?? '?',
        macUnits: p.macUnits ?? 0,
        expUnits: p.expUnits ?? 0,
        lnUnits: p.lnUnits ?? 0,
        trigUnits: p.trigUnits ?? 0,
        latencyCycles: p.latencyCycles ?? 0,
        precisionBits: p.precisionBits ?? 32,
        status: p.status ?? 'unknown',
    };
}


/**
 * Walk up from `filePath` looking for the monogate-forge repo
 * root (identified by `tools/cli/main.py` + `lang/spec/SPEC.md`).
 * Returns null when no repo found within 8 ancestor levels.
 */
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
