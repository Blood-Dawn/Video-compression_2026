package org.svcs.mobile.ui

import java.util.Locale
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/** Formatting shared by COMPRESS, SAVED and Server Mode's HOME. */
class FormatTest {

    private lateinit var saved: Locale

    @Before
    fun pinLocale() {
        // String.format follows the default locale; pin it so "12.3" is not "12,3".
        saved = Locale.getDefault()
        Locale.setDefault(Locale.US)
    }

    @After
    fun restoreLocale() = Locale.setDefault(saved)

    @Test
    fun humanBytes_isBinaryAndPicksTheUnit() {
        assertEquals("40 B", humanBytes(40))
        assertEquals("512 KB", humanBytes(512 * 1024))
        assertEquals("12.3 MB", humanBytes((12.3 * 1_048_576).toLong()))
        assertEquals("1.66 GB", humanBytes((1.66 * 1_073_741_824).toLong()))
    }

    @Test
    fun decimalMb_matchesHowPlatformsQuoteLimits() {
        // Discord's "10 MB" is 10,000,000 bytes; humanBytes would say 9.5 MB.
        assertEquals("10 MB", decimalMb(10_000_000))
        assertEquals("9.5 MB", humanBytes(10_000_000))
        assertEquals("8.5 MB", decimalMb(8_500_000))
    }

    @Test
    fun clock_isMinutesAndPaddedSeconds() {
        assertEquals("0:00", clock(0))
        assertEquals("0:00", clock(-5_000))
        assertEquals("1:47", clock(107_267))
        assertEquals("61:01", clock(3_661_000))
    }
}
