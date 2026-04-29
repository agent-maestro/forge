package research.monogate.forge

import com.intellij.lang.Language

/**
 * Marker class for the EML-lang [Language] registered with the IntelliJ
 * Platform. Used by parser definitions, syntax highlighters, and the
 * file type registration in `plugin.xml`.
 */
object EmlLanguage : Language("EML")
