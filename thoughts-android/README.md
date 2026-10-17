# Thoughts

A single-purpose Android app: open it, speak, and your words are appended to
`Documents/thoughts.md` with a `YYYY-MM-DD HH:MM:SS` timestamp. Then it closes itself.

- Kotlin + Jetpack Compose, dark minimal UI
- Native `SpeechRecognizer`, chained sessions for continuous dictation
- "Done · Save" button, plus optional auto-save after 4 s of silence (toggle is remembered)

## Toolchain

| Piece | Version |
| --- | --- |
| Android Studio | Quail 4 (2026.1.4) or newer (Rabbit recommended) |
| Android Gradle plugin | 9.4.0 (built-in Kotlin) |
| Gradle | 9.6.0 (wrapper) |
| Kotlin / Compose compiler plugin | 2.4.10 |
| Compose BOM | 2026.09.00 |
| compileSdk / targetSdk / minSdk | 37 / 36 / 26 |

## Build and install

1. Android Studio: **File > Open** and select this `thoughts-android` folder. Let Gradle sync
   (accept any SDK Platform 37 download prompt).
2. On the phone: **Settings > About phone**, tap **Build number** seven times, then enable
   **Developer options > USB debugging** and plug the phone in.
3. Press **Run** to build and install in one step, or build an APK with
   **Build > Generate App Bundles or APKs > Generate APKs**
   (output: `app/build/outputs/apk/debug/app-debug.apk`), or from a terminal: `./gradlew assembleDebug`.
4. First launch: allow the microphone, then switch on **All files access** for Thoughts on the
   screen that opens, and go back. Later launches start listening straight away.

Installing with Android Studio or `adb install` is exempt from Android's developer-verification
requirement.
