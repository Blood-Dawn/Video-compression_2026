package org.svcs.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import org.svcs.mobile.net.Capabilities
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTextDim
import org.svcs.mobile.ui.theme.SvcsYellow

/**
 * The pairing screen: server address, device token, Test, Save.
 *
 * This is the whole of M1.1. It is kept to one screen on purpose, because it
 * is the first Android code in a Python repo and the risk is in the toolchain,
 * not the UI.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */
@Composable
fun ServerSettingsScreen(
    vm: ServerSettingsViewModel = viewModel(),
    /**
     * Fired after credentials are saved, so the shell can rebuild its API
     * client. Re-pairing is worthless if the rest of the app keeps using the
     * client it built at launch with the old token.
     */
    onCredentialsSaved: () -> Unit = {},
) {
    val state by vm.state.collectAsState()

    // One-shot save event (0.3.1 fix). The ViewModel outlives this screen, so
    // saveCount is STATE, not an event: after the first save it stays > 0
    // forever, and the old `if (saveCount > 0) fire` replayed the callback on
    // every later visit to MORE. The shell responded by rebuilding the whole
    // session, which remounted this screen, which replayed the callback again,
    // an infinite teardown loop that looked like the screen glitching. The
    // baseline records the count at first composition and only a LATER
    // increment (a save the user just performed here) fires the callback once.
    // Author: Bloodawn (KheivenD), 2026-08-16 (0.3.1 glitch fix).
    var savedBaseline by remember { mutableStateOf<Int?>(null) }
    LaunchedEffect(state.saveCount) {
        val baseline = savedBaseline
        if (baseline == null) {
            savedBaseline = state.saveCount
        } else if (state.saveCount > baseline) {
            savedBaseline = state.saveCount
            onCredentialsSaved()
        }
    }

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(20.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("SVCS", style = MaterialTheme.typography.displaySmall)
            Text(
                "SELECTIVE VIDEO COMPRESSION SYSTEM",
                style = MaterialTheme.typography.labelSmall,
                color = SvcsTextDim,
            )

            OutlinedTextField(
                value = state.serverUrl,
                onValueChange = vm::onServerUrlChanged,
                label = { Text("SERVER ADDRESS") },
                placeholder = { Text("http://192.168.1.42:5000") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                isError = state.urlError != null,
                supportingText = {
                    state.urlError?.let { Text(it, color = SvcsRed) }
                },
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = state.token,
                onValueChange = vm::onTokenChanged,
                label = { Text("ACCESS TOKEN") },
                placeholder = { Text("svcs_...") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "Create a token on the dashboard under Settings. It is shown " +
                    "once. Credentials are sent only to your own SVCS server " +
                    "and are never logged.",
                style = MaterialTheme.typography.bodyMedium,
                color = SvcsTextDim,
            )

            Button(
                onClick = vm::testConnection,
                enabled = !state.busy && state.serverUrl.isNotBlank() &&
                    state.token.isNotBlank(),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.busy) {
                    CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
                }
                Text(if (state.busy) "TESTING..." else "TEST CONNECTION")
            }

            state.message?.let { msg ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        msg,
                        modifier = Modifier.padding(12.dp),
                        color = if (state.ok) SvcsGreen else SvcsRed,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }

            state.capabilities?.let { CapabilitiesCard(it) }

            // A public address is refused unless the user says so explicitly.
            // Deliberately a second, worded confirmation rather than a plain
            // toggle: this is the moment a user would otherwise publish their
            // camera footage to the internet without noticing.
            if (state.needsPublicConsent) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text(
                            "That address is not on a private network.",
                            style = MaterialTheme.typography.titleMedium,
                            color = SvcsYellow,
                        )
                        Text(
                            "SVCS speaks plain HTTP, so your token and your " +
                                "video would cross the public internet " +
                                "unencrypted. Use a VPN (WireGuard or " +
                                "Tailscale) instead. Continue only if you " +
                                "know this address is safe.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = SvcsTextDim,
                        )
                        TextButton(onClick = vm::confirmPublicAddress) {
                            Text("I understand, connect anyway")
                        }
                    }
                }
            }

            if (state.capabilities != null) {
                // The explicit "you are entering the app now" affordance. On a
                // working connection this saves the pairing and the shell then
                // lands on HOME; calling it SAVE alone left users staring at
                // this screen wondering how to get into the app.
                Button(
                    onClick = vm::save,
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("SAVE & OPEN") }
                Text(
                    "Saves this pairing and opens the dashboard.",
                    style = MaterialTheme.typography.labelSmall,
                    color = SvcsTextDim,
                )
            }

            // 0.8.0: upload behavior. Some operators want to upload now and
            // pick a mode later; the auto-compress is a choice, not a law.
            SettingSwitchRow(
                title = "Auto-compress uploads",
                subtitle = "When on, an uploaded video immediately compresses " +
                    "with mode 1. When off, it just lands in the server's " +
                    "uploads folder for later.",
                checked = state.autoCompressUpload,
                onToggle = vm::toggleAutoCompress,
            )

            // R6 Track C (0.9.0): closed-app push. These settings live on the
            // SERVER, because the server is what posts to ntfy, so this is a
            // remote control rather than a phone preference. Hidden until the
            // pairing exists, since without it there is nothing to talk to.
            if (state.serverUrl.isNotBlank() && state.token.isNotBlank()) {
                LaunchedEffect(state.serverUrl, state.token) {
                    if (!state.pushLoaded) vm.loadPushConfig()
                }
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        Modifier.padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Text("PHONE ALERTS WHILE SVCS IS CLOSED",
                            style = MaterialTheme.typography.labelSmall,
                            color = SvcsYellow)
                        Text(
                            "This app's own notifications stop when Android " +
                                "stops the app. To still hear about a line " +
                                "crossing, the server posts to an ntfy topic " +
                                "you host, and the ntfy app on this phone " +
                                "wakes up for it. Setup is in " +
                                "docs/PUSH-NOTIFICATIONS.md.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = SvcsTextDim,
                        )
                        OutlinedTextField(
                            value = state.pushTopicUrl,
                            onValueChange = vm::onPushTopicChanged,
                            label = { Text("NTFY TOPIC URL") },
                            placeholder = { Text("http://192.168.1.50:8080/svcs-a7f3c9d2") },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                            modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedTextField(
                            value = state.pushToken,
                            onValueChange = vm::onPushTokenChanged,
                            label = { Text("NTFY TOKEN") },
                            placeholder = {
                                Text(
                                    if (state.pushHasToken)
                                        "a token is stored, leave blank to keep it"
                                    else "optional, for a topic that needs auth",
                                )
                            },
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            modifier = Modifier.fillMaxWidth(),
                        )
                        SettingSwitchRow(
                            title = "Send alerts to my ntfy topic",
                            subtitle = "Off by default. With no topic URL the " +
                                "server never opens a socket for this.",
                            checked = state.pushEnabled,
                            onToggle = vm::togglePushEnabled,
                        )
                        SettingSwitchRow(
                            title = "Compression finished or failed",
                            subtitle = null,
                            checked = state.pushOnJobs,
                            onToggle = vm::togglePushOnJobs,
                        )
                        SettingSwitchRow(
                            title = "Line crossings and loitering",
                            subtitle = null,
                            checked = state.pushOnEvents,
                            onToggle = vm::togglePushOnEvents,
                        )
                        androidx.compose.foundation.layout.Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            TextButton(
                                onClick = vm::testPush,
                                enabled = !state.pushBusy,
                                modifier = Modifier.weight(1f),
                            ) { Text(if (state.pushBusy) "WORKING..." else "SEND TEST") }
                            Button(
                                onClick = vm::savePushConfig,
                                enabled = !state.pushBusy,
                                modifier = Modifier.weight(1f),
                            ) { Text("SAVE ALERTS") }
                        }
                        state.pushMessage?.let { msg ->
                            Text(
                                msg,
                                style = MaterialTheme.typography.bodyMedium,
                                color = if (state.pushOk) SvcsGreen else SvcsRed,
                            )
                        }
                        Text(
                            "Alerts carry the event kind, camera id, and class " +
                                "label only. No plate text, no file paths, no " +
                                "camera credentials.",
                            style = MaterialTheme.typography.labelSmall,
                            color = SvcsTextDim,
                        )
                    }
                }
            }

            // The phone app's own version, so nobody mistakes the server
            // version shown on the CONNECTED card for the app's.
            Text(
                "SVCS Mobile app " + org.svcs.mobile.BuildConfig.VERSION_NAME,
                style = MaterialTheme.typography.labelSmall,
                color = SvcsTextDim,
            )
        }
    }
}

/**
 * One labelled switch, used by the auto-compress toggle and by every push
 * switch. Extracted when the third hand-rolled Row of the same shape appeared.
 */
@Composable
private fun SettingSwitchRow(
    title: String,
    subtitle: String?,
    checked: Boolean,
    onToggle: () -> Unit,
) {
    androidx.compose.foundation.layout.Row(
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyMedium)
            subtitle?.let {
                Text(it, style = MaterialTheme.typography.labelSmall,
                    color = SvcsTextDim)
            }
        }
        androidx.compose.material3.Switch(checked = checked,
            onCheckedChange = { onToggle() })
    }
}

@Composable
private fun CapabilitiesCard(caps: Capabilities) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text("CONNECTED TO SERVER", style = MaterialTheme.typography.labelSmall,
                color = SvcsGreen)
            // This is the SERVER's version (the desktop install), not this
            // app's. The app's own version is printed at the foot of the
            // screen; showing a bare "SVCS 2.2.0" here read as the app version.
            Text("Server ${caps.app} ${caps.version}",
                style = MaterialTheme.typography.titleMedium)
            Text(caps.editionLabel, style = MaterialTheme.typography.bodyMedium,
                color = SvcsTextDim)
            val enabled = caps.features.filterValues { it }.keys.sorted()
            Text(
                "FEATURES: " + (enabled.joinToString(", ").ifEmpty { "none" }),
                style = MaterialTheme.typography.labelSmall,
                color = SvcsTextDim,
            )
            if (!caps.hasLive) {
                // The field edition registers no HLS blueprint at all, so the
                // LIVE tab must be hidden rather than 404 on every request.
                Text(
                    "This server has no live streaming, so the LIVE tab will " +
                        "be hidden.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = SvcsTextDim,
                )
            }
        }
    }
}
