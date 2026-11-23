package org.svcs.mobile.securitycam

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** What the recording service is doing right now, for the screen to show. */
data class SecurityCamStatus(
    val running: Boolean = false,
    /** Seconds until the current clip is cut and sent. */
    val secondsLeft: Int = 0,
    val clipSeconds: Int = 0,
    val clipsRecorded: Int = 0,
    val error: String? = null,
)

/**
 * Process-wide status of the Security cam service. A service and a screen
 * cannot share a ViewModel, and this is two small values, so a StateFlow in an
 * object is the simplest honest bridge.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, roadmap 13.1).
 */
object SecurityCamBus {
    private val _status = MutableStateFlow(SecurityCamStatus())
    val status: StateFlow<SecurityCamStatus> = _status

    fun update(block: (SecurityCamStatus) -> SecurityCamStatus) {
        _status.value = block(_status.value)
    }

    fun reset(clipSeconds: Int) {
        _status.value = SecurityCamStatus(running = true, clipSeconds = clipSeconds, secondsLeft = clipSeconds)
    }
}
