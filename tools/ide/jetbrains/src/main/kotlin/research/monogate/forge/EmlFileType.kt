package research.monogate.forge

import com.intellij.openapi.fileTypes.LanguageFileType
import javax.swing.Icon

/**
 * Registers `*.eml` as the EML file type so the IDE associates the
 * language with our parser + highlighter.
 */
object EmlFileType : LanguageFileType(EmlLanguage) {
    override fun getName(): String = "EML File"
    override fun getDescription(): String = "Monogate Forge EML-lang source"
    override fun getDefaultExtension(): String = "eml"
    override fun getIcon(): Icon? = null
    @JvmField val INSTANCE: EmlFileType = this
}
