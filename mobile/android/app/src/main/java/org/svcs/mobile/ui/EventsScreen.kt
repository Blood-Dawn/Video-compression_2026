package org.svcs.mobile.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import org.svcs.mobile.net.ZoneLine
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsSurface2
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * EVENTS tab (R6 Track A): behavior events + the zone/line editor.
 *
 * The list half polls /api/events/recent; the editor half draws normalized
 * geometry by drag on a 16:9 canvas and POSTs /api/zones. No backdrop frame
 * in v1 - geometry is normalized, so the grid stands in for the scene until
 * a still-frame endpoint exists; the config applies to the NEXT run either
 * way and the API says so.
 *
 * Author: Bloodawn (KheivenD), 2026-08-17 (R6 Track A).
 */
@Composable
fun EventsScreen(vm: EventsViewModel) {
    val state by vm.state.collectAsState()
    var editing by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Text("EVENTS", style = MaterialTheme.typography.labelSmall, color = SvcsAmber,
            modifier = Modifier.padding(top = 12.dp, bottom = 2.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            EditorChip("RECENT", !editing) { editing = false }
            EditorChip("EDIT ZONES", editing) { editing = true }
        }
        if (editing) {
            ZoneEditor(vm)
        } else {
            EventsList(vm)
        }
    }
}

@Composable
private fun EventsList(vm: EventsViewModel) {
    val state by vm.state.collectAsState()
    val subtitle = when {
        state.error != null -> state.error!!
        state.events.isEmpty() ->
            "No behavior events yet. Draw a line or zone under EDIT ZONES, " +
                "then compress a clip with motion for that camera."
        else -> "${state.events.size} recent"
    }
    Text(subtitle, style = MaterialTheme.typography.bodyMedium,
        color = if (state.error != null) SvcsRed else SvcsTextDim,
        modifier = Modifier.padding(vertical = 6.dp))
    LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(state.events) { ev ->
            Column(
                Modifier.fillMaxWidth()
                    .border(1.dp, SvcsBorder, RoundedCornerShape(2.dp))
                    .background(SvcsSurface2).padding(10.dp),
            ) {
                Text(ev.headline(), style = MaterialTheme.typography.bodyMedium,
                    color = if (ev.kind == "loitering") SvcsAmber else SvcsGreen)
                Text("${ev.cameraId}  ${ev.wallTime}",
                    style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
            }
        }
    }
}

@Composable
private fun ZoneEditor(vm: EventsViewModel) {
    val state by vm.state.collectAsState()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        OutlinedTextField(
            value = state.editorCamera,
            onValueChange = vm::onCameraChanged,
            label = { Text("CAMERA ID") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(vertical = 8.dp),
        ) {
            EditorChip("LOAD", false) { vm.loadZones() }
            EditorChip("ZONE", state.drawMode == "zone") { vm.setDrawMode("zone") }
            EditorChip("LINE", state.drawMode == "line") { vm.setDrawMode("line") }
            EditorChip("CLEAR", false) { vm.clearGeometry() }
            EditorChip("SAVE", false) { vm.saveZones() }
        }
        Text(
            "Drag on the canvas: ZONE draws an exclude box (ignored area), " +
                "LINE draws a crossing line. Applies to the next run.",
            style = MaterialTheme.typography.labelSmall, color = SvcsTextDim,
        )
        state.editorMessage?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium, color = SvcsGreen,
                modifier = Modifier.padding(vertical = 4.dp))
        }

        var canvasSize by remember { mutableStateOf(Size.Zero) }
        var dragStart by remember { mutableStateOf<Offset?>(null) }
        var dragNow by remember { mutableStateOf<Offset?>(null) }

        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(16f / 9f)
                .padding(top = 8.dp)
                .background(Color(0xFF10151C))
                .border(1.dp, SvcsBorder)
                .pointerInput(state.drawMode) {
                    detectDragGestures(
                        onDragStart = { o -> dragStart = o; dragNow = o },
                        onDrag = { change, _ -> dragNow = change.position },
                        onDragEnd = {
                            val s = dragStart
                            val e = dragNow
                            if (s != null && e != null && canvasSize != Size.Zero) {
                                vm.addGeometry(
                                    s.x / canvasSize.width, s.y / canvasSize.height,
                                    e.x / canvasSize.width, e.y / canvasSize.height,
                                )
                            }
                            dragStart = null; dragNow = null
                        },
                    )
                },
        ) {
            canvasSize = size
            // Rule-of-thirds grid so the blank canvas still reads as a frame.
            val grid = Color(0xFF223041)
            for (i in 1..2) {
                drawLine(grid, Offset(size.width * i / 3f, 0f),
                    Offset(size.width * i / 3f, size.height))
                drawLine(grid, Offset(0f, size.height * i / 3f),
                    Offset(size.width, size.height * i / 3f))
            }
            // Existing exclude zones: red fill.
            state.editorExcludes.forEach { r ->
                val x1 = (minOf(r[0], r[2]) * size.width).toFloat()
                val y1 = (minOf(r[1], r[3]) * size.height).toFloat()
                val x2 = (maxOf(r[0], r[2]) * size.width).toFloat()
                val y2 = (maxOf(r[1], r[3]) * size.height).toFloat()
                drawRect(Color(0x55FF5555), Offset(x1, y1), Size(x2 - x1, y2 - y1))
            }
            // Crossing lines: amber.
            state.editorLines.forEach { l ->
                if (l.line.size == 4) {
                    drawLine(Color(0xFFFFB300),
                        Offset((l.line[0] * size.width).toFloat(),
                            (l.line[1] * size.height).toFloat()),
                        Offset((l.line[2] * size.width).toFloat(),
                            (l.line[3] * size.height).toFloat()),
                        strokeWidth = 6f)
                }
            }
            // Live drag preview.
            val s = dragStart
            val e = dragNow
            if (s != null && e != null) {
                if (state.drawMode == "line") {
                    drawLine(Color(0xFFFFE082), s, e, strokeWidth = 5f)
                } else {
                    drawRect(Color(0x338888FF),
                        Offset(minOf(s.x, e.x), minOf(s.y, e.y)),
                        Size(kotlin.math.abs(e.x - s.x), kotlin.math.abs(e.y - s.y)))
                }
            }
        }
        Text(
            "${state.editorExcludes.size} zone(s), ${state.editorLines.size} line(s)",
            style = MaterialTheme.typography.labelSmall, color = SvcsTextDim,
            modifier = Modifier.padding(vertical = 6.dp),
        )
    }
}

@Composable
private fun EditorChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        label,
        style = MaterialTheme.typography.labelSmall,
        color = if (selected) SvcsAmber else SvcsTextDim,
        modifier = Modifier
            .border(1.dp, if (selected) SvcsAmber else SvcsBorder, RoundedCornerShape(2.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}
