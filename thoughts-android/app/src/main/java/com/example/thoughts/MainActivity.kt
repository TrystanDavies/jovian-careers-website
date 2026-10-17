package com.example.thoughts

import android.Manifest
import android.app.Application
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.SystemClock
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

// ---------------------------------------------------------------------------------------------
// Tunables
// ---------------------------------------------------------------------------------------------

/** How long the room must stay quiet (no new words recognised) before auto-save kicks in. */
private const val SILENCE_TIMEOUT_MS = 4_000L

/** Quiet time after which the "Auto-saving in Ns" countdown becomes visible. */
private const val SILENCE_HINT_AFTER_MS = 1_500L
private const val SILENCE_TICK_MS = 200L

/** Max time to wait for the recogniser's final result after tapping Save. */
private const val FINALIZE_TIMEOUT_MS = 1_500L

/** How long the "Saved" confirmation stays on screen before the app closes. */
private const val SAVED_SCREEN_DURATION_MS = 1_200L

private const val RESTART_DELAY_MS = 200L
private const val MAX_CONSECUTIVE_ERRORS = 6

private const val PREFS_NAME = "thoughts_prefs"
private const val PREF_AUTO_SAVE = "auto_save_on_silence"
private const val KEY_ASKED_RUNTIME = "asked_runtime_permissions"
private const val KEY_ASKED_ALL_FILES = "asked_all_files_access"

private const val THOUGHTS_FILE_NAME = "thoughts.md"
private const val THOUGHTS_DISPLAY_PATH = "Documents/$THOUGHTS_FILE_NAME"

// SpeechRecognizer error codes added in API 31, declared locally so they are safe on minSdk 26.
private const val ERROR_TOO_MANY_REQUESTS = 10
private const val ERROR_SERVER_DISCONNECTED = 11
private const val ERROR_LANGUAGE_NOT_SUPPORTED = 12
private const val ERROR_LANGUAGE_UNAVAILABLE = 13

private val TIMESTAMP_FORMAT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss", Locale.US)

// ---------------------------------------------------------------------------------------------
// Activity: permissions + lifecycle wiring
// ---------------------------------------------------------------------------------------------

class MainActivity : ComponentActivity() {

    private val viewModel: ThoughtsViewModel by viewModels()

    private var askedRuntimePermissions = false
    private var askedAllFilesAccess = false

    private val runtimePermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            runPermissionFlow()
        }

    private val allFilesAccessLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
            runPermissionFlow()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        askedRuntimePermissions = savedInstanceState?.getBoolean(KEY_ASKED_RUNTIME) ?: false
        askedAllFilesAccess = savedInstanceState?.getBoolean(KEY_ASKED_ALL_FILES) ?: false

        setContent {
            ThoughtsTheme {
                ThoughtsScreen(
                    state = viewModel.uiState,
                    micLevel = { viewModel.micLevel },
                    onAutoSaveChange = viewModel::setAutoSave,
                    onSave = viewModel::requestSave,
                    onGrantPermissions = ::onGrantPermissionsClicked,
                    onRetry = viewModel::retry,
                    onFinished = ::finishAndRemoveTask,
                )
            }
        }

        // Fresh launch (or restored after process death): check permissions, then start listening.
        if (viewModel.uiState.phase == Phase.CheckingPermissions) runPermissionFlow()
    }

    override fun onStart() {
        super.onStart()
        viewModel.onAppForegrounded()
    }

    override fun onResume() {
        super.onResume()
        // The user may have granted access manually in system settings and come back.
        if (viewModel.uiState.phase == Phase.NeedsPermissions &&
            missingRuntimePermissions().isEmpty() &&
            !needsAllFilesAccess()
        ) {
            viewModel.onPermissionsGranted()
        }
    }

    override fun onStop() {
        viewModel.onAppBackgrounded()
        super.onStop()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putBoolean(KEY_ASKED_RUNTIME, askedRuntimePermissions)
        outState.putBoolean(KEY_ASKED_ALL_FILES, askedAllFilesAccess)
    }

    /** Asks for each missing permission once, automatically, then hands over to the UI. */
    private fun runPermissionFlow() {
        val missing = missingRuntimePermissions()
        when {
            missing.isNotEmpty() && !askedRuntimePermissions -> {
                askedRuntimePermissions = true
                runtimePermissionLauncher.launch(missing.toTypedArray())
            }
            missing.isNotEmpty() -> viewModel.onPermissionsMissing(describeMissing(missing))
            needsAllFilesAccess() && !askedAllFilesAccess -> {
                askedAllFilesAccess = true
                openAllFilesAccessSettings()
            }
            needsAllFilesAccess() -> viewModel.onPermissionsMissing(allFilesMessage())
            else -> viewModel.onPermissionsGranted()
        }
    }

    /** "Grant access" button: re-asks if Android still allows it, otherwise opens Settings. */
    private fun onGrantPermissionsClicked() {
        val missing = missingRuntimePermissions()
        when {
            missing.isNotEmpty() && missing.all { shouldShowRequestPermissionRationale(it) } ->
                runtimePermissionLauncher.launch(missing.toTypedArray())
            missing.isNotEmpty() -> openAppSettings()
            needsAllFilesAccess() -> openAllFilesAccessSettings()
            else -> viewModel.onPermissionsGranted()
        }
    }

    private fun missingRuntimePermissions(): List<String> = buildList {
        if (!isGranted(Manifest.permission.RECORD_AUDIO)) add(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R &&
            !isGranted(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        ) {
            add(Manifest.permission.WRITE_EXTERNAL_STORAGE)
        }
    }

    private fun isGranted(permission: String): Boolean =
        checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED

    /** Android 11+ needs "All files access" to write a plain file into the shared Documents folder. */
    private fun needsAllFilesAccess(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()

    private fun describeMissing(missing: List<String>): String =
        if (Manifest.permission.RECORD_AUDIO in missing) {
            "Thoughts needs the microphone to hear you."
        } else {
            "Thoughts needs storage access to save $THOUGHTS_DISPLAY_PATH."
        }

    private fun allFilesMessage(): String =
        "Thoughts needs “All files access” to save $THOUGHTS_DISPLAY_PATH."

    private fun openAllFilesAccessSettings() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        val appScreen = Intent(
            Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
            Uri.fromParts("package", packageName, null),
        )
        try {
            allFilesAccessLauncher.launch(appScreen)
        } catch (e: ActivityNotFoundException) {
            try {
                allFilesAccessLauncher.launch(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            } catch (e2: ActivityNotFoundException) {
                viewModel.onPermissionsMissing(allFilesMessage())
            }
        }
    }

    private fun openAppSettings() {
        val intent = Intent(
            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.fromParts("package", packageName, null),
        )
        try {
            startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            startActivity(Intent(Settings.ACTION_SETTINGS))
        }
    }
}

// ---------------------------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------------------------

enum class Phase { CheckingPermissions, NeedsPermissions, Listening, Paused, Finalizing, Saving, Saved, Error }

data class UiState(
    val phase: Phase = Phase.CheckingPermissions,
    val committedText: String = "",
    val partialText: String = "",
    val autoSave: Boolean = true,
    val silenceCountdown: Int? = null,
    val message: String? = null,
) {
    val hasText: Boolean get() = committedText.isNotBlank() || partialText.isNotBlank()
}

// ---------------------------------------------------------------------------------------------
// ViewModel: continuous speech recognition, silence detection, saving
// ---------------------------------------------------------------------------------------------

class ThoughtsViewModel(application: Application) : AndroidViewModel(application) {

    private val app: Application = application
    private val prefs = application.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var uiState by mutableStateOf(UiState(autoSave = prefs.getBoolean(PREF_AUTO_SAVE, true)))
        private set

    /** Live microphone level from 0 to 1; only drives the pulse animation. */
    var micLevel by mutableFloatStateOf(0f)
        private set

    private var recognizer: SpeechRecognizer? = null
    private var inForeground = false
    private var startWhenForeground = false
    private var sessionToken = 0
    private var sessionOpen = false
    private var consecutiveErrors = 0
    private var lastSpeechAt = 0L
    private var restartJob: Job? = null
    private var silenceJob: Job? = null
    private var finalizeJob: Job? = null

    private val recognizerIntent: Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, application.packageName)
    }

    fun onPermissionsGranted() {
        val phase = uiState.phase
        if (phase != Phase.CheckingPermissions && phase != Phase.NeedsPermissions) return
        // Android only lets a visible app open the microphone, so wait for onStart if needed.
        if (inForeground) startListening() else startWhenForeground = true
    }

    fun onPermissionsMissing(reason: String) {
        val phase = uiState.phase
        if (phase == Phase.CheckingPermissions || phase == Phase.NeedsPermissions) {
            uiState = uiState.copy(phase = Phase.NeedsPermissions, message = reason)
        }
    }

    fun onAppForegrounded() {
        inForeground = true
        if (startWhenForeground || uiState.phase == Phase.Paused) {
            startWhenForeground = false
            startListening()
        }
    }

    fun onAppBackgrounded() {
        inForeground = false
        when (uiState.phase) {
            Phase.Listening -> {
                // Android blocks background microphone use, so pause and keep what we have.
                stopRecognition()
                commitPartial()
                uiState = uiState.copy(phase = Phase.Paused, silenceCountdown = null)
            }
            Phase.Finalizing -> persist()
            else -> Unit
        }
    }

    fun setAutoSave(enabled: Boolean) {
        prefs.edit().putBoolean(PREF_AUTO_SAVE, enabled).apply()
        lastSpeechAt = SystemClock.elapsedRealtime()
        uiState = uiState.copy(autoSave = enabled, silenceCountdown = null)
    }

    fun retry() {
        if (uiState.phase == Phase.Error) startListening()
    }

    fun requestSave() {
        when (uiState.phase) {
            Phase.Listening -> {
                if (sessionOpen && uiState.partialText.isNotBlank()) {
                    // Give the recogniser a moment to finalise the words in flight, but never wait long.
                    uiState = uiState.copy(phase = Phase.Finalizing, silenceCountdown = null)
                    restartJob?.cancel()
                    recognizer?.stopListening()
                    finalizeJob = viewModelScope.launch {
                        delay(FINALIZE_TIMEOUT_MS)
                        persist()
                    }
                } else {
                    persist()
                }
            }
            Phase.Paused, Phase.Error -> persist()
            else -> Unit
        }
    }

    private fun startListening() {
        if (!SpeechRecognizer.isRecognitionAvailable(app)) {
            fail("No speech recognition service found. Install or enable the Google app, then try again.")
            return
        }
        consecutiveErrors = 0
        lastSpeechAt = SystemClock.elapsedRealtime()
        uiState = uiState.copy(phase = Phase.Listening, message = null, silenceCountdown = null)
        startSilenceWatcher()
        beginSession()
    }

    /** One recogniser session lasts until the speaker pauses; we chain sessions back to back. */
    private fun beginSession() {
        if (uiState.phase != Phase.Listening) return
        val activeRecognizer = recognizer
            ?: SpeechRecognizer.createSpeechRecognizer(app).also { recognizer = it }
        val token = ++sessionToken
        sessionOpen = true
        activeRecognizer.setRecognitionListener(SessionListener(token))
        try {
            activeRecognizer.startListening(recognizerIntent)
        } catch (e: RuntimeException) {
            sessionOpen = false
            handleError(SpeechRecognizer.ERROR_CLIENT)
        }
    }

    private fun scheduleRestart(delayMs: Long, recreateRecognizer: Boolean = false) {
        restartJob?.cancel()
        restartJob = viewModelScope.launch {
            delay(delayMs)
            if (recreateRecognizer) destroyRecognizer()
            beginSession()
        }
    }

    private fun handleError(error: Int) {
        commitPartial()
        if (uiState.phase == Phase.Finalizing) {
            persist()
            return
        }
        if (uiState.phase != Phase.Listening) return
        when (error) {
            // Normal when nobody is talking: just listen again.
            SpeechRecognizer.ERROR_NO_MATCH,
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> scheduleRestart(RESTART_DELAY_MS)

            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
                fail("Microphone permission is missing. Close and reopen Thoughts to grant it.")

            ERROR_LANGUAGE_NOT_SUPPORTED,
            ERROR_LANGUAGE_UNAVAILABLE ->
                fail("Speech recognition isn't available for your phone's language. Check your voice input settings.")

            else -> {
                consecutiveErrors++
                if (consecutiveErrors > MAX_CONSECUTIVE_ERRORS) {
                    fail("Speech recognition keeps failing (${describeError(error)}).")
                } else {
                    val backoff = (300L shl (consecutiveErrors - 1)).coerceAtMost(4_000L)
                    scheduleRestart(backoff, recreateRecognizer = true)
                }
            }
        }
    }

    private fun startSilenceWatcher() {
        silenceJob?.cancel()
        silenceJob = viewModelScope.launch {
            while (true) {
                delay(SILENCE_TICK_MS)
                val state = uiState
                if (state.phase != Phase.Listening || !state.autoSave || !state.hasText) {
                    if (state.silenceCountdown != null) uiState = state.copy(silenceCountdown = null)
                    continue
                }
                val idle = SystemClock.elapsedRealtime() - lastSpeechAt
                if (idle >= SILENCE_TIMEOUT_MS) {
                    requestSave()
                    return@launch
                }
                val countdown = if (idle >= SILENCE_HINT_AFTER_MS) {
                    ((SILENCE_TIMEOUT_MS - idle + 999L) / 1000L).toInt()
                } else {
                    null
                }
                if (countdown != state.silenceCountdown) uiState = state.copy(silenceCountdown = countdown)
            }
        }
    }

    private fun persist() {
        val phase = uiState.phase
        if (phase == Phase.Saving || phase == Phase.Saved) return
        stopRecognition()
        silenceJob?.cancel()
        commitPartial()

        val text = uiState.committedText.trim()
        if (text.isEmpty()) {
            uiState = uiState.copy(phase = Phase.Saved, silenceCountdown = null, message = "Nothing to save")
            return
        }
        val entry = text.replaceFirstChar { it.titlecase(Locale.getDefault()) }
        val timestamp = LocalDateTime.now().format(TIMESTAMP_FORMAT)
        uiState = uiState.copy(phase = Phase.Saving, silenceCountdown = null, message = null)

        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { ThoughtsFile.append(entry, timestamp) }
            }
            uiState = result.fold(
                onSuccess = { uiState.copy(phase = Phase.Saved, message = "Saved to $THOUGHTS_DISPLAY_PATH") },
                onFailure = { uiState.copy(phase = Phase.Error, message = "Couldn't save: ${it.message ?: "unknown error"}") },
            )
        }
    }

    private fun fail(message: String) {
        stopRecognition()
        commitPartial()
        uiState = uiState.copy(phase = Phase.Error, message = message, silenceCountdown = null)
    }

    private fun commitPartial() {
        val partial = uiState.partialText
        if (partial.isNotEmpty()) {
            uiState = uiState.copy(committedText = joinText(uiState.committedText, partial), partialText = "")
        }
    }

    private fun stopRecognition() {
        restartJob?.cancel()
        finalizeJob?.cancel()
        sessionOpen = false
        sessionToken++ // Ignore any late callbacks from the old session.
        destroyRecognizer()
        micLevel = 0f
    }

    private fun destroyRecognizer() {
        val old = recognizer ?: return
        recognizer = null
        // Some devices throw "Service not registered" if the service already went away.
        runCatching { old.destroy() }
    }

    override fun onCleared() {
        stopRecognition()
        super.onCleared()
    }

    private inner class SessionListener(private val token: Int) : RecognitionListener {

        private fun isCurrent(): Boolean = token == sessionToken && sessionOpen

        override fun onReadyForSpeech(params: Bundle?) = Unit

        override fun onBeginningOfSpeech() = Unit

        override fun onRmsChanged(rmsdB: Float) {
            if (isCurrent()) micLevel = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)
        }

        override fun onBufferReceived(buffer: ByteArray?) = Unit

        override fun onEndOfSpeech() {
            if (isCurrent()) micLevel = 0f
        }

        override fun onPartialResults(partialResults: Bundle?) {
            if (!isCurrent()) return
            val text = partialResults.firstResult() ?: return
            if (text.isEmpty() || text == uiState.partialText) return
            consecutiveErrors = 0
            lastSpeechAt = SystemClock.elapsedRealtime()
            uiState = uiState.copy(partialText = text, silenceCountdown = null)
        }

        override fun onResults(results: Bundle?) {
            if (!isCurrent()) return
            sessionOpen = false
            micLevel = 0f
            val text = results.firstResult()
            if (!text.isNullOrEmpty()) {
                consecutiveErrors = 0
                lastSpeechAt = SystemClock.elapsedRealtime()
                uiState = uiState.copy(
                    committedText = joinText(uiState.committedText, text),
                    partialText = "",
                )
            } else {
                commitPartial()
            }
            when (uiState.phase) {
                Phase.Finalizing -> persist()
                Phase.Listening -> scheduleRestart(RESTART_DELAY_MS)
                else -> Unit
            }
        }

        override fun onError(error: Int) {
            if (!isCurrent()) return
            sessionOpen = false
            micLevel = 0f
            handleError(error)
        }

        override fun onEvent(eventType: Int, params: Bundle?) = Unit
    }
}

private fun Bundle?.firstResult(): String? =
    this?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim()

private fun joinText(existing: String, addition: String): String {
    val clean = addition.trim()
    return when {
        clean.isEmpty() -> existing
        existing.isBlank() -> clean
        else -> "$existing $clean"
    }
}

private fun describeError(error: Int): String = when (error) {
    SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "network timeout"
    SpeechRecognizer.ERROR_NETWORK -> "network error"
    SpeechRecognizer.ERROR_AUDIO -> "audio recording error"
    SpeechRecognizer.ERROR_SERVER -> "server error"
    SpeechRecognizer.ERROR_CLIENT -> "client error"
    SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "recogniser busy"
    ERROR_TOO_MANY_REQUESTS -> "too many requests"
    ERROR_SERVER_DISCONNECTED -> "service disconnected"
    else -> "code $error"
}

// ---------------------------------------------------------------------------------------------
// Storage: append to /storage/emulated/0/Documents/thoughts.md
// ---------------------------------------------------------------------------------------------

object ThoughtsFile {

    @Suppress("DEPRECATION")
    private fun target(): File = File(
        Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS),
        THOUGHTS_FILE_NAME,
    )

    @Throws(IOException::class)
    fun append(text: String, timestamp: String) {
        val file = target()
        val dir = file.parentFile ?: throw IOException("Invalid storage path")
        if (!dir.exists() && !dir.mkdirs()) throw IOException("Could not create ${dir.absolutePath}")

        val isNew = !file.exists() || file.length() == 0L
        val entry = buildString {
            if (isNew) {
                append("# Thoughts\n\n")
            } else if (lastByteOf(file) != '\n'.code) {
                append('\n')
            }
            append("## ").append(timestamp).append('\n')
            append(text).append("\n\n")
        }

        FileOutputStream(file, true).use { out ->
            out.write(entry.toByteArray(Charsets.UTF_8))
            out.flush()
            out.fd.sync() // Make sure it is on disk before the app closes.
        }
    }

    private fun lastByteOf(file: File): Int = RandomAccessFile(file, "r").use { raf ->
        raf.seek(raf.length() - 1)
        raf.read()
    }
}

// ---------------------------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------------------------

private object Palette {
    val Background = Color(0xFF111316)
    val Card = Color(0xFF1A1D22)
    val Hairline = Color(0xFF272B32)
    val Raised = Color(0xFF23272E)
    val TextPrimary = Color(0xFFF2F4F7)
    val TextSecondary = Color(0xFF8B94A3)
    val Accent = Color(0xFF8AB4FF)
    val OnAccent = Color(0xFF0C1424)
    val Success = Color(0xFF7EE0B5)
    val Error = Color(0xFFFF8A80)
}

@Composable
private fun ThoughtsTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Palette.Accent,
            onPrimary = Palette.OnAccent,
            background = Palette.Background,
            onBackground = Palette.TextPrimary,
            surface = Palette.Card,
            onSurface = Palette.TextPrimary,
            surfaceVariant = Palette.Raised,
            onSurfaceVariant = Palette.TextSecondary,
            outline = Palette.Hairline,
            error = Palette.Error,
        ),
        content = content,
    )
}

// ---------------------------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------------------------

@Composable
private fun ThoughtsScreen(
    state: UiState,
    micLevel: () -> Float,
    onAutoSaveChange: (Boolean) -> Unit,
    onSave: () -> Unit,
    onGrantPermissions: () -> Unit,
    onRetry: () -> Unit,
    onFinished: () -> Unit,
) {
    val haptics = LocalHapticFeedback.current
    LaunchedEffect(state.phase) {
        if (state.phase == Phase.Saved) {
            haptics.performHapticFeedback(HapticFeedbackType.Confirm)
            delay(SAVED_SCREEN_DURATION_MS)
            onFinished()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Palette.Background),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .safeDrawingPadding(),
        ) {
            TopBar()
            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Spacer(Modifier.height(8.dp))
                MicPulse(
                    listening = state.phase == Phase.Listening,
                    saved = state.phase == Phase.Saved && state.hasText,
                    level = micLevel,
                )
                StatusLine(state = state, onRetry = onRetry)
                Spacer(Modifier.height(16.dp))
                TranscriptCard(
                    state = state,
                    onGrantPermissions = onGrantPermissions,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth(),
                )
                Spacer(Modifier.height(16.dp))
            }
            Controls(state = state, onAutoSaveChange = onAutoSaveChange, onSave = onSave)
        }
    }
}

@Composable
private fun TopBar() {
    Column(Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "Thoughts",
                color = Palette.TextPrimary,
                fontSize = 20.sp,
                fontWeight = FontWeight.Medium,
                letterSpacing = 0.5.sp,
            )
        }
        HorizontalDivider(thickness = 0.5.dp, color = Palette.Hairline)
    }
}

@Composable
private fun MicPulse(listening: Boolean, saved: Boolean, level: () -> Float) {
    val transition = rememberInfiniteTransition(label = "pulse")
    val wave by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(animation = tween(durationMillis = 2_400, easing = LinearEasing)),
        label = "wave",
    )
    val breath by transition.animateFloat(
        initialValue = 0.96f,
        targetValue = 1.04f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1_200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "breath",
    )
    val voice by animateFloatAsState(
        targetValue = if (listening) level() else 0f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioNoBouncy, stiffness = Spring.StiffnessMediumLow),
        label = "voice",
    )
    val ringsAlpha by animateFloatAsState(
        targetValue = if (listening) 1f else 0f,
        animationSpec = tween(durationMillis = 400),
        label = "rings",
    )
    val accent by animateColorAsState(
        targetValue = if (saved) Palette.Success else Palette.Accent,
        label = "accent",
    )
    val active = listening || saved

    Box(modifier = Modifier.size(220.dp), contentAlignment = Alignment.Center) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            if (ringsAlpha <= 0f) return@Canvas
            val core = 44.dp.toPx()
            val maxRadius = size.minDimension / 2f
            repeat(3) { i ->
                val progress = (wave + i / 3f) % 1f
                drawCircle(
                    color = accent.copy(alpha = (1f - progress) * 0.35f * ringsAlpha),
                    radius = core + (maxRadius - core) * progress,
                    style = Stroke(width = 1.5.dp.toPx()),
                )
            }
            // Soft glow that swells with your voice.
            drawCircle(
                color = accent.copy(alpha = (0.10f + 0.20f * voice) * ringsAlpha),
                radius = core * (1.3f + 0.7f * voice),
            )
        }
        Box(
            modifier = Modifier
                .size(88.dp)
                .graphicsLayer {
                    val s = if (listening) breath + 0.10f * voice else 1f
                    scaleX = s
                    scaleY = s
                }
                .clip(CircleShape)
                .background(if (active) accent else Palette.Raised),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = if (saved) CheckIcon else MicIcon,
                contentDescription = if (saved) "Saved" else "Microphone",
                tint = if (active) Palette.OnAccent else Palette.TextSecondary,
                modifier = Modifier.size(36.dp),
            )
        }
    }
}

@Composable
private fun StatusLine(state: UiState, onRetry: () -> Unit) {
    val text = when (state.phase) {
        Phase.CheckingPermissions -> "Getting ready…"
        Phase.NeedsPermissions -> "Waiting for permission"
        Phase.Listening -> state.silenceCountdown?.let { "Auto-saving in ${it}s…" } ?: "Listening…"
        Phase.Paused -> "Paused"
        Phase.Finalizing, Phase.Saving -> "Saving…"
        Phase.Saved -> state.message ?: "Saved"
        Phase.Error -> state.message ?: "Something went wrong"
    }
    val color = when (state.phase) {
        Phase.Saved -> Palette.Success
        Phase.Error -> Palette.Error
        else -> Palette.TextSecondary
    }
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Crossfade(targetState = text, label = "status") { label ->
            Text(
                text = label,
                color = color,
                fontSize = 14.sp,
                letterSpacing = 0.3.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (state.phase == Phase.Error) {
            TextButton(onClick = onRetry) {
                Text(text = "Try again", color = Palette.Accent)
            }
        }
    }
}

@Composable
private fun TranscriptCard(state: UiState, onGrantPermissions: () -> Unit, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(24.dp),
        color = Palette.Card,
        border = BorderStroke(1.dp, Palette.Hairline),
    ) {
        if (state.phase == Phase.NeedsPermissions) {
            PermissionPrompt(
                message = state.message ?: "Thoughts needs a couple of permissions to work.",
                onGrant = onGrantPermissions,
            )
        } else {
            TranscriptText(committed = state.committedText, partial = state.partialText)
        }
    }
}

@Composable
private fun TranscriptText(committed: String, partial: String) {
    val scroll = rememberScrollState()
    // Keep the newest words in view as the transcript grows.
    LaunchedEffect(scroll) {
        snapshotFlow { scroll.maxValue }.collectLatest { scroll.animateScrollTo(it) }
    }
    Box(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(24.dp),
    ) {
        if (committed.isBlank() && partial.isBlank()) {
            Text(
                text = "Start speaking…",
                color = Palette.TextSecondary.copy(alpha = 0.6f),
                fontSize = 20.sp,
                lineHeight = 30.sp,
            )
        } else {
            Text(
                text = buildAnnotatedString {
                    append(committed)
                    if (partial.isNotBlank()) {
                        if (committed.isNotBlank()) append(' ')
                        // Words still being recognised are slightly dimmer.
                        withStyle(SpanStyle(color = Palette.TextPrimary.copy(alpha = 0.55f))) { append(partial) }
                    }
                },
                color = Palette.TextPrimary,
                fontSize = 20.sp,
                lineHeight = 30.sp,
            )
        }
    }
}

@Composable
private fun PermissionPrompt(message: String, onGrant: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = message,
            color = Palette.TextPrimary,
            fontSize = 18.sp,
            lineHeight = 26.sp,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(20.dp))
        OutlinedButton(
            onClick = onGrant,
            shape = RoundedCornerShape(14.dp),
            border = BorderStroke(1.dp, Palette.Accent),
        ) {
            Text(text = "Grant access", color = Palette.Accent)
        }
    }
}

@Composable
private fun Controls(state: UiState, onAutoSaveChange: (Boolean) -> Unit, onSave: () -> Unit) {
    val canSave = state.phase == Phase.Listening || state.phase == Phase.Paused || state.phase == Phase.Error
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 20.dp, end = 20.dp, bottom = 16.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = "Auto-save on silence", color = Palette.TextPrimary.copy(alpha = 0.9f), fontSize = 15.sp)
                Text(
                    text = "Saves after ${SILENCE_TIMEOUT_MS / 1000}s of quiet",
                    color = Palette.TextSecondary,
                    fontSize = 12.sp,
                )
            }
            Switch(
                checked = state.autoSave,
                onCheckedChange = onAutoSaveChange,
                modifier = Modifier.scale(0.85f),
                colors = SwitchDefaults.colors(
                    checkedThumbColor = Palette.OnAccent,
                    checkedTrackColor = Palette.Accent,
                    checkedBorderColor = Palette.Accent,
                    uncheckedThumbColor = Palette.TextSecondary,
                    uncheckedTrackColor = Palette.Raised,
                    uncheckedBorderColor = Palette.Hairline,
                ),
            )
        }
        Spacer(Modifier.height(14.dp))
        Button(
            onClick = onSave,
            enabled = canSave,
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp),
            shape = RoundedCornerShape(18.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = Palette.Accent,
                contentColor = Palette.OnAccent,
                disabledContainerColor = Palette.Raised,
                disabledContentColor = Palette.TextSecondary,
            ),
        ) {
            Text(text = "Done  ·  Save", fontSize = 16.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.3.sp)
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Icons (Material "mic" and "check" paths, so no icon library is needed)
// ---------------------------------------------------------------------------------------------

private val MicIcon: ImageVector by lazy {
    ImageVector.Builder(
        name = "Mic",
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).addPath(
        pathData = addPathNodes(
            "M12,14c1.66,0 2.99,-1.34 2.99,-3L15,5c0,-1.66 -1.34,-3 -3,-3S9,3.34 9,5v6c0,1.66 1.34,3 3,3z" +
                "M17.3,11c0,3 -2.54,5.1 -5.3,5.1S6.7,14 6.7,11L5,11c0,3.41 2.72,6.23 6,6.72L11,21h2v-3.28" +
                "c3.28,-0.48 6,-3.3 6,-6.72h-1.7z",
        ),
        fill = SolidColor(Color.Black),
    ).build()
}

private val CheckIcon: ImageVector by lazy {
    ImageVector.Builder(
        name = "Check",
        defaultWidth = 24.dp,
        defaultHeight = 24.dp,
        viewportWidth = 24f,
        viewportHeight = 24f,
    ).addPath(
        pathData = addPathNodes("M9,16.17L4.83,12l-1.42,1.41L9,19 21,7l-1.41,-1.41z"),
        fill = SolidColor(Color.Black),
    ).build()
}
