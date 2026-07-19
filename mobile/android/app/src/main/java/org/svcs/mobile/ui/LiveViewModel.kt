package org.svcs.mobile.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.HlsStartResult
import org.svcs.mobile.net.SvcsApi

/** What the LIVE tab is doing. Each state maps to one thing on screen. */
sealed interface LiveState {
    /** Nothing running and we have not asked for anything. */
    data class Idle(val lastSource: String = "") : LiveState

    /**
     * Waiting for the playlist to become playable. [elapsedS] drives a progress
     * line, because a bare spinner for 3+ seconds reads as a hang.
     */
    data class Starting(val cameraId: String, val elapsedS: Int) : LiveState

    /** Playlist is ready. [url] can be handed to ExoPlayer now, not before. */
    data class Ready(
        val cameraId: String,
        val url: String,
        val weStartedIt: Boolean,
        val sourceLabel: String? = null,
    ) : LiveState

    data class Error(
        val message: String,
        val lastSource: String = "",
        /** True when the fix is re-pairing, not retrying. Changes the UI. */
        val needsRepair: Boolean = false,
    ) : LiveState
}

/**
 * Drives the LIVE tab (M3).
 *
 * The whole reason this class exists rather than handing a URL straight to
 * ExoPlayer is a measured 3.2s gap. On a real-time source, POST /api/hls/start
 * returns 200 and /api/hls/status reports running=true immediately, but the
 * playlist 404s until the first 2s segment CLOSES and ffmpeg writes it out.
 * ExoPlayer's default retry budget is shorter than that, so a player created on
 * the start response gives up before the stream exists and shows a dead frame
 * with no useful error. So: poll the playlist, and only build a player once it
 * genuinely names a segment.
 *
 * ingest_latency_s is deliberately NOT the gate. It is set when the first .ts
 * file appears, which was measured to land in the same 100ms sample as the
 * playlist entry, so it is no earlier and carries no extra information.
 *
 * Ownership matters on the way out. The server has a single process-wide
 * stream slot shared with the desktop dashboard, so this stops the stream only
 * if this app started it AND the server still says the stream it started is
 * the one running. That second half is not paranoia: the server reaps an idle
 * stream after 30s, and the desktop can stop and restart one at any time, so a
 * "we started it" flag taken on its own goes stale and would have this app
 * killing the operator's stream.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M3).
 */
class LiveViewModel(
    private val api: SvcsApi?,
    private val lastSourceProvider: suspend () -> String = { "" },
    private val lastSourceSaver: suspend (String) -> Unit = {},
) : ViewModel() {

    private companion object {
        /** Measured ready at ~3.2s; 45s covers an RTSP camera that is slow to
         *  handshake without hanging forever on one that will never connect. */
        const val READY_TIMEOUT_S = 45
        const val POLL_MS = 500L
        /** Steady-state health poll while playing. Well inside the server's
         *  30s idle timeout, so a stream that dies under us is noticed. */
        const val HEALTH_POLL_MS = 5000L
        const val DEFAULT_CAMERA = "cam_mobile"
        const val REPAIR_MSG =
            "The server rejected this device's token. Re-pair under MORE."
    }

    private val _state = MutableStateFlow<LiveState>(LiveState.Idle())
    val state: StateFlow<LiveState> = _state.asStateFlow()

    /** Every background loop this VM owns, so all of them can be cancelled. */
    private var readyJob: Job? = null
    private var healthJob: Job? = null

    /**
     * The camera_id this app started, or null.
     *
     * Deliberately not a boolean. Ownership has to be checked against what the
     * server says is running RIGHT NOW, and a name is what makes that check
     * possible.
     */
    private var startedCamera: String? = null

    fun httpClient(): OkHttpClient? = api?.httpClient()

    /**
     * Called when the tab appears. If the server is already streaming, attach
     * to it; otherwise sit idle and let the user pick a source.
     */
    fun onAppear() {
        val client = api ?: run {
            _state.value = LiveState.Error("Not paired with a server yet.")
            return
        }
        // Cancel anything a previous visit left running, so repeated visits
        // cannot stack readiness loops on top of each other.
        cancelJobs()
        readyJob = viewModelScope.launch {
            val remembered = lastSourceProvider()
            when (val st = withContext(Dispatchers.IO) { client.hlsStatus() }) {
                is Fetched.Ok -> {
                    val s = st.value
                    if (s.running && !s.cameraId.isNullOrBlank()) {
                        // Someone else's stream. Watch it, do not claim it.
                        startedCamera = null
                        // Show CONNECTING, not the START form: this still has
                        // to wait for the playlist, and an idle-looking form
                        // during that wait invites a second start.
                        _state.value = LiveState.Starting(s.cameraId, 0)
                        awaitReady(s.cameraId, weStarted = false,
                                   sourceLabel = s.inputSource)
                    } else {
                        _state.value = LiveState.Idle(remembered)
                    }
                }
                Fetched.Unauthorized ->
                    _state.value = LiveState.Error(REPAIR_MSG, remembered,
                                                   needsRepair = true)
                is Fetched.Failed -> _state.value = LiveState.Error(
                    "Could not reach the server. ${st.detail}", remembered)
            }
        }
    }

    /** Start streaming [source] and wait for it to become playable. */
    fun start(source: String, mode: String = "Mode 2") {
        val client = api ?: return
        val src = source.trim()
        if (src.isEmpty()) {
            _state.value = LiveState.Error("Enter a camera source first.")
            return
        }
        cancelJobs()
        readyJob = viewModelScope.launch {
            lastSourceSaver(src)
            _state.value = LiveState.Starting(DEFAULT_CAMERA, 0)
            // Claim ownership BEFORE the request. If this coroutine is
            // cancelled while the POST is in flight, the server may still have
            // started the stream; recording the claim first means onCleared
            // can release the slot instead of leaking it.
            startedCamera = DEFAULT_CAMERA
            when (val r = withContext(Dispatchers.IO) {
                client.hlsStart(src, DEFAULT_CAMERA, mode)
            }) {
                HlsStartResult.Started ->
                    awaitReady(DEFAULT_CAMERA, weStarted = true, sourceLabel = src)
                HlsStartResult.AlreadyRunning -> {
                    // One stream slot server-wide. Attach to whatever holds it
                    // rather than reporting a conflict the user cannot act on.
                    startedCamera = null
                    val st = withContext(Dispatchers.IO) { client.hlsStatus() }
                    val cam = (st as? Fetched.Ok)?.value?.cameraId ?: DEFAULT_CAMERA
                    awaitReady(cam, weStarted = false,
                               sourceLabel = (st as? Fetched.Ok)?.value?.inputSource)
                }
                HlsStartResult.Unauthorized -> {
                    startedCamera = null
                    _state.value = LiveState.Error(REPAIR_MSG, src,
                                                   needsRepair = true)
                }
                is HlsStartResult.Failed -> {
                    startedCamera = null
                    _state.value = LiveState.Error(r.detail, src)
                }
            }
        }
    }

    /**
     * Poll until the playlist actually names a segment.
     *
     * Polling the playlist rather than the status route is the entire point:
     * status says running=true a full segment before there is anything to play.
     */
    private suspend fun awaitReady(
        cameraId: String,
        weStarted: Boolean,
        sourceLabel: String?,
    ) {
        val client = api ?: return
        var waited = 0
        while (waited < READY_TIMEOUT_S * 1000) {
            // Check auth FIRST. playlistReady() cannot distinguish a 401 from
            // "no segment yet", so polling it blind against a revoked token
            // both hides the real problem and burns the server's failed-auth
            // budget: 10 failures in 300s locks this IP out of EVERY route for
            // five minutes, which would break HOME, LIBRARY and METRICS too.
            when (val st = withContext(Dispatchers.IO) { client.hlsStatus() }) {
                Fetched.Unauthorized -> {
                    _state.value = LiveState.Error(REPAIR_MSG,
                                                   sourceLabel ?: "",
                                                   needsRepair = true)
                    return
                }
                is Fetched.Ok -> {
                    val err = st.value.error
                    if (!err.isNullOrBlank()) {
                        // A bad RTSP address fails in the annotator thread and
                        // the status route's error field is the only place it
                        // shows up. Surface it instead of counting to 45.
                        _state.value = LiveState.Error(err, sourceLabel ?: "")
                        return
                    }
                    if (!st.value.running && waited > 2000) {
                        _state.value = LiveState.Error(
                            "The stream stopped before it produced any video. " +
                                "Check that the camera address is reachable.",
                            sourceLabel ?: "")
                        return
                    }
                }
                is Fetched.Failed -> Unit  // transient; keep waiting
            }

            if (withContext(Dispatchers.IO) { client.playlistReady(cameraId) }) {
                _state.value = LiveState.Ready(
                    cameraId = cameraId,
                    url = client.playlistUrl(cameraId),
                    weStartedIt = weStarted,
                    sourceLabel = sourceLabel,
                )
                startHealthPoll(cameraId)
                return
            }
            delay(POLL_MS)
            waited += POLL_MS.toInt()
            _state.update { cur ->
                if (cur is LiveState.Starting) cur.copy(elapsedS = waited / 1000)
                else cur
            }
        }
        _state.value = LiveState.Error(
            "The stream did not produce any video within ${READY_TIMEOUT_S}s.",
            sourceLabel ?: "")
    }

    /**
     * While playing, keep asking the server whether the stream still exists.
     *
     * Without this the UI shows a green STREAMING label over a frozen picture
     * whenever the stream ends underneath it, which happens routinely: the
     * server reaps a stream nobody is fetching after 30s, and the desktop can
     * stop one at any moment. It also keeps the ownership claim honest, so
     * leaving the tab cannot stop a stream that is no longer ours.
     */
    private fun startHealthPoll(cameraId: String) {
        healthJob?.cancel()
        healthJob = viewModelScope.launch {
            while (isActive) {
                delay(HEALTH_POLL_MS)
                val client = api ?: return@launch
                when (val st = withContext(Dispatchers.IO) { client.hlsStatus() }) {
                    Fetched.Unauthorized -> {
                        startedCamera = null
                        _state.value = LiveState.Error(REPAIR_MSG,
                                                       needsRepair = true)
                        return@launch
                    }
                    is Fetched.Ok -> {
                        val s = st.value
                        if (!s.running) {
                            startedCamera = null
                            _state.value = LiveState.Error(
                                "The stream ended on the server.",
                                lastSourceProvider())
                            return@launch
                        }
                        if (s.cameraId != null && s.cameraId != cameraId) {
                            // A different stream took the single slot. What we
                            // were playing is gone, and it is emphatically not
                            // ours to stop any more.
                            startedCamera = null
                            _state.value = LiveState.Error(
                                "Another client started a different stream " +
                                    "(${s.cameraId}).",
                                lastSourceProvider())
                            return@launch
                        }
                    }
                    is Fetched.Failed -> Unit  // transient; keep watching
                }
            }
        }
    }

    /** Report a playback failure from the player into the state machine. */
    fun onPlaybackError(codeName: String, isAuth: Boolean) {
        cancelJobs()
        if (isAuth) {
            startedCamera = null
            _state.value = LiveState.Error(REPAIR_MSG, needsRepair = true)
        } else {
            _state.value = LiveState.Error(
                "Playback stopped ($codeName). The stream may have ended or " +
                    "the connection dropped.",
                (_state.value as? LiveState.Ready)?.sourceLabel ?: "")
        }
    }

    /**
     * Leaving the tab.
     *
     * Stops the server-side stream only if this app started it AND the server
     * still reports that same stream running. The desktop shares the single
     * stream slot, and the flag alone goes stale: the server reaps an idle
     * stream after 30s, after which the operator may have started their own.
     * Acting on the stale flag would kill it with no warning on either device.
     */
    fun onLeave() {
        cancelJobs()
        val mine = startedCamera ?: return
        val client = api ?: return
        startedCamera = null
        viewModelScope.launch {
            val stillMine = when (val st = withContext(Dispatchers.IO) {
                client.hlsStatus()
            }) {
                is Fetched.Ok -> st.value.running && st.value.cameraId == mine
                else -> false
            }
            if (stillMine) withContext(Dispatchers.IO) { client.hlsStop() }
            _state.value = LiveState.Idle(lastSourceProvider())
        }
    }

    /** Explicit user action, so it stops the stream whoever started it. */
    fun stopStream() {
        val client = api ?: return
        cancelJobs()
        startedCamera = null
        viewModelScope.launch {
            withContext(Dispatchers.IO) { client.hlsStop() }
            _state.value = LiveState.Idle(lastSourceProvider())
        }
    }

    private fun cancelJobs() {
        readyJob?.cancel()
        readyJob = null
        healthJob?.cancel()
        healthJob = null
    }

    /**
     * Last resort: the VM is going away (activity finishing), so release the
     * stream slot if we are still holding it. viewModelScope is already
     * cancelled here, so this cannot use it.
     */
    override fun onCleared() {
        val mine = startedCamera
        val client = api
        startedCamera = null
        if (mine != null && client != null) {
            Thread { client.hlsStop() }.apply { isDaemon = true }.start()
        }
        super.onCleared()
    }
}
