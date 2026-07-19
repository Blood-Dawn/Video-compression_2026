package org.svcs.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsSurface2
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * METRICS tab (M2.2).
 *
 * The design mockup shows a "POWER DURING ENCODING / server draw - avg watts"
 * tile. It is NOT built here, and that is deliberate rather than an omission:
 * nothing in the server measures wattage. /api/system_metrics exposes
 * psutil CPU, RAM and battery only, and no design capacity in Wh is read
 * anywhere, so watts cannot even be derived. Showing a fabricated number on a
 * screen an operator would use for hardware sizing is worse than showing
 * nothing, so the tile is replaced by CPU load, which is the real quantity the
 * server actually has.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2.2).
 */
@Composable
fun MetricsScreen(vm: MetricsViewModel) {
    val s by vm.state.collectAsState()
    LaunchedEffect(Unit) { vm.start() }

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 12.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("METRICS", style = MaterialTheme.typography.labelSmall, color = SvcsAmber,
            modifier = Modifier.padding(top = 12.dp))

        s.error?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, color = SvcsRed)
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Stat("CPU", s.cpuPct?.let { "${it.toInt()}%" } ?: "n/a", Modifier.weight(1f))
            Stat("RAM", s.ramPct?.let { "${it.toInt()}%" } ?: "n/a", Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Stat("BATTERY",
                s.batteryPct?.let { "${it.toInt()}%" } ?: "on mains",
                Modifier.weight(1f))
            Stat("PIPELINE", if (s.running) "RUNNING" else "IDLE", Modifier.weight(1f),
                accent = if (s.running) SvcsGreen else SvcsTextDim)
        }

        Text("STORED FOOTAGE", style = MaterialTheme.typography.labelSmall,
            color = SvcsAmber, modifier = Modifier.padding(top = 10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Stat("TOTAL", s.storageHuman ?: "n/a", Modifier.weight(1f))
            Stat("SEGMENTS", s.segments?.toString() ?: "n/a", Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Stat("HOURS", s.hours?.let { String.format("%.1f", it) } ?: "n/a",
                Modifier.weight(1f))
            Stat("WITH TARGETS", s.withTargets?.toString() ?: "n/a", Modifier.weight(1f))
        }

        // Say why the mockup's watts tile is missing, so the gap reads as a
        // decision rather than an unfinished screen.
        Text(
            "Power draw in watts is not shown: the server does not measure it. " +
                "CPU load above is the closest real quantity.",
            style = MaterialTheme.typography.bodyMedium,
            color = SvcsTextDim,
            modifier = Modifier.padding(top = 12.dp, bottom = 20.dp),
        )
    }
}

@Composable
private fun Stat(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    accent: androidx.compose.ui.graphics.Color = SvcsAmber,
) {
    Column(
        modifier
            .border(1.dp, SvcsBorder, RoundedCornerShape(2.dp))
            .background(SvcsSurface2)
            .padding(12.dp),
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
        Text(value, style = MaterialTheme.typography.titleMedium, color = accent)
    }
}
