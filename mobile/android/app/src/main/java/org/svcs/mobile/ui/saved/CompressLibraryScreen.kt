package org.svcs.mobile.ui.saved

import android.net.Uri
import android.util.Size
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import org.svcs.mobile.compress.CompressionRecord
import org.svcs.mobile.ui.components.SvcsChip
import org.svcs.mobile.ui.components.SvcsIcons
import org.svcs.mobile.ui.components.SvcsPanel
import org.svcs.mobile.ui.components.SvcsSectionLabel
import org.svcs.mobile.ui.components.SvcsStat
import org.svcs.mobile.ui.components.SvcsTag
import org.svcs.mobile.ui.components.VideoThumbnail
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsDisplay
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsMono
import org.svcs.mobile.ui.theme.SvcsOrange
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTeal
import org.svcs.mobile.ui.theme.SvcsText
import org.svcs.mobile.ui.theme.SvcsTextBright
import org.svcs.mobile.ui.theme.SvcsTextDim
import org.svcs.mobile.ui.VideoIntents
import org.svcs.mobile.ui.humanBytes

/**
 * SAVED tab (Fall roadmap Phase 1.5): search and advanced filters over
 * everything this phone has compressed with the on-device compressor.
 * Distinct from the server-mode LIBRARY tab, which lists the desktop's
 * remote catalog over the network - this needs no pairing and no network.
 *
 * 2026-09-23 UI pass: totals up top, search, and the filter chips folded
 * behind a FILTERS toggle (with a count of active filters) so the first
 * screen is videos, not four rows of chips. Rows show the saving as a
 * badge and act through icon buttons.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1.5); UI pass 2026-09-23.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CompressLibraryScreen(vm: CompressLibraryViewModel) {
    val filters by vm.filters.collectAsState()
    val records by vm.visible.collectAsState()
    val context = LocalContext.current
    var pendingDelete by remember { mutableStateOf<CompressionRecord?>(null) }
    var showFilters by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.reload() }

    val activeFilters = listOf(
        filters.dateFilter != DateFilter.ALL,
        filters.codecFilter.isNotEmpty(),
        filters.modeFilter.isNotEmpty(),
        filters.fallbackOnly,
        filters.smartCompressOnly,
    ).count { it }
    val totalSaved = records.sumOf {
        if (it.originalSizeBytes > 0 && it.outputSizeBytes > 0) (it.originalSizeBytes - it.outputSizeBytes).coerceAtLeast(0) else 0L
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Column {
                Text("SAVED", style = MaterialTheme.typography.titleLarge, color = SvcsTextBright)
                Text("EVERYTHING COMPRESSED ON THIS PHONE", style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
            }
        }
        if (records.isNotEmpty() || activeFilters > 0 || filters.query.isNotBlank()) {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    SvcsStat(
                        label = if (activeFilters > 0 || filters.query.isNotBlank()) "Matching" else "Videos",
                        value = records.size.toString(),
                        accent = SvcsTeal,
                        modifier = Modifier.weight(1f),
                    )
                    SvcsStat(
                        label = "Space saved",
                        value = humanBytes(totalSaved),
                        accent = SvcsGreen,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
        item {
            OutlinedTextField(
                value = filters.query,
                onValueChange = vm::setQuery,
                placeholder = { Text("Search by filename") },
                leadingIcon = { Icon(SvcsIcons.Search, contentDescription = null, tint = SvcsTextDim, modifier = Modifier.size(20.dp)) },
                singleLine = true,
                shape = RoundedCornerShape(2.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = SvcsAmber,
                    unfocusedBorderColor = SvcsBorder,
                    cursorColor = SvcsAmber,
                ),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ToggleButton(
                    text = if (activeFilters > 0) "Filters ($activeFilters)" else "Filters",
                    icon = if (showFilters) SvcsIcons.ChevronUp else SvcsIcons.Filter,
                    active = activeFilters > 0 || showFilters,
                    onClick = { showFilters = !showFilters },
                )
                Spacer(Modifier.weight(1f))
                // Tap to cycle the sort: one compact control instead of a row.
                val next = LibrarySort.entries[(filters.sort.ordinal + 1) % LibrarySort.entries.size]
                ToggleButton(
                    text = filters.sort.label,
                    icon = SvcsIcons.ChevronDown,
                    active = false,
                    onClick = { vm.setSort(next) },
                )
            }
        }
        item {
            AnimatedVisibility(
                visible = showFilters,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut(),
            ) {
                SvcsPanel(modifier = Modifier.fillMaxWidth(), contentPadding = 12.dp) {
                    SvcsSectionLabel("When")
                    Spacer(Modifier.height(6.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        DateFilter.entries.forEach { d ->
                            SvcsChip(d.label, selected = filters.dateFilter == d, onClick = { vm.setDateFilter(d) })
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    SvcsSectionLabel("How it was compressed")
                    Spacer(Modifier.height(6.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        SvcsChip("H.265", "video/hevc" in filters.codecFilter, { vm.toggleCodec("video/hevc") })
                        SvcsChip("H.264", "video/avc" in filters.codecFilter, { vm.toggleCodec("video/avc") })
                        SvcsChip("Quality", "QUALITY" in filters.modeFilter, { vm.toggleMode("QUALITY") })
                        SvcsChip("Size limit", "TARGET_SIZE" in filters.modeFilter, { vm.toggleMode("TARGET_SIZE") })
                        SvcsChip("Smart Compress", filters.smartCompressOnly, { vm.setSmartCompressOnly(!filters.smartCompressOnly) })
                        SvcsChip("Used fallback", filters.fallbackOnly, { vm.setFallbackOnly(!filters.fallbackOnly) })
                    }
                }
            }
        }

        if (records.isEmpty()) {
            item {
                SvcsPanel(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        if (activeFilters > 0 || filters.query.isNotBlank()) "NO MATCHES" else "NOTHING YET",
                        fontFamily = SvcsDisplay,
                        fontSize = 26.sp,
                        color = SvcsTextBright,
                    )
                    Text(
                        if (activeFilters > 0 || filters.query.isNotBlank()) {
                            "Nothing matches these filters. Loosen them or clear the search."
                        } else {
                            "Videos you compress on the COMPRESS tab show up here, with how much space each one saved."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = SvcsTextDim,
                    )
                }
            }
        } else {
            items(records, key = { it.outputUri }) { record ->
                LibraryRow(
                    record = record,
                    onPlay = { VideoIntents.play(context, Uri.parse(record.outputUri)) },
                    onShare = { VideoIntents.share(context, Uri.parse(record.outputUri)) },
                    onDelete = { pendingDelete = record },
                )
            }
        }
    }

    pendingDelete?.let { record ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("DELETE THIS VIDEO?", fontFamily = SvcsDisplay, fontSize = 24.sp) },
            text = { Text("${record.outputDisplayName} will be permanently deleted from this phone.") },
            confirmButton = {
                TextButton(onClick = { vm.delete(record); pendingDelete = null }) {
                    Text("DELETE", color = SvcsRed)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) { Text("CANCEL", color = SvcsText) }
            },
        )
    }
}

@Composable
private fun ToggleButton(text: String, icon: ImageVector, active: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(2.dp)
    Row(
        Modifier
            .clip(shape)
            .border(1.dp, if (active) SvcsAmber else SvcsBorder, shape)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = if (active) SvcsAmber else SvcsTextDim, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(8.dp))
        Text(text.uppercase(), style = MaterialTheme.typography.labelLarge, color = if (active) SvcsAmber else SvcsText)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LibraryRow(
    record: CompressionRecord,
    onPlay: () -> Unit,
    onShare: () -> Unit,
    onDelete: () -> Unit,
) {
    val known = record.originalSizeBytes > 0 && record.outputSizeBytes > 0
    val savedPct = if (known) ((1.0 - record.outputSizeBytes.toDouble() / record.originalSizeBytes) * 100).toInt() else null

    SvcsPanel(modifier = Modifier.fillMaxWidth(), contentPadding = 10.dp) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.clickable(onClick = onPlay)) {
                VideoThumbnail(Uri.parse(record.outputUri), Modifier.size(84.dp))
                Box(
                    Modifier.align(Alignment.Center).size(30.dp).clip(RoundedCornerShape(50)).background(Color(0x99000000)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(SvcsIcons.Play, contentDescription = "Play", tint = Color.White, modifier = Modifier.size(16.dp))
                }
            }
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.Top) {
                    Text(
                        record.originalName ?: record.outputDisplayName,
                        style = MaterialTheme.typography.titleSmall,
                        color = SvcsTextBright,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    if (savedPct != null) {
                        Spacer(Modifier.width(8.dp))
                        Text(
                            if (savedPct >= 0) "-$savedPct%" else "+${-savedPct}%",
                            fontFamily = SvcsDisplay,
                            fontSize = 22.sp,
                            lineHeight = 22.sp,
                            color = if (savedPct >= 0) SvcsGreen else SvcsOrange,
                        )
                    }
                }
                Text(
                    if (known) "${humanBytes(record.originalSizeBytes)}  ->  ${humanBytes(record.outputSizeBytes)}"
                    else humanBytes(record.outputSizeBytes),
                    fontFamily = SvcsMono,
                    fontSize = 11.5.sp,
                    color = SvcsText,
                )
                val date = SimpleDateFormat("MMM d, h:mm a", Locale.getDefault()).format(Date(record.timestampMs))
                val codec = if (record.codecMime == "video/hevc") "H.265" else "H.264"
                Text(
                    date.uppercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = SvcsTextDim,
                    maxLines = 1,
                )
                Spacer(Modifier.height(6.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    SvcsTag(codec, SvcsTextDim)
                    SvcsTag(record.presetLabel, SvcsTextDim)
                    if (record.smartCompressUsed) {
                        SvcsTag(
                            when {
                                record.smartCompressActivityDetected == false -> "Smart: squeezed"
                                record.roiRegions > 0 -> "Smart: regions"
                                else -> "Smart: kept quality"
                            },
                            SvcsAmber,
                        )
                    }
                    if (record.usedFallback) SvcsTag("Fallback", SvcsOrange)
                }
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    RowAction(SvcsIcons.Share, "Share", SvcsText, onShare)
                    RowAction(SvcsIcons.Delete, "Delete", SvcsRed, onDelete)
                }
            }
        }
    }
}

@Composable
private fun RowAction(icon: ImageVector, label: String, color: Color, onClick: () -> Unit) {
    Row(
        Modifier
            .clip(RoundedCornerShape(2.dp))
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = color)
    }
}
