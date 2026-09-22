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
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import org.svcs.mobile.net.humanBytes
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsSurface2
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * HOME tab (M2.3): what the server is doing, and what compression actually saved.
 *
 * The mockup's headline is "277.8x SMALLER". That number is real arithmetic over
 * an unreal quantity: the desktop computes it as
 * duration * width * height * 3 * fps, which is the clip as RAW UNCOMPRESSED
 * RGB. A camera never delivers raw RGB, it delivers H.264 already, so most of
 * that ratio is "video compression exists" and not "SVCS shrank your files".
 * Presenting it as a headline credits SVCS with something it did not do.
 *
 * So this screen shows a ratio ONLY over files SVCS compressed from a real
 * source file, where both sizes are genuinely known, and reports live recording
 * as a plain total with no ratio at all. When nothing has been compressed yet it
 * says so, rather than filling the space with a flattering number.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2.3).
 */
@Composable
fun HomeScreen(vm: HomeViewModel) {
    val s by vm.state.collectAsState()
    LaunchedEffect(Unit) { vm.start() }

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 12.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("SVCS", style = MaterialTheme.typography.displaySmall,
            modifier = Modifier.padding(top = 12.dp))
        s.error?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, color = SvcsRed)
        }

        // ── what the pipeline is doing right now ──
        Text("PIPELINE", style = MaterialTheme.typography.labelSmall, color = SvcsAmber,
            modifier = Modifier.padding(top = 6.dp))
        Card {
            Text(
                if (s.running) "RUNNING" else "IDLE",
                style = MaterialTheme.typography.titleMedium,
                color = if (s.running) SvcsGreen else SvcsTextDim,
            )
            if (s.running) {
                s.progressPct?.let { pct ->
                    LinearProgressIndicator(
                        progress = { (pct / 100.0).toFloat().coerceIn(0f, 1f) },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                }
                Text(
                    "${s.segmentCount} segments, ${s.frameCount} frames",
                    style = MaterialTheme.typography.labelSmall, color = SvcsTextDim,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
        }

        // ── the honest compression number ──
        Text("COMPRESSION SAVINGS", style = MaterialTheme.typography.labelSmall,
            color = SvcsAmber, modifier = Modifier.padding(top = 10.dp))
        if (s.measuredFiles > 0) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Stat("SAVED", humanBytes(s.savedBytes), Modifier.weight(1f),
                    accent = SvcsGreen)
                Stat("SMALLER",
                    s.ratio?.let { String.format("%.1fx", it) } ?: "n/a",
                    Modifier.weight(1f), accent = SvcsGreen)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Stat("FILES", s.measuredFiles.toString(), Modifier.weight(1f))
                Stat("NOW", humanBytes(s.measuredOutputBytes), Modifier.weight(1f))
            }
            Text(
                "Measured against the original files, ${humanBytes(s.measuredSourceBytes)} " +
                    "before compression.",
                style = MaterialTheme.typography.bodyMedium, color = SvcsTextDim,
            )
        } else {
            Card {
                Text("Nothing compressed yet",
                    style = MaterialTheme.typography.titleMedium, color = SvcsTextDim)
                Text(
                    "A savings figure appears once SVCS has compressed a file " +
                        "and both sizes are known. Recorded footage below has no " +
                        "original to compare against.",
                    style = MaterialTheme.typography.bodyMedium, color = SvcsTextDim,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }

        // ── recorded footage: totals only, deliberately no ratio ──
        Text("RECORDED FOOTAGE", style = MaterialTheme.typography.labelSmall,
            color = SvcsAmber, modifier = Modifier.padding(top = 10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Stat("ON DISK", humanBytes(s.recordedBytes), Modifier.weight(1f))
            Stat("SEGMENTS", s.recordedSegments.toString(), Modifier.weight(1f))
        }
        Text(
            "Live capture has no original file to compare against, so no " +
                "reduction is claimed for it.",
            style = MaterialTheme.typography.bodyMedium, color = SvcsTextDim,
            modifier = Modifier.padding(bottom = 20.dp),
        )
    }
}

@Composable
private fun Card(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .border(1.dp, SvcsBorder, RoundedCornerShape(2.dp))
            .background(SvcsSurface2)
            .padding(12.dp),
        content = content,
    )
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
