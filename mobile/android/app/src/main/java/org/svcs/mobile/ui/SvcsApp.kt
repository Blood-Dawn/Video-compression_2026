package org.svcs.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.svcs.mobile.JobNotifier
import org.svcs.mobile.data.TokenStore
import org.svcs.mobile.net.Capabilities
import org.svcs.mobile.net.Fetched
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
 * 2026-08-16 rework (0.3.1): a re-pair no longer tears the whole UI down.
 * Previously every save nulled `api` and dropped to the splash while the probe
 * re-ran, and combined with the stale save-event replay in the settings screen
 * (see ServerSettingsScreen) the shell cycled splash <-> settings forever the
 * moment the user opened MORE after pairing; on the device it read as "the
 * screen is glitching". Now the old session keeps rendering while the new
 * probe runs, and a successful (re)pair lands the user on HOME, which is also
 * the explicit "you are in the app now" moment the pairing flow was missing.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2); reworked 2026-08-16.
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
     * Bumped whenever credentials are saved (a real save, not a replay; the
     * settings screen guarantees that since 0.3.1). Keying both the pairing
     * probe and the per-tab ViewModels on this is what makes re-pairing take
     * effect without a force-quit.
     */
    var sessionEpoch by remember { mutableStateOf(0) }

    // Restore the saved pairing and ask the server what it can do. Re-runs on
    // re-pair so the new token is picked up in place. The previous session
    // stays on screen while this runs; only the RESULT swaps the UI.
    LaunchedEffect(sessionEpoch) {
        val isRepair = checked
        val url = store.serverUrl()
        val token = store.token()
        var newApi: SvcsApi? = null
        var newCaps: Capabilities? = null
        if (!url.isNullOrBlank() && !token.isNullOrBlank()) {
            val client = SvcsApi(url, token)
            val probe = withContext(Dispatchers.IO) { client.probe() }
            if (probe is ProbeResult.Ok) {
                newApi = client
                newCaps = probe.capabilities
            }
        }
        api = newApi
        caps = newCaps
        checked = true
        // Land in the app after a successful save; the pairing screen's
        // SAVE & OPEN button promises exactly this.
        if (newApi != null && (isRepair || tab == Tab.MORE)) tab = Tab.HOME
    }

    // M5 slice: notify when a server job finishes. Polls /api/jobs/recent
    // every 10s while the app process lives; the FIRST result only baselines
    // (jobs that finished before the app opened are history, not news).
    // Closed-app push transport remains open work per MOBILE-ARCHITECTURE.
    val appContext = context.applicationContext
    LaunchedEffect(sessionEpoch) {
        var lastSeen: Double? = null
        var baselined = false
        while (true) {
            val client = api
            if (client != null) {
                val r = withContext(Dispatchers.IO) { client.jobsRecent(1) }
                if (r is Fetched.Ok) {
                    val newest = r.value.jobs.firstOrNull()
                    val ts = newest?.endedAt
                    if (!baselined) {
                        lastSeen = ts
                        baselined = true
                    } else if (newest != null && ts != null && ts != lastSeen) {
                        lastSeen = ts
                        JobNotifier.notifyJobDone(
                            appContext, newest.label, newest.status)
                    }
                }
            }
            delay(10_000)
        }
    }

    if (!checked) {
        // First launch only: an honest loading state, not a bare wordmark.
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text("SVCS", style = MaterialTheme.typography.displaySmall)
                CircularProgressIndicator()
                Text(
                    "CONNECTING TO SERVER...",
                    style = MaterialTheme.typography.labelSmall,
                )
            }
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
