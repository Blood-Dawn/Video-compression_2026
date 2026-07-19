package org.svcs.mobile.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.svcs.mobile.data.TokenStore
import org.svcs.mobile.net.Capabilities
import org.svcs.mobile.net.ProbeResult
import org.svcs.mobile.net.SvcsApi

/**
 * Tabs from the design mockup. LIVE is conditional: the field edition registers
 * no HLS blueprint at all, so on that build the tab must not exist rather than
 * appear and 404 on every request. /api/capabilities is what tells us.
 */
enum class Tab(val label: String) {
    HOME("HOME"),
    LIBRARY("LIBRARY"),
    LIVE("LIVE"),
    METRICS("METRICS"),
    MORE("MORE"),
}

/**
 * App shell (M2).
 *
 * Pairing state decides what renders: with no stored token there is nothing to
 * show but the pairing screen, so the bottom nav does not appear at all rather
 * than offering four tabs that would each report "not paired".
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2).
 */
@Composable
fun SvcsApp() {
    val context = LocalContext.current
    val store = remember { TokenStore(context) }

    var api by remember { mutableStateOf<SvcsApi?>(null) }
    var caps by remember { mutableStateOf<Capabilities?>(null) }
    var checked by remember { mutableStateOf(false) }
    var tab by remember { mutableStateOf(Tab.HOME) }

    /**
     * Bumped whenever credentials are saved.
     *
     * Keying both the pairing probe and the per-tab ViewModels on this is what
     * makes re-pairing actually take effect. Previously the probe ran once at
     * launch and every screen kept the SvcsApi built from the token in force at
     * that moment, so a user whose token had been revoked was told to re-pair
     * under MORE, did it, and stayed broken until they force-quit the app.
     */
    var sessionEpoch by remember { mutableStateOf(0) }

    // Restore the saved pairing and ask the server what it can do. Re-runs on
    // re-pair so the new token is picked up in place.
    LaunchedEffect(sessionEpoch) {
        checked = false
        api = null
        val url = store.serverUrl()
        val token = store.token()
        if (!url.isNullOrBlank() && !token.isNullOrBlank()) {
            val client = SvcsApi(url, token)
            val probe = withContext(Dispatchers.IO) { client.probe() }
            if (probe is ProbeResult.Ok) {
                api = client
                caps = probe.capabilities
            }
        }
        checked = true
    }

    if (!checked) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("SVCS", style = MaterialTheme.typography.displaySmall)
        }
        return
    }

    if (api == null) {
        // Not paired. The pairing screen is the whole app until it is.
        ServerSettingsScreen(onCredentialsSaved = { sessionEpoch++ })
        return
    }

    val visibleTabs = Tab.entries.filter { it != Tab.LIVE || caps?.hasLive == true }

    Scaffold(
        bottomBar = {
            NavigationBar {
                visibleTabs.forEach { t ->
                    NavigationBarItem(
                        selected = tab == t,
                        onClick = { tab = t },
                        icon = {},
                        label = { Text(t.label, style = MaterialTheme.typography.labelSmall) },
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            // The ViewModel keys carry sessionEpoch so re-pairing discards the
            // cached ones. They hold an SvcsApi bound to the token that was in
            // force when they were created, and a stale one would keep 401ing
            // against a credential the user has already replaced.
            when (tab) {
                Tab.LIBRARY -> LibraryScreen(
                    vm = viewModel(key = "lib-$sessionEpoch") { LibraryViewModel(api) })
                Tab.METRICS -> MetricsScreen(
                    vm = viewModel(key = "metrics-$sessionEpoch") { MetricsViewModel(api) })
                Tab.MORE -> ServerSettingsScreen(
                    onCredentialsSaved = { sessionEpoch++ })
                Tab.HOME -> HomeScreen(
                    vm = viewModel(key = "home-$sessionEpoch") { HomeViewModel(api) })
                Tab.LIVE -> LiveScreen(
                    vm = viewModel(key = "live-$sessionEpoch") {
                        LiveViewModel(
                            api = api,
                            lastSourceProvider = { store.lastLiveSource() },
                            lastSourceSaver = { store.setLastLiveSource(it) },
                        )
                    },
                )
            }
        }
    }
}
