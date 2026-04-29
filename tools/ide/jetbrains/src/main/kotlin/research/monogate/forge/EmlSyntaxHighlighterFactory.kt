package research.monogate.forge

import com.intellij.lexer.Lexer
import com.intellij.openapi.editor.colors.TextAttributesKey
import com.intellij.openapi.editor.colors.TextAttributesKey.createTextAttributesKey
import com.intellij.openapi.editor.DefaultLanguageHighlighterColors as Defaults
import com.intellij.openapi.fileTypes.SyntaxHighlighter
import com.intellij.openapi.fileTypes.SyntaxHighlighterBase
import com.intellij.openapi.fileTypes.SyntaxHighlighterFactory
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.tree.IElementType

/**
 * Light-touch syntax highlighter that re-uses the existing TextMate
 * grammar shipped with the VS Code extension. Until the JetBrains-side
 * lexer is grammar-driven, we expose a tiny set of token-class colors
 * so the editor doesn't render plain black.
 */
class EmlSyntaxHighlighterFactory : SyntaxHighlighterFactory() {
    override fun getSyntaxHighlighter(
        project: Project?,
        virtualFile: VirtualFile?,
    ): SyntaxHighlighter = EmlSyntaxHighlighter
}

object EmlSyntaxHighlighter : SyntaxHighlighterBase() {
    val KEYWORD: TextAttributesKey =
        createTextAttributesKey("EML_KEYWORD", Defaults.KEYWORD)
    val NUMBER: TextAttributesKey =
        createTextAttributesKey("EML_NUMBER", Defaults.NUMBER)
    val STRING: TextAttributesKey =
        createTextAttributesKey("EML_STRING", Defaults.STRING)
    val COMMENT: TextAttributesKey =
        createTextAttributesKey("EML_COMMENT", Defaults.LINE_COMMENT)
    val ANNOTATION: TextAttributesKey =
        createTextAttributesKey("EML_ANNOTATION", Defaults.METADATA)
    val BUILTIN: TextAttributesKey =
        createTextAttributesKey("EML_BUILTIN", Defaults.STATIC_FIELD)

    override fun getHighlightingLexer(): Lexer =
        // Real lexer lands when the JetBrains parser is wired (post-0.1).
        // Until then, the stub lexer returns a single token for the
        // entire file -- the editor still shows plain text.
        EmlStubLexer

    override fun getTokenHighlights(tokenType: IElementType?): Array<TextAttributesKey> =
        emptyArray()
}
