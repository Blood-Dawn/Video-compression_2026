package org.svcs.mobile.securitycam

import androidx.work.WorkInfo.State
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.svcs.mobile.net.SecurityCamClip
import org.svcs.mobile.ui.server.cam.clipLengthLabel
import org.svcs.mobile.ui.server.cam.clipLine
import org.svcs.mobile.ui.server.cam.countdownLabel

/** Pure parts of the Security cam: naming, ordering, counting and labels. */
class SecurityCamTest {

    @Test
    fun clipNamesSortInRecordingOrder() {
        val a = ClipQueue.clipName(1_795_400_000_000L)
        val b = ClipQueue.clipName(1_795_400_600_000L)
        assertTrue(a.startsWith("cam_") && a.endsWith(".mp4"))
        assertTrue(a < b)
    }

    @Test
    fun waitingClipsAreOldestFirstAndIgnoreOtherFiles() {
        val dir = createTempDir()
        File(dir, "cam_20261123_140500.mp4").writeText("b")
        File(dir, "cam_20261123_140000.mp4").writeText("a")
        File(dir, "notes.txt").writeText("x")
        assertEquals(
            listOf("cam_20261123_140000.mp4", "cam_20261123_140500.mp4"),
            ClipQueue.waitingClips(dir).map { it.name },
        )
        dir.deleteRecursively()
    }

    @Test
    fun sha256MatchesTheKnownDigest() {
        val f = File.createTempFile("clip", ".mp4")
        f.writeText("abc")
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", ClipQueue.sha256(f))
        f.delete()
    }

    @Test
    fun roomCheckUsesTheFreeSpaceThreshold() {
        val dir = createTempDir()
        assertTrue(ClipQueue.hasRoom(dir, minFree = 1))
        assertFalse(ClipQueue.hasRoom(dir, minFree = Long.MAX_VALUE))
        dir.deleteRecursively()
    }

    @Test
    fun countsGroupWorkStates() {
        val c = ClipCounts.from(
            listOf(State.SUCCEEDED, State.SUCCEEDED, State.RUNNING, State.ENQUEUED, State.BLOCKED, State.FAILED),
        )
        assertEquals(ClipCounts(sent = 2, waiting = 3, failed = 1), c)
    }

    @Test
    fun labelsReadLikeAPersonWouldSayThem() {
        assertEquals("10 min", clipLengthLabel(600))
        assertEquals("90 s", clipLengthLabel(90))
        assertEquals("9:41", countdownLabel(581))
        assertEquals("0:05", countdownLabel(5))
    }

    @Test
    fun clipLineUsesTheDesktopsRealSizes() {
        val c = SecurityCamClip("cam_a.mp4", "saved", 62.0, 212.4, 81.3)
        assertEquals("cam_a.mp4: 212.4 MB to 81.3 MB (62% saved)", clipLine(c))
        assertEquals("cam_b.mp4: pending", clipLine(SecurityCamClip("cam_b.mp4", "pending")))
    }
}
