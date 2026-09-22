package org.svcs.mobile.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import org.svcs.mobile.compress.CompressionRecord
import org.svcs.mobile.net.humanBytes
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * SAVED tab (Fall roadmap Phase 1.5): search and advanced filters over
 * everything this phone has compressed with the on-device compressor.
 * Distinct from the server-mode LIBRARY tab, which lists the desktop's
 * remote catalog over the network - this needs no pairing and no network.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1.5).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CompressLibraryScreen(vm: CompressLibraryViewModel) {
    val filters by vm.filters.collectAsState()
    val records by vm.visible.collectAsState()
    val context = LocalContext.current
    var pendingDelete by remember { mutableStateOf<CompressionRecord?>(null) }

    LaunchedEffect(Unit) { vm.reload() }

    Column(
        Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("SAVED", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(
            "Everything you've compressed on this phone. No server needed here either.",
            style = MaterialTheme.typography.bodySmall,
            color = SvcsTextDim,
        )

        OutlinedTextField(
            value = filters.query,
            onValueChange = vm::setQuery,
            label = { Text("Search by filename") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            DateFilter.entries.forEach { d ->
                FilterChip(
                    selected = filters.dateFilter == d,
                    onClick = { vm.setDateFilter(d) },
                    label = { Text(d.label) },
                )
            }
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = "video/hevc" in filters.codecFilter,
                onClick = { vm.toggleCodec("video/hevc") },
                label = { Text("H.265") },
            )
            FilterChip(
                selected = "video/avc" in filters.codecFilter,
                onClick = { vm.toggleCodec("video/avc") },
                label = { Text("H.264") },
            )
            FilterChip(
                selected = "QUALITY" in filters.modeFilter,
                onClick = { vm.toggleMode("QUALITY") },
                label = { Text("Quality mode") },
            )
            FilterChip(
                selected = "TARGET_SIZE" in filters.modeFilter,
                onClick = { vm.toggleMode("TARGET_SIZE") },
                label = { Text("Size target") },
            )
            FilterChip(
                selected = filters.fallbackOnly,
                onClick = { vm.setFallbackOnly(!filters.fallbackOnly) },
                label = { Text("Used fallback") },
            )
            FilterChip(
                selected = filters.smartCompressOnly,
                onClick = { vm.setSmartCompressOnly(!filters.smartCompressOnly) },
                label = { Text("Smart Compress") },
            )
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            LibrarySort.entries.forEach { s ->
                FilterChip(
                    selected = filters.sort == s,
                    onClick = { vm.setSort(s) },
                    label = { Text(s.label) },
                )
            }
        }

        if (records.isEmpty()) {
            Text(
                "Nothing here yet, or nothing matches these filters.",
                style = MaterialTheme.typography.bodyMedium,
                color = SvcsTextDim,
            )
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(records, key = { it.outputUri }) { record ->
                    LibraryRow(
                        record = record,
                        onPlay = {
                            val intent = Intent(Intent.ACTION_VIEW).apply {
                                setDataAndType(Uri.parse(record.outputUri), "video/mp4")
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            context.startActivity(intent)
                        },
                        onShare = {
                            val intent = Intent(Intent.ACTION_SEND).apply {
                                type = "video/mp4"
                                putExtra(Intent.EXTRA_STREAM, Uri.parse(record.outputUri))
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            context.startActivity(Intent.createChooser(intent, "Share compressed video"))
                        },
                        onDelete = { pendingDelete = record },
                    )
                }
            }
        }
    }

    pendingDelete?.let { record ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("Delete this video?") },
            text = { Text("${record.outputDisplayName} will be permanently deleted from this phone.") },
            confirmButton = {
                TextButton(onClick = { vm.delete(record); pendingDelete = null }) {
                    Text("Delete", color = SvcsRed)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun LibraryRow(
    record: CompressionRecord,
    onPlay: () -> Unit,
    onShare: () -> Unit,
    onDelete: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                record.outputDisplayName,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
            )
            val ratioText = if (record.originalSizeBytes > 0 && record.outputSizeBytes > 0) {
                val ratio = record.originalSizeBytes.toDouble() / record.outputSizeBytes.toDouble()
                "${humanBytes(record.originalSizeBytes)} -> ${humanBytes(record.outputSizeBytes)} " +
                    "(%.1fx smaller)".format(ratio)
            } else {
                humanBytes(record.outputSizeBytes)
            }
            Text(ratioText, style = MaterialTheme.typography.bodySmall, color = SvcsTextDim)
            val dateText = SimpleDateFormat("MMM d, yyyy - h:mm a", Locale.getDefault())
                .format(Date(record.timestampMs))
            val codecLabel = if (record.codecMime == "video/hevc") "H.265" else "H.264"
            Text(
                "$dateText - $codecLabel - ${record.presetLabel}",
                style = MaterialTheme.typography.bodySmall,
                color = SvcsTextDim,
            )
            if (record.usedFallback) {
                Text(
                    "Used the compatibility fallback",
                    style = MaterialTheme.typography.bodySmall,
                    color = SvcsRed,
                )
            }
            if (record.smartCompressUsed) {
                Text(
                    if (record.smartCompressActivityDetected == false) {
                        "Smart Compress: no activity found, compressed harder"
                    } else {
                        "Smart Compress: activity found, full bitrate used"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = SvcsTextDim,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onPlay) { Text("Play") }
                TextButton(onClick = onShare) { Text("Share") }
                TextButton(onClick = onDelete) { Text("Delete", color = SvcsRed) }
            }
        }
    }
}
