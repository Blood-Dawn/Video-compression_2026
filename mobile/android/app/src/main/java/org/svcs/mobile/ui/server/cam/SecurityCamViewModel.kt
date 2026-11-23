package org.svcs.mobile.ui.server.cam

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.work.WorkInfo
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.SecurityCamInfo
import org.svcs.mobile.net.SvcsApiClient
import org.svcs.mobile.securitycam.ClipCounts

data class SecurityCamUiState(
    /** What the desktop says; null until the first answer. */
    val info: SecurityCamInfo? = null,
    val counts: ClipCounts = ClipCounts(),
    /** Null when the desktop answered; otherwise why it did not. */
    val linkError: String? = null,
)

/**
 * Keeps the Security cam screen in step with the desktop (clip length, mode,
 * clips it has already compressed) and with the phone's own upload queue.
 * Polls like the METRICS tab: a read-only GET every few seconds, stopped when
 * the ViewModel is cleared.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, roadmap 13.1).
 */
class SecurityCamViewModel(
    private val api: SvcsApiClient?,
    private val workStates: Flow<List<WorkInfo.State>>,
) : ViewModel() {

    private companion object { const val POLL_MS = 4000L }

    private val _state = MutableStateFlow(SecurityCamUiState())
    val state: StateFlow<SecurityCamUiState> = _state.asStateFlow()

    private var started = false

    fun start() {
        if (started) return
        started = true
        viewModelScope.launch {
            workStates.collect { states ->
                _state.update { it.copy(counts = ClipCounts.from(states)) }
            }
        }
        val client = api ?: run {
            _state.update { it.copy(linkError = "Not paired with a server yet.") }
            return
        }
        viewModelScope.launch {
            while (isActive) {
                val result = withContext(Dispatchers.IO) { client.securityCam() }
                _state.update { s ->
                    when (result) {
                        is Fetched.Ok -> s.copy(info = result.value, linkError = null)
                        Fetched.Unauthorized -> s.copy(
                            linkError = "The server rejected this device's token. Re-pair under MORE.")
                        is Fetched.Failed -> s.copy(
                            linkError = "Could not reach the desktop. ${result.detail}")
                    }
                }
                delay(POLL_MS)
            }
        }
    }
}

/** "10 min", "30 min", "90 s": the clip length as a person says it. */
fun clipLengthLabel(seconds: Int): String = when {
    seconds >= 60 && seconds % 60 == 0 -> "${seconds / 60} min"
    else -> "$seconds s"
}

/** "9:41" style countdown for the current clip. */
fun countdownLabel(seconds: Int): String = "%d:%02d".format(seconds / 60, seconds % 60)
