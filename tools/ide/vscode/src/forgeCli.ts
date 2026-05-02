/**
 * Resolves how to invoke the Monogate Forge CLI for the current
 * editing session. Two paths supported, in priority order:
 *
 *   1. `eml-compile` on PATH -- the published package
 *      (`pip install monogate-forge`). No forge clone needed.
 *
 *   2. `python tools/cli/main.py` from a forge checkout above
 *      the open .eml file. Used by contributors who edit inside
 *      the repo and want their unbuilt local changes to take
 *      effect.
 *
 * If neither resolves, the extension shows a one-shot info
 * message with the install command (suppressed for the rest of
 * the session so the user is not nagged on every save).
 *
 * Discovery is cached: PATH lookup runs once per process, repo
 * lookup is keyed by file path.
 */

import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';


export interface ForgeInvocation {
    /** The executable to spawn (e.g. "eml-compile" or "python"). */
    cmd: string;
    /** Argv prefix; the caller appends source path + flags. */
    args: string[];
    /** Working directory for the spawn. Repo root for in-clone
     *  invocation; the .eml's directory for the installed CLI. */
    cwd: string;
    /** "package" or "checkout" -- for telemetry / messaging. */
    source: 'package' | 'checkout';
}


let _cachedPackagePath: string | null | undefined; // undefined = unresolved
let _cachedLspPath: string | null | undefined;
let _shownMissingHint = false;
const OUTPUT = vscode.window.createOutputChannel('Monogate Forge');


/**
 * Resolve a Forge CLI invocation for the given .eml file.
 * Returns null when neither path resolves; the caller should
 * skip its work in that case (the user is shown an install hint
 * once per session).
 */
export function resolveForge(filePath: string): ForgeInvocation | null {
    // 1) Prefer the installed `eml-compile` binary -- it works
    //    from any directory and doesn't require a repo clone.
    const pkgPath = findPackageCli();
    if (pkgPath) {
        return {
            cmd: pkgPath,
            args: [],
            cwd: path.dirname(filePath),
            source: 'package',
        };
    }

    // 2) Fall back to in-clone invocation. Mostly for forge
    //    contributors editing the language itself.
    const repo = findRepoRoot(filePath);
    if (repo) {
        const python = vscode.workspace
            .getConfiguration('eml.compile')
            .get<string>('python', 'python');
        return {
            cmd: python,
            args: ['tools/cli/main.py'],
            cwd: repo,
            source: 'checkout',
        };
    }

    showMissingHintOnce();
    return null;
}


/**
 * Convenience: spawn a Forge invocation and resolve to its
 * stdout/stderr. Errors propagate so the caller can decide
 * whether to surface them.
 */
export function runForge(
    inv: ForgeInvocation,
    extraArgs: string[],
    timeoutMs = 10_000,
): Promise<{ stdout: string; stderr: string }> {
    return new Promise((resolve, reject) => {
        cp.execFile(
            inv.cmd,
            [...inv.args, ...extraArgs],
            { cwd: inv.cwd, timeout: timeoutMs, encoding: 'utf-8',
              maxBuffer: 16 * 1024 * 1024 },
            (err, stdout, stderr) => {
                if (err) {
                    // Attach stdout/stderr to the error so the
                    // caller can pull diagnostics out of failed runs.
                    (err as { stdout?: string }).stdout = stdout;
                    (err as { stderr?: string }).stderr = stderr;
                    reject(err);
                    return;
                }
                resolve({ stdout, stderr });
            },
        );
    });
}


function findPackageCli(): string | null {
    return _findOnPath('eml-compile', '_cachedPackagePath');
}


/**
 * Find the `eml-lsp` binary on PATH. Installed by
 * `pip install monogate-forge[lsp]` -- the LSP is opt-in
 * because pygls is a heavier dep than the rest of forge needs.
 */
export function findLspBinary(): string | null {
    return _findOnPath('eml-lsp', '_cachedLspPath');
}


function _findOnPath(name: string, cacheKey: '_cachedPackagePath' | '_cachedLspPath'): string | null {
    const cache = cacheKey === '_cachedPackagePath' ? _cachedPackagePath : _cachedLspPath;
    if (cache !== undefined) return cache;
    const lookup = process.platform === 'win32' ? 'where' : 'which';
    try {
        const out = cp.execFileSync(lookup, [name], {
            encoding: 'utf-8',
            timeout: 3000,
        }).trim();
        const first = out.split(/\r?\n/)[0].trim();
        if (first && fs.existsSync(first)) {
            if (cacheKey === '_cachedPackagePath') _cachedPackagePath = first;
            else _cachedLspPath = first;
            OUTPUT.appendLine(`${name}: ${first}`);
            return first;
        }
    } catch {
        // Not on PATH -- fall through.
    }
    if (cacheKey === '_cachedPackagePath') _cachedPackagePath = null;
    else _cachedLspPath = null;
    return null;
}


/**
 * Walk up from `filePath` looking for the monogate-forge repo
 * root (identified by `tools/cli/main.py` + `lang/spec/SPEC.md`).
 * Returns null when no repo found within 8 ancestor levels.
 */
function findRepoRoot(filePath: string): string | null {
    let dir = path.dirname(filePath);
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


function showMissingHintOnce(): void {
    if (_shownMissingHint) return;
    _shownMissingHint = true;
    const installCmd = 'pip install monogate-forge';
    vscode.window
        .showInformationMessage(
            'Monogate Forge CLI not found. Install with:  ' + installCmd,
            'Copy command', 'Open docs',
        )
        .then((choice) => {
            if (choice === 'Copy command') {
                vscode.env.clipboard.writeText(installCmd);
            } else if (choice === 'Open docs') {
                vscode.env.openExternal(
                    vscode.Uri.parse('https://monogate.dev/learn/eml'),
                );
            }
        });
}
