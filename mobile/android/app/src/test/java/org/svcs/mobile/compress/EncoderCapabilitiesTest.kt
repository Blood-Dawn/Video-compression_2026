package org.svcs.mobile.compress

import org.junit.Assert.assertEquals
import org.junit.Test

/** The MORE screen's one-line-per-format summary of the ROI probe. */
class EncoderCapabilitiesTest {

    private fun enc(name: String, mime: String, hw: Boolean, roi: Boolean) =
        EncoderInfo(name, mime, hardware = hw, roi = roi, constantQuality = false)

    @Test
    fun roiEncoder_isNamedWhenPresent() {
        val lines = EncoderCapabilities.summary(listOf(
            enc("c2.android.hevc.encoder", "video/hevc", hw = false, roi = false),
            enc("c2.vendor.hevc.encoder", "video/hevc", hw = true, roi = true),
            enc("c2.vendor.avc.encoder", "video/avc", hw = true, roi = false),
        ))
        assertEquals("H.265: region-of-interest encoding supported (c2.vendor.hevc.encoder)", lines[0])
        assertEquals(
            "H.264: no region-of-interest support (c2.vendor.avc.encoder); Smart Compress uses the whole-clip mode",
            lines[1],
        )
    }

    @Test
    fun withoutRoi_theHardwareEncoderIsTheOneNamed() {
        val lines = EncoderCapabilities.summary(listOf(
            enc("c2.android.avc.encoder", "video/avc", hw = false, roi = false),
            enc("c2.vendor.avc.encoder", "video/avc", hw = true, roi = false),
        ))
        assertEquals("H.265: no encoder found", lines[0])
        assertEquals(true, lines[1].contains("c2.vendor.avc.encoder"))
    }
}
