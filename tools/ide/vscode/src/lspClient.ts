/**
 * Spawns the `eml-lsp` server (from `pip install monogate-forge[lsp]`)
 * and connects VS Code to it via vscode-languageclient.
 *
 * The server speaks the standard LSP wire over stdio. When it's
 * available, it owns the diagnostics pipeline -- the legacy
 * save-triggered ChainOrderDiagnostics is suppressed in
 * extension.ts to avoid duplicate squiggles.
 *
 * When `eml-lsp` is NOT on PATH (the user installed
 * `pip install monogate-forge` without the `[lsp]` extra), this
 * module returns null and the extension falls back to the legacy
 * save-triggered diagnostics. No nag screen for missing LSP --
 * the install hint for the base CLI already covers discovery,
 * and the legacy path still works.
 */

import * as vscode from 'vscode';
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    TransportKind,
} from 'vscode-languageclient/node';
import { findLspBinary } from './forgeCli';


export function startLspClient(
    context: vscode.ExtensionContext,
): LanguageClient | null {
    const bin = findLspBinary();
    if (!bin) return null;

    const serverOptions: ServerOptions = {
        run:   { command: bin, transport: TransportKind.stdio },
        debug: { command: bin, transport: TransportKind.stdio },
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: 'file', language: 'eml' }],
        synchronize: {
            // Re-publish on changes to project-level config the
            // server doesn't yet read; reserved for a future
            // workspace-aware mode.
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.eml'),
        },
        outputChannelName: 'EML Language Server',
    };

    const client = new LanguageClient(
        'eml-lsp',
        'EML Language Server',
        serverOptions,
        clientOptions,
    );
    client.start();
    context.subscriptions.push({ dispose: () => client.stop() });
    return client;
}
