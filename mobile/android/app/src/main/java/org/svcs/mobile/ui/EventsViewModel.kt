package org.svcs.mobile.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.svcs.mobile.net.EventItem
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.SvcsApi
import org.svcs.mobile.net.ZoneLine
import org.svcs.mobile.net.ZonesConfig

data class EventsState(
    val events: List<EventItem> = emptyList(),
    val error: String? = null,
    // Editor half.
    val editorCamera: String = "cam_00",
    val drawMode: String = "zone",           // "zone" | "line"
    val editorExcludes: List<List<Double>> = emptyList(),
    val editorLines: List<ZoneLine> = emptyList(),
    val editorMessage: String? = null,
)

/**
 * EVENTS tab logic (R6 Track A): a 10s poll of /api/events/recent plus the
 * zone-editor state that GETs and POSTs /api/zones.
 *
 * Author: Bloodawn (KheivenD), 2026-08-17 (R6 Track A).
 */
class EventsViewModel(private val api: SvcsApi?) : ViewModel() {

    private val _state = MutableStateFlow(EventsState())
    val state: StateFlow<EventsState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            while (true) {
                refresh()
                delay(10_000)
            }
        }
    }

    fun refresh() {
        val client = api ?: return
        viewModelScope.launch {
            val r = withContext(Dispatchers.IO) { client.eventsRecent(100) }
            _state.update { s ->
                when (r) {
                    is Fetched.Ok -> s.copy(events = r.value.events, error = null)
                    Fetched.Unauthorized -> s.copy(
                        error = "The server rejected this device's token. Re-pair under MORE.")
                    is Fetched.Failed -> s.copy(
                        error = "Could not reach the server. ${r.detail}")
                }
            }
        }
    }

    // ── editor ───────────────────────────────────────────────────────────

    fun onCameraChanged(v: String) =
        _state.update { it.copy(editorCamera = v, editorMessage = null) }

    fun setDrawMode(mode: String) = _state.update { it.copy(drawMode = mode) }

    fun clearGeometry() = _state.update {
        it.copy(editorExcludes = emptyList(), editorLines = emptyList(),
            editorMessage = null)
    }

    fun addGeometry(x1: Float, y1: Float, x2: Float, y2: Float) {
        val q = listOf(x1.toDouble(), y1.toDouble(), x2.toDouble(), y2.toDouble())
            .map { it.coerceIn(0.0, 1.0) }
        val isLine = _state.value.drawMode == "line"
        // Tiny accidental taps are not zones (lines may be short on one axis).
        if (!isLine && (kotlin.math.abs(q[2] - q[0]) < 0.02 ||
                kotlin.math.abs(q[3] - q[1]) < 0.02)) {
            return
        }
        _state.update { s ->
            if (isLine) {
                s.copy(editorLines = s.editorLines +
                    ZoneLine(id = "line${s.editorLines.size + 1}", line = q))
            } else {
                s.copy(editorExcludes = s.editorExcludes + listOf(q))
            }
        }
    }

    fun loadZones() {
        val client = api ?: return
        val cam = _state.value.editorCamera.trim()
        if (cam.isBlank()) return
        viewModelScope.launch {
            val r = withContext(Dispatchers.IO) { client.getZones(cam) }
            _state.update { s ->
                when (r) {
                    is Fetched.Ok -> s.copy(
                        editorExcludes = r.value.config.exclude,
                        editorLines = r.value.config.lines,
                        editorMessage = "Loaded ${r.value.config.exclude.size} zone(s), " +
                            "${r.value.config.lines.size} line(s) for $cam.")
                    Fetched.Unauthorized -> s.copy(
                        editorMessage = "Token rejected. Re-pair under MORE.")
                    is Fetched.Failed -> s.copy(
                        editorMessage = "Load failed: ${r.detail}")
                }
            }
        }
    }

    fun saveZones() {
        val client = api ?: return
        val s0 = _state.value
        val cam = s0.editorCamera.trim()
        if (cam.isBlank()) return
        viewModelScope.launch {
            val cfg = ZonesConfig(exclude = s0.editorExcludes, lines = s0.editorLines)
            val r = withContext(Dispatchers.IO) { client.saveZones(cam, cfg) }
            _state.update { s ->
                when (r) {
                    is Fetched.Ok -> s.copy(
                        editorMessage = "Saved for $cam. Applies to the next run.")
                    Fetched.Unauthorized -> s.copy(
                        editorMessage = "Token rejected. Re-pair under MORE.")
                    is Fetched.Failed -> s.copy(
                        editorMessage = "Save failed: ${r.detail}")
                }
            }
        }
    }
}
