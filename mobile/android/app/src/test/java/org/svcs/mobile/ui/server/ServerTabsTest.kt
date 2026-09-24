package org.svcs.mobile.ui.server

import org.junit.Assert.assertEquals
import org.junit.Test
import org.svcs.mobile.net.Capabilities

/** Which Server Mode sections the SERVER tab offers. */
class ServerTabsTest {

    private val withLive = Capabilities(features = mapOf("hls" to true))
    private val fieldEdition = Capabilities(features = mapOf("hls" to false))

    @Test
    fun liveIsOfferedOnlyWhenTheServerStreams() {
        assertEquals(ServerTab.entries.toList(), visibleServerTabs(withLive))
        assertEquals(
            listOf(ServerTab.HOME, ServerTab.LIBRARY, ServerTab.EVENTS, ServerTab.METRICS),
            visibleServerTabs(fieldEdition),
        )
        // Capabilities not known yet: no LIVE rather than a tab that 404s.
        assertEquals(false, ServerTab.LIVE in visibleServerTabs(null))
    }

    @Test
    fun aSelectionThatIsNoLongerOffered_fallsBackToHome() {
        assertEquals(ServerTab.LIVE, effectiveServerTab(ServerTab.LIVE, withLive))
        assertEquals(ServerTab.HOME, effectiveServerTab(ServerTab.LIVE, fieldEdition))
        assertEquals(ServerTab.EVENTS, effectiveServerTab(ServerTab.EVENTS, fieldEdition))
    }
}
