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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
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
fun ServerSettingsScreen(vm: ServerSettingsViewModel = viewModel()) {
    val state by vm.state.collectAsState()

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
                Button(
                    onClick = vm::save,
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("SAVE") }
            }
        }
    }
}

@Composable
private fun CapabilitiesCard(caps: Capabilities) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text("CONNECTED", style = MaterialTheme.typography.labelSmall,
                color = SvcsGreen)
            Text("${caps.app} ${caps.version}",
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
