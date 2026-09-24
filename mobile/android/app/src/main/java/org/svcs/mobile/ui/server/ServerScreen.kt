package org.svcs.mobile.ui.server

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import org.svcs.mobile.data.TokenStore
import org.svcs.mobile.net.Capabilities
import org.svcs.mobile.net.SvcsApiClient
import org.svcs.mobile.ui.components.SvcsIcons
import org.svcs.mobile.ui.server.events.EventsScreen
import org.svcs.mobile.ui.server.events.EventsViewModel
import org.svcs.mobile.ui.server.home.HomeScreen
import org.svcs.mobile.ui.server.home.HomeViewModel
import org.svcs.mobile.ui.server.library.LibraryScreen
import org.svcs.mobile.ui.server.library.LibraryViewModel
import org.svcs.mobile.ui.server.live.LiveScreen
import org.svcs.mobile.ui.server.live.LiveViewModel
import org.svcs.mobile.ui.server.metrics.MetricsScreen
import org.svcs.mobile.ui.server.metrics.MetricsViewModel
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsSurface
import org.svcs.mobile.ui.theme.SvcsTextDim

/** The Server Mode sections, shown as top tabs inside the SERVER tab. */
enum class ServerTab(val label: String, val icon: ImageVector) {
    HOME("HOME", SvcsIcons.Home),
    LIBRARY("LIBRARY", SvcsIcons.Library),
    LIVE("LIVE", SvcsIcons.Live),
    EVENTS("EVENTS", SvcsIcons.Events),
    METRICS("METRICS", SvcsIcons.Metrics),
}

/**
 * Which sections to offer. LIVE only exists when the server says it can stream:
 * the field edition registers no HLS blueprint, so the tab would just 404.
 */
fun visibleServerTabs(caps: Capabilities?): List<ServerTab> =
    ServerTab.entries.filter { it != ServerTab.LIVE || caps?.hasLive == true }

/** The selected section, falling back to HOME when it is not offered (a
 *  re-pair to a server without LIVE while LIVE was selected, say). */
fun effectiveServerTab(selected: ServerTab, caps: Capabilities?): ServerTab =
    if (selected in visibleServerTabs(caps)) selected else ServerTab.HOME

/**
 * SERVER tab: everything that needs the paired desktop, in one place.
 *
 * With a server paired the app used to put eight items in the bottom bar
 * (COMPRESS, SAVED, HOME, LIBRARY, LIVE, EVENTS, METRICS, MORE), past
 * Material's three-to-five guidance, so labels had to be hidden on all but the
 * selected one (UI-REVIEW.md open item 1). The five Server Mode sections now
 * sit under this one tab as a scrollable top tab strip, and the bottom bar is
 * COMPRESS, SAVED, SERVER, MORE: the standalone compressor first, Server Mode
 * one tap away.
 *
 * ViewModels stay keyed on [sessionEpoch] exactly as before, so a re-pair
 * still discards the ones bound to the old token.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (UI-REVIEW item 1).
 */
@Composable
fun ServerScreen(
    client: SvcsApiClient,
    caps: Capabilities?,
    store: TokenStore,
    sessionEpoch: Int,
    selected: ServerTab,
    onSelect: (ServerTab) -> Unit,
) {
    val tabs = visibleServerTabs(caps)
    val current = effectiveServerTab(selected, caps)
    Column(Modifier.fillMaxSize()) {
        ServerTabStrip(tabs, current, onSelect)
        Box(Modifier.fillMaxSize()) {
            when (current) {
                ServerTab.HOME -> HomeScreen(
                    vm = viewModel(key = "home-$sessionEpoch") { HomeViewModel(client) })
                ServerTab.LIBRARY -> LibraryScreen(
                    vm = viewModel(key = "lib-$sessionEpoch") {
                        LibraryViewModel(client, autoCompress = { store.autoCompressUpload() })
                    })
                ServerTab.LIVE -> LiveScreen(
                    vm = viewModel(key = "live-$sessionEpoch") {
                        LiveViewModel(
                            api = client,
                            lastSourceProvider = { store.lastLiveSource() },
                            lastSourceSaver = { store.setLastLiveSource(it) },
                        )
                    },
                )
                ServerTab.EVENTS -> EventsScreen(
                    vm = viewModel(key = "events-$sessionEpoch") { EventsViewModel(client) })
                ServerTab.METRICS -> MetricsScreen(
                    vm = viewModel(key = "metrics-$sessionEpoch") { MetricsViewModel(client) })
            }
        }
    }
}

/** Mono labels with an amber underline on the selected one, in the design's
 *  terminal style; scrolls sideways on narrow phones instead of truncating. */
@Composable
private fun ServerTabStrip(tabs: List<ServerTab>, current: ServerTab, onSelect: (ServerTab) -> Unit) {
    Column(Modifier.fillMaxWidth().background(SvcsSurface)) {
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp)) {
            tabs.forEach { t ->
                val on = t == current
                Column(
                    Modifier
                        .clickable(role = Role.Tab) { onSelect(t) }
                        .padding(horizontal = 10.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Spacer(Modifier.height(10.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(t.icon, contentDescription = null, tint = if (on) SvcsAmber else SvcsTextDim, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(t.label, style = MaterialTheme.typography.labelSmall, color = if (on) SvcsAmber else SvcsTextDim)
                    }
                    Spacer(Modifier.height(8.dp))
                    Box(Modifier.width(56.dp).height(2.dp).background(if (on) SvcsAmber else Color.Transparent))
                }
            }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(SvcsBorder))
    }
}
