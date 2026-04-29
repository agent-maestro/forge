// Gradle build for the IntelliJ Platform plugin "Monogate Forge".
//
// Run:
//
//     ./gradlew buildPlugin            -- produces build/distributions/*.zip
//     ./gradlew runIde                 -- spawns a sandbox IDE
//
// The plugin targets IntelliJ IDEA + every Platform-based IDE (CLion,
// PyCharm, GoLand, RustRover, WebStorm, Rider, Android Studio).

plugins {
    id("java")
    id("org.jetbrains.kotlin.jvm") version "1.9.0"
    id("org.jetbrains.intellij") version "1.17.0"
}

group = "research.monogate"
version = "0.1.0"

repositories {
    mavenCentral()
}

intellij {
    version.set("2024.1")
    type.set("IC")  // IntelliJ Community
    plugins.set(listOf<String>())
}

tasks {
    withType<JavaCompile> {
        sourceCompatibility = "17"
        targetCompatibility = "17"
    }
    patchPluginXml {
        sinceBuild.set("241")
        untilBuild.set("251.*")
    }
    runIde {
        // Pass through the developer's PATH so `python tools/cli/main.py`
        // resolves the same way in the sandbox.
        environment("PATH", System.getenv("PATH") ?: "")
    }
}
