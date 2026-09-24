package org.svcs.mobile.compress

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class EncoderFallbackTest {

    @Test
    fun matchingOutput_saysNothing() {
        assertNull(EncoderFallback.describe("video/hevc", "video/hevc", 1280, 720, 1280, 720))
    }

    @Test
    fun portraitEncodedAsRotatedLandscape_isNotAFallback() {
        // Media3 encodes a 720x1280 portrait frame as 1280x720 plus rotation.
        assertNull(EncoderFallback.describe("video/hevc", "video/hevc", 720, 1280, 1280, 720))
    }

    @Test
    fun encoderRounding_isNotAFallback() {
        assertNull(EncoderFallback.describe("video/avc", "video/avc", 1918, 1080, 1920, 1088))
    }

    @Test
    fun emulatorStyleHevcCap_isReported_inTheRequestedOrientation() {
        val note = EncoderFallback.describe("video/hevc", "video/hevc", 720, 1280, 512, 288)
        assertEquals("The encoder lowered the resolution to 288x512 (asked for 720x1280).", note)
    }

    @Test
    fun codecSwitch_isReported() {
        assertEquals(
            "Saved as H.264 because this phone could not encode H.265.",
            EncoderFallback.describe("video/hevc", "video/avc", 1280, 720, 1280, 720),
        )
    }

    @Test
    fun unknownSizes_onlyReportTheCodec() {
        assertNull(EncoderFallback.describe("video/hevc", null, 0, 0, -1, -1))
    }
}
