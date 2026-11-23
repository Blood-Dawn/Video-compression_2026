package org.svcs.mobile.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Shape of GET /api/security-cam, the desktop side of the Security cam.
 *
 * The phone only READS this: the clip length and mode are chosen on the
 * desktop (a POST there needs the dashboard password, which a device token
 * does not carry). Unknown keys are ignored so a newer server cannot break an
 * older installed app.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, roadmap 13.1).
 */
@Serializable
data class SecurityCamInfo(
    @SerialName("segment_seconds") val segmentSeconds: Int = 600,
    val mode: String = "mode0",
    val receiving: Boolean = false,
    @SerialName("watch_folder") val watchFolder: String = "",
    val phones: List<SecurityCamPhone> = emptyList(),
    val recent: List<SecurityCamClip> = emptyList(),
)

@Serializable
data class SecurityCamPhone(
    val id: String = "",
    val label: String = "",
    @SerialName("last_seen") val lastSeen: String = "",
)

/** One clip the desktop has already compressed, with real byte sizes. */
@Serializable
data class SecurityCamClip(
    val name: String = "",
    val verdict: String = "",
    @SerialName("saved_pct") val savedPct: Double? = null,
    @SerialName("before_mb") val beforeMb: Double? = null,
    @SerialName("after_mb") val afterMb: Double? = null,
)
