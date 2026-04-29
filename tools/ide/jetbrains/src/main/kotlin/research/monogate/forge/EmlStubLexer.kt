package research.monogate.forge

import com.intellij.lexer.LexerBase
import com.intellij.psi.tree.IElementType

/**
 * Stub lexer used until the real grammar-driven lexer ships. Emits a
 * single `EML_TEXT` token covering the whole buffer -- the IDE still
 * recognizes the file as EML, just without per-token colorization.
 *
 * Replace with a JFlex / Grammar-Kit lexer in 0.2 to enable per-token
 * highlighting + parser-driven structure view.
 */
object EmlStubLexer : LexerBase() {
    private var buffer: CharSequence = ""
    private var bufferStart: Int = 0
    private var bufferEnd: Int = 0
    private var tokenStart: Int = 0
    private var done: Boolean = true

    override fun start(buffer: CharSequence, startOffset: Int, endOffset: Int, initialState: Int) {
        this.buffer = buffer
        this.bufferStart = startOffset
        this.bufferEnd = endOffset
        this.tokenStart = startOffset
        this.done = startOffset >= endOffset
    }

    override fun getState(): Int = 0
    override fun getTokenType(): IElementType? = if (done) null else TEXT
    override fun getTokenStart(): Int = tokenStart
    override fun getTokenEnd(): Int = bufferEnd
    override fun advance() { done = true }
    override fun getBufferSequence(): CharSequence = buffer
    override fun getBufferEnd(): Int = bufferEnd

    private val TEXT: IElementType = EmlElementType("EML_TEXT")
}

class EmlElementType(debugName: String) : IElementType(debugName, EmlLanguage)
