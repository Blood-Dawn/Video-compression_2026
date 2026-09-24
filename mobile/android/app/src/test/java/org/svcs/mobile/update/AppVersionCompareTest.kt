package org.svcs.mobile.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Mirrors the desktop's test_version.py: same shapes, same expected
 * outcomes, since AppVersionCompare is a straight port of that module's
 * parse_version/is_newer.
 */
class AppVersionCompareTest {

    @Test
    fun plainNumberBeatsAnyStagedSameNumber() {
        assertTrue(AppVersionCompare.isNewer("2.2.0", "2.2.0.dev1"))
        assertTrue(AppVersionCompare.isNewer("2.2.0", "2.2.0-beta"))
        assertTrue(AppVersionCompare.isNewer("2.2.0", "2.2.0rc1"))
    }

    @Test
    fun betaOutranksDevAtTheSameNumber() {
        // The exact regression this project hit on 2026-09-24: a beta tag
        // must outrank a same-numbered dev build every time, permanently.
        assertTrue(AppVersionCompare.isNewer("2.2.0-beta", "2.2.0.dev1"))
        assertFalse(AppVersionCompare.isNewer("2.2.0.dev1", "2.2.0-beta"))
    }

    @Test
    fun higherPatchBeatsLowerStage() {
        assertTrue(AppVersionCompare.isNewer("2.2.1.dev0", "2.2.0"))
    }

    @Test
    fun leadingVIsAccepted() {
        assertTrue(AppVersionCompare.isNewer("v1.3.0", "v1.2.1-beta"))
    }

    @Test
    fun sameVersionIsNotNewer() {
        assertFalse(AppVersionCompare.isNewer("1.2.1-beta", "1.2.1-beta"))
        assertFalse(AppVersionCompare.isNewer("2.2.0", "2.2.0"))
    }

    @Test
    fun unparseableTagSortsAsLowest() {
        // The historical mobile tag "v1-beta" has no minor/patch numbers -
        // it must never be mistaken for newer than a real version.
        assertFalse(AppVersionCompare.isNewer("v1-beta", "1.2.1-beta"))
        assertTrue(AppVersionCompare.isNewer("1.2.1-beta", "v1-beta"))
    }

    @Test
    fun blankOrNullNeverThrowsAndSortsAsLowest() {
        assertEquals(AppVersionCompare.Parsed.LOWEST, AppVersionCompare.parse(null))
        assertEquals(AppVersionCompare.Parsed.LOWEST, AppVersionCompare.parse(""))
        assertEquals(AppVersionCompare.Parsed.LOWEST, AppVersionCompare.parse("not-a-version"))
    }

    @Test
    fun stageNumberBreaksTiesWithinTheSameStage() {
        assertTrue(AppVersionCompare.isNewer("2.2.0-beta2", "2.2.0-beta"))
        assertTrue(AppVersionCompare.isNewer("2.2.0rc2", "2.2.0rc1"))
    }
}
