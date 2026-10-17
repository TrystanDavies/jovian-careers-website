// Top-level build file.
// AGP 9 compiles Kotlin itself ("built-in Kotlin"), so there is no org.jetbrains.kotlin.android plugin.
// The Compose compiler plugin version is the Kotlin version, and it lifts AGP's bundled Kotlin to match.
plugins {
    id("com.android.application") version "9.4.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.10" apply false
}
