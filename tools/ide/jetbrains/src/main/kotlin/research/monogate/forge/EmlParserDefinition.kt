package research.monogate.forge

import com.intellij.lang.ASTNode
import com.intellij.lang.ParserDefinition
import com.intellij.lang.PsiParser
import com.intellij.lexer.Lexer
import com.intellij.openapi.project.Project
import com.intellij.psi.FileViewProvider
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiFile
import com.intellij.psi.PsiFileBase
import com.intellij.psi.tree.IFileElementType
import com.intellij.psi.tree.TokenSet

/**
 * Stub parser definition. Emits a single PSI element covering the whole
 * file so structure view / go-to-definition / find-usages all return
 * "no results" rather than crashing. Real parser lands in 0.2.
 */
class EmlParserDefinition : ParserDefinition {
    override fun createLexer(project: Project): Lexer = EmlStubLexer
    override fun createParser(project: Project): PsiParser =
        PsiParser { root, builder ->
            val rootMarker = builder.mark()
            while (!builder.eof()) {
                builder.advanceLexer()
            }
            rootMarker.done(root)
            builder.treeBuilt
        }
    override fun getFileNodeType(): IFileElementType = FILE
    override fun getCommentTokens(): TokenSet = TokenSet.EMPTY
    override fun getStringLiteralElements(): TokenSet = TokenSet.EMPTY
    override fun createElement(node: ASTNode): PsiElement {
        throw UnsupportedOperationException("EML parser stub")
    }
    override fun createFile(viewProvider: FileViewProvider): PsiFile =
        EmlFile(viewProvider)

    companion object {
        @JvmField
        val FILE: IFileElementType = IFileElementType(EmlLanguage)
    }
}

class EmlFile(viewProvider: FileViewProvider) :
    PsiFileBase(viewProvider, EmlLanguage) {
    override fun getFileType() = EmlFileType
}
