package org.svcs.mobile.ui.server.cam

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import org.svcs.mobile.net.SecurityCamClip
import org.svcs.mobile.securitycam.SecurityCamBus
import org.svcs.mobile.securitycam.SecurityCamService
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTextDim
import org.svcs.mobile.ui.theme.SvcsYellow

/**
 * SECURITY CAM: turn this phone into a camera that sends short clips to the
 * desktop, which compresses them as they arrive.
 *
 * The clip length and compression mode are set on the desktop (its Security
 * cam tab) and only shown here, so there is one place to change them.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, roadmap 13.1).
 */
@Composable
fun SecurityCamScreen(vm: SecurityCamViewModel) {
    val ui by vm.state.collectAsState()
    val cam by SecurityCamBus.status.collectAsState()
    val context = LocalContext.current
    LaunchedEffect(Unit) { vm.start() }

    val cameraGranted = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
        PackageManager.PERMISSION_GRANTED
    val clipSeconds = ui.info?.segmentSeconds ?: 600
    val linked = ui.linkError == null && ui.info != null

    val notifyLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) {
            if (Build.VERSION.SDK_INT >= 33) notifyLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            SecurityCamService.start(context, clipSeconds)
        }
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Security cam", style = MaterialTheme.typography.titleLarge)
        Text(
            "This phone records short clips and sends each one to the desktop, " +
                "which compresses it when it arrives.",
            color = SvcsTextDim,
        )

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Before you start", style = MaterialTheme.typography.titleMedium)
                CheckRow(
                    linked,
                    if (linked) "Linked to the desktop" else (ui.linkError ?: "Checking the desktop..."),
                )
                CheckRow(cameraGranted, if (cameraGranted) "Camera allowed" else "Camera not allowed yet (asked when you start)")
                CheckRow(null, "Plug the phone in and point it where you want. Recording keeps going with the screen off.")
            }
        }

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Clip length", style = MaterialTheme.typography.titleMedium)
                Text(clipLengthLabel(clipSeconds), style = MaterialTheme.typography.headlineSmall)
                Text("Change it on the desktop, under its Security cam tab.", color = SvcsTextDim)
            }
        }

        if (cam.running) {
            Button(
                onClick = { SecurityCamService.stop(context) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Stop recording") }
            Text(
                "Recording. This clip is sent in ${countdownLabel(cam.secondsLeft)}.",
                color = SvcsGreen,
            )
        } else {
            Button(
                onClick = {
                    if (cameraGranted) SecurityCamService.start(context, clipSeconds)
                    else cameraLauncher.launch(Manifest.permission.CAMERA)
                },
                enabled = linked,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Start recording") }
        }
        cam.error?.let { Text(it, color = SvcsRed) }

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("This phone", style = MaterialTheme.typography.titleMedium)
                Text("Recorded this session: ${cam.clipsRecorded}")
                Text("Sent: ${ui.counts.sent}   Waiting: ${ui.counts.waiting}   Failed: ${ui.counts.failed}")
                if (ui.counts.failed > 0) {
                    Text("A failed clip was dropped after the phone gave up reaching the desktop.", color = SvcsYellow)
                }
            }
        }

        val recent = ui.info?.recent.orEmpty()
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Compressed on the desktop", style = MaterialTheme.typography.titleMedium)
                if (recent.isEmpty()) {
                    Text("Nothing yet. Clips show up here once the desktop has compressed them.", color = SvcsTextDim)
                } else {
                    recent.take(6).forEach { Text(clipLine(it)) }
                }
            }
        }
    }
}

@Composable
private fun CheckRow(ok: Boolean?, text: String) {
    val mark = when (ok) { true -> "[x]"; false -> "[ ]"; null -> "[i]" }
    Text("$mark $text", color = if (ok == false) SvcsYellow else MaterialTheme.colorScheme.onSurface)
}

/** One clip as "name: 212.4 MB to 81.3 MB (62% saved)" using the desktop's real sizes. */
fun clipLine(c: SecurityCamClip): String {
    val before = c.beforeMb
    val after = c.afterMb
    if (before == null || after == null) return "${c.name}: ${c.verdict}"
    val pct = c.savedPct?.let { " (${"%.0f".format(it)}% saved)" }.orEmpty()
    return "${c.name}: ${"%.1f".format(before)} MB to ${"%.1f".format(after)} MB$pct"
}
