/**
 * Free-tier editor providers -- work without the Forge CLI.
 *
 * The marketplace extension stays fully functional for *writing*
 * EML even when the licensed CLI isn't installed. These providers
 * give users:
 *   - keyword + builtin completion (static list)
 *   - document symbols / outline (regex-based)
 *
 * They register only when the LSP hasn't started (so we never
 * duplicate the richer LSP results when the CLI is present).
 */

import * as vscode from 'vscode';


// Static list mirrors lang/parser/lexer.py KEYWORDS and
// lang/parser/ast_nodes.py BUILTIN_NAMES. Kept in lock-step
// manually -- the LSP sources these from the parser at runtime,
// but the editor-only path can't import from Python.
const KEYWORDS: ReadonlyArray<string> = [
    'module', 'import', 'use', 'as',
    'const', 'type', 'fn', 'extern', 'let', 'mut', 'while', 'where',
    'domain', 'precision', 'chain_order', 'requires', 'ensures',
    'return', 'if', 'else', 'true', 'false',
    'Real', 'f64', 'f32', 'f16', 'bf16',
    'u8', 'u16', 'u32', 'u64', 'i8', 'i16', 'i32', 'i64',
    'bool', 'void', 'fixed',
];

const BUILTINS: ReadonlyArray<string> = [
    'exp', 'ln', 'sin', 'cos', 'tan', 'sqrt', 'pow', 'eml',
    'abs', 'clamp', 'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh',
];


export class StaticCompletionProvider implements vscode.CompletionItemProvider {
    public provideCompletionItems(
        _document: vscode.TextDocument,
        _position: vscode.Position,
    ): vscode.CompletionItem[] {
        const items: vscode.CompletionItem[] = [];
        for (const k of KEYWORDS) {
            const item = new vscode.CompletionItem(
                k, vscode.CompletionItemKind.Keyword);
            item.detail = 'keyword';
            items.push(item);
        }
        for (const b of BUILTINS) {
            const item = new vscode.CompletionItem(
                b, vscode.CompletionItemKind.Function);
            item.detail = 'builtin';
            items.push(item);
        }
        return items;
    }
}


/**
 * Regex-based outline. Recognises top-level `fn`, `const`, `type`
 * declarations. Body content is ignored -- we don't try to parse
 * EML expressions in TypeScript; that's the LSP's job.
 *
 * Skips matches inside `// ...` line comments and `/* ... *\/`
 * block comments. Within-string false positives are rare enough
 * that we accept them rather than ship a stateful tokeniser.
 */
export class RegexDocumentSymbolProvider implements vscode.DocumentSymbolProvider {
    public provideDocumentSymbols(
        document: vscode.TextDocument,
    ): vscode.DocumentSymbol[] {
        const out: vscode.DocumentSymbol[] = [];
        const text = stripComments(document.getText());
        const lines = text.split(/\r?\n/);

        // Allow optional `@whatever(...)` annotations before fn.
        const fnRe = /^\s*(?:@\w+\([^)]*\)\s*)*\s*fn\s+([A-Za-z_][\w]*)\s*\(/;
        const constRe = /^\s*const\s+([A-Za-z_][\w]*)\s*:/;
        const typeRe = /^\s*type\s+([A-Za-z_][\w]*)\s*=/;

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            for (const [re, kind] of [
                [fnRe, vscode.SymbolKind.Function],
                [constRe, vscode.SymbolKind.Constant],
                [typeRe, vscode.SymbolKind.TypeParameter],
            ] as Array<[RegExp, vscode.SymbolKind]>) {
                const m = re.exec(line);
                if (!m) continue;
                const name = m[1];
                const col = line.indexOf(name);
                const range = new vscode.Range(i, col, i, col + name.length);
                out.push(new vscode.DocumentSymbol(
                    name, '', kind, range, range,
                ));
                break;  // one decl per line
            }
        }
        return out;
    }
}


/**
 * Strip line + block comments so the regex outliner doesn't pick
 * up `// fn foo` examples in user prose. Preserves line numbers
 * (replaces stripped content with spaces so character offsets
 * stay valid for any caller that maps regex output back to ranges).
 */
function stripComments(src: string): string {
    let out = '';
    let i = 0;
    const n = src.length;
    while (i < n) {
        // Block comment
        if (src[i] === '/' && src[i + 1] === '*') {
            const end = src.indexOf('*/', i + 2);
            const stop = end === -1 ? n : end + 2;
            // Replace with spaces, preserve newlines for line counts
            for (let j = i; j < stop; j++) {
                out += src[j] === '\n' ? '\n' : ' ';
            }
            i = stop;
            continue;
        }
        // Line comment
        if (src[i] === '/' && src[i + 1] === '/') {
            const end = src.indexOf('\n', i);
            const stop = end === -1 ? n : end;
            for (let j = i; j < stop; j++) out += ' ';
            i = stop;
            continue;
        }
        out += src[i];
        i++;
    }
    return out;
}
