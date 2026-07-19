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

data class MetricsState(
    val cpuPct: Double? = null,
    val ramPct: Double? = null,
    val batteryPct: Double? = null,
    val running: Boolean = false,
    val storageHuman: String? = null,
    val segments: Int? = null,
    val hours: Double? = null,
    val withTargets: Int? = null,
    val error: String? = null,
)

/**
 * Polls the read-only metrics surfaces (M2.2).
 *
 * Polling, not SSE, on purpose. /api/logs is the only event stream and it is
 * destructive with more than one client (docs/MOBILE-ARCHITECTURE.md B11): each
 * log line reaches exactly one listener, so a phone attaching to it would steal
 * lines from the desktop dashboard. These endpoints are idempotent GETs that any
 * number of clients can poll safely.
 *
 * The loop stops when the ViewModel's scope is cancelled, so leaving the tab
 * stops the traffic rather than polling a LAN server from a backgrounded phone.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2.2).
 */
class MetricsViewModel(private val api: SvcsApi?) : ViewModel() {

    private companion object { const val POLL_MS = 4000L }

    private val _state = MutableStateFlow(MetricsState())
    val state: StateFlow<MetricsState> = _state.asStateFlow()

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
                val metrics = withContext(Dispatchers.IO) { client.systemMetrics() }
                val storage = withContext(Dispatchers.IO) { client.storageStats() }
                val status = withContext(Dispatchers.IO) { client.pipelineStatus() }

                _state.update { s ->
                    var next = s.copy(error = null)
                    when (metrics) {
                        is Fetched.Ok -> next = next.copy(
                            cpuPct = metrics.value.cpuPct,
                            ramPct = metrics.value.ramPct,
                            batteryPct = metrics.value.batteryPct,
                        )
                        Fetched.Unauthorized -> next = next.copy(
                            error = "The server rejected this device's token. " +
                                "Re-pair under MORE.")
                        is Fetched.Failed -> next = next.copy(
                            error = "Could not reach the server. ${metrics.detail}")
                    }
                    if (storage is Fetched.Ok) {
                        next = next.copy(
                            storageHuman = storage.value.humanTotal(),
                            segments = storage.value.totalSegments,
                            hours = storage.value.totalDurationHours,
                            withTargets = storage.value.segmentsWithTargets,
                        )
                    }
                    if (status is Fetched.Ok) {
                        next = next.copy(running = status.value.running)
                    }
                    next
                }
                delay(POLL_MS)
            }
        }
    }
}
