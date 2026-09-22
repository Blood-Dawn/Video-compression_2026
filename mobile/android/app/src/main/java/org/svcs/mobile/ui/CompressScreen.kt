package org.svcs.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import org.svcs.mobile.compress.CompressionMode
import org.svcs.mobile.compress.QualityPresets
import org.svcs.mobile.compress.SizePresets
import org.svcs.mobile.compress.VideoCodecChoice
import org.svcs.mobile.net.humanBytes
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * COMPRESS tab (Fall roadmap Phase 1): the standalone, server-free compressor.
 *
 * This is the app's new primary surface - it needs no paired desktop, no
 * network at all. Everything else the app does (LIBRARY, LIVE, EVENTS,
 * METRICS) stays behind pairing as "Server Mode"; this does not, by design,
 * per STANDALONE-COMPRESSOR-ROADMAP.md section 3.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CompressScreen(vm: CompressViewModel) {
    val s by vm.state.collectAsState()

    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri -> uri?.let(vm::onVideoPicked) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("COMPRESS", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(
            "Compresses a video entirely on this phone. No server, no upload, " +
                "no internet needed.",
            style = MaterialTheme.typography.bodySmall,
            color = SvcsTextDim,
        )

        Button(
            onClick = { pickVideo.launch(arrayOf("video/*")) },
            modifier = Modifier.fillMaxWidth(),
            enabled = s.phase != org.svcs.mobile.ui.JobPhase.RUNNING,
        ) {
            Text(if (s.pickedUri == null) "Choose a video" else "Choose a different video")
        }

        s.pickedName?.let { name ->
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(name, style = MaterialTheme.typography.bodyMedium)
                val sizeText = if (s.pickedSizeBytes >= 0) humanBytes(s.pickedSizeBytes) else "unknown size"
                val durationText = if (s.durationMs > 0) {
                    val totalSec = s.durationMs / 1000
                    "%d:%02d".format(totalSec / 60, totalSec % 60)
                } else "unknown length"
                Text("$sizeText - $durationText", style = MaterialTheme.typography.bodySmall, color = SvcsTextDim)
            }
        }

        if (s.pickedUri != null && s.phase != org.svcs.mobile.ui.JobPhase.RUNNING) {
            Text("Quality", style = MaterialTheme.typography.labelLarge)
            // FlowRow, not Row: a plain Row never wraps, so once the chip
            // labels stop fitting on one line the extras get pushed off the
            // right edge of the screen instead of showing up at all - that
            // was the "only Discord shows" bug. Wrapping onto more lines
            // also means adding presets later can't reintroduce it.
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                QualityPresets.ALL.forEach { preset ->
                    val selected = (s.mode as? CompressionMode.Quality)?.preset == preset
                    FilterChip(
                        selected = selected,
                        onClick = { vm.setQualityPreset(preset) },
                        label = { Text(preset.label) },
                    )
                }
            }

            Text("Or fit under a size limit", style = MaterialTheme.typography.labelLarge)
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                SizePresets.ALL.forEach { preset ->
                    val selected = s.customSizeText.isEmpty() &&
                        (s.mode as? CompressionMode.TargetSize)?.preset == preset
                    FilterChip(
                        selected = selected,
                        onClick = { vm.setSizePreset(preset) },
                        label = { Text(preset.label) },
                    )
                }
            }
            OutlinedTextField(
                value = s.customSizeText,
                onValueChange = vm::setCustomSizeText,
                label = { Text("Or type an exact size (MB)") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            Text("Format", style = MaterialTheme.typography.labelLarge)
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                VideoCodecChoice.entries.forEach { codec ->
                    FilterChip(
                        selected = s.codec == codec,
                        onClick = { vm.setCodec(codec) },
                        label = { Text(codec.label) },
                    )
                }
            }

            Button(
                onClick = vm::startCompress,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = SvcsGreen),
            ) {
                Text("Compress")
            }
        }

        if (s.phase == org.svcs.mobile.ui.JobPhase.RUNNING) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Compressing... ${s.progressPercent}%", style = MaterialTheme.typography.bodyMedium)
                LinearProgressIndicator(
                    progress = { s.progressPercent / 100f },
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedButton(onClick = vm::cancel, modifier = Modifier.fillMaxWidth()) {
                    Text("Cancel")
                }
            }
        }

        if (s.phase == org.svcs.mobile.ui.JobPhase.DONE) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Done", style = MaterialTheme.typography.titleMedium, color = SvcsGreen)
                if (s.pickedSizeBytes > 0 && s.outputBytes > 0) {
                    val ratio = s.pickedSizeBytes.toDouble() / s.outputBytes.toDouble()
                    Text(
                        "${humanBytes(s.pickedSizeBytes)} -> ${humanBytes(s.outputBytes)} " +
                            "(%.1fx smaller)".format(ratio),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                if (s.usedFallback) {
                    Text(
                        "This device's encoder needed a safer resolution/codec " +
                            "to finish, so quality may be lower than requested.",
                        style = MaterialTheme.typography.bodySmall,
                        color = SvcsTextDim,
                    )
                }
                Text("Saved to Movies/SVCS.", style = MaterialTheme.typography.bodySmall, color = SvcsTextDim)
                OutlinedButton(onClick = vm::reset, modifier = Modifier.fillMaxWidth()) {
                    Text("Compress another")
                }
            }
        }

        if (s.phase == org.svcs.mobile.ui.JobPhase.FAILED) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("Compression failed", style = MaterialTheme.typography.titleMedium, color = SvcsRed)
                Text(s.error ?: "Unknown error", style = MaterialTheme.typography.bodySmall, color = SvcsTextDim)
                OutlinedButton(onClick = vm::reset, modifier = Modifier.fillMaxWidth()) {
                    Text("Try again")
                }
            }
        }
    }
}
