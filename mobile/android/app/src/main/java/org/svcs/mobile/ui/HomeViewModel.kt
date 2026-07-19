package org.svcs.mobile.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.SvcsApi

data class HomeState(
    val running: Boolean = false,
    val segmentCount: Long = 0,
    val frameCount: Long = 0,
    val progressPct: Double? = null,
    // Measured: real source-versus-output, the only honest ratio.
    val measuredFiles: Int = 0,
    val measuredSourceBytes: Long = 0,
    val measuredOutputBytes: Long = 0,
    val savedBytes: Long = 0,
    val ratio: Double? = null,
    // Recorded: totals only, no ratio (live capture has no source file).
    val recordedBytes: Long = 0,
    val recordedSegments: Int = 0,
    val error: String? = null,
)

/**
 * Polls /api/status and /api/savings for the HOME tab (M2.3).
 *
 * Faster than METRICS because this is where a running job's progress shows, and
 * a progress bar that updates every 4s reads as frozen.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2.3).
 */
class HomeViewModel(private val api: SvcsApi?) : ViewModel() {

    private companion object { const val POLL_MS = 2500L }

    private val _state = MutableStateFlow(HomeState())
    val state: StateFlow<HomeState> = _state.asStateFlow()
    private var started = false

    fun start() {
        if (started) return
        started = true
        val client = api ?: run {
            _state.update { it.copy(error = "Not paired with a server yet.") }
            return
        }
        viewModelScope.launch {
            while (isActive) {
                val status = withContext(Dispatchers.IO) { client.pipelineStatus() }
                val savings = withContext(Dispatchers.IO) { client.savings() }
                _state.update { s ->
                    var next = s.copy(error = null)
                    when (status) {
                        is Fetched.Ok -> next = next.copy(
                            running = status.value.running,
                            segmentCount = status.value.segmentCount,
                            frameCount = status.value.frameCount,
                            progressPct = status.value.progressPct,
                        )
                        Fetched.Unauthorized -> next = next.copy(
                            error = "The server rejected this device's token. " +
                                "Re-pair under MORE.")
                        is Fetched.Failed -> next = next.copy(
                            error = "Could not reach the server. ${status.detail}")
                    }
                    if (savings is Fetched.Ok) {
                        val m = savings.value.measured
                        val r = savings.value.recorded
                        next = next.copy(
                            measuredFiles = m.files,
                            measuredSourceBytes = m.sourceBytes,
                            measuredOutputBytes = m.outputBytes,
                            savedBytes = m.savedBytes,
                            ratio = m.ratio,
                            recordedBytes = r.outputBytes,
                            recordedSegments = r.segments,
                        )
                    }
                    next
                }
                delay(POLL_MS)
            }
        }
    }
}
