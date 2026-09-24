package org.svcs.mobile.ui.components

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.dp

/**
 * SVCS line icons, drawn to match the imported design mockup's inline SVGs:
 * 24px grid, 1.6 stroke, round caps. HOME, LIBRARY, LIVE, METRICS and MORE
 * are the mockup's own path data; the rest follow the same rules.
 *
 * Hand-built ImageVectors rather than material-icons-extended: a dozen icons
 * don't justify the dependency, and the stock set's filled, rounded style
 * isn't the design's terminal line style anyway. Icon() tints them, so the
 * colors here are placeholders.
 *
 * Author: Bloodawn (KheivenD), 2026-09-23 (UI pass).
 */
object SvcsIcons {

    private fun icon(name: String, strokes: List<String>, fills: List<String> = emptyList()): ImageVector {
        val b = ImageVector.Builder(
            name = name,
            defaultWidth = 24.dp,
            defaultHeight = 24.dp,
            viewportWidth = 24f,
            viewportHeight = 24f,
        )
        strokes.forEach { d ->
            b.addPath(
                pathData = PathParser().parsePathString(d).toNodes(),
                fill = null,
                stroke = SolidColor(Color.Black),
                strokeLineWidth = 1.6f,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            )
        }
        fills.forEach { d ->
            b.addPath(pathData = PathParser().parsePathString(d).toNodes(), fill = SolidColor(Color.Black))
        }
        return b.build()
    }

    /** A circle as path data, for PathParser (which has no <circle>). */
    private fun circle(cx: Float, cy: Float, r: Float) =
        "M${cx - r},$cy a$r,$r 0 1,0 ${2 * r},0 a$r,$r 0 1,0 ${-2 * r},0"

    // ── Bottom navigation ────────────────────────────────────────────────
    /** Four corner arrows pointing in: squeezing a frame. */
    val Compress = icon(
        "Compress",
        listOf(
            "M4 4l5 5", "M9 4.8V9H4.8",
            "M20 4l-5 5", "M15 4.8V9h4.2",
            "M4 20l5-5", "M9 19.2V15H4.8",
            "M20 20l-5-5", "M15 19.2V15h4.2",
        ),
    )
    /** Clapperboard: a finished clip. */
    val Saved = icon("Saved", listOf("M4 9h16v11H4z", "M4 9l1.4-4.5 14.4 0L20 9", "M9.5 4.6L8 9", "M15 4.6L13.5 9"))
    val Home = icon("Home", listOf("M4 11l8-7 8 7", "M6 9.5V20h12V9.5"))
    val Library = icon("Library", listOf("M3 4h7v7H3z", "M14 4h7v7h-7z", "M3 14h7v7H3z", "M14 14h7v7h-7z"))
    val Live = icon("Live", listOf(circle(12f, 12f, 8f)), listOf(circle(12f, 12f, 2.4f)))
    /** A pulse line: something happened. */
    val Events = icon("Events", listOf("M3 12h4l2.5-6 5 12 2.5-6h4"))
    val Metrics = icon("Metrics", listOf("M5 20V11", "M12 20V4", "M19 20v-6"))
    /** Two stacked rack units: the paired desktop server (Server Mode). */
    val Server = icon(
        "Server",
        listOf("M4 4.5h16v6H4z", "M4 13.5h16v6H4z", "M11 7.5h6", "M11 16.5h6"),
        listOf(circle(7.5f, 7.5f, 1.1f), circle(7.5f, 16.5f, 1.1f)),
    )
    val More = icon("More", emptyList(), listOf(circle(5f, 12f, 1.4f), circle(12f, 12f, 1.4f), circle(19f, 12f, 1.4f)))

    // ── Actions ──────────────────────────────────────────────────────────
    /** Video camera: pick a video. */
    val Video = icon("Video", listOf("M3 6.5h12.5v11H3z", "M15.5 10.5l5.5-3.2v9.4l-5.5-3.2"))
    val Play = icon("Play", emptyList(), listOf("M8 5.5v13l10.5-6.5z"))
    val Share = icon("Share", listOf("M4.5 12.5v7h15v-7", "M12 4v11", "M8 7.8L12 4l4 3.8"))
    val Delete = icon("Delete", listOf("M5 7h14", "M10 4h4", "M7 7l1 13h8l1-13", "M10.5 11v5", "M13.5 11v5"))
    val Check = icon("Check", listOf("M5 12.5l4.5 4.5L19 7.5"))
    val Close = icon("Close", listOf("M6.5 6.5l11 11", "M17.5 6.5l-11 11"))
    val ChevronDown = icon("ChevronDown", listOf("M6 9.5l6 6 6-6"))
    val ChevronUp = icon("ChevronUp", listOf("M6 14.5l6-6 6 6"))
    val Search = icon("Search", listOf(circle(10.5f, 10.5f, 6f), "M15 15l5 5"))
    /** Three sliders: filters. */
    val Filter = icon("Filter", listOf("M4 7h16", "M7 12h10", "M10 17h4"))
    /** Four-point sparkle: Smart Compress. */
    val Smart = icon("Smart", listOf("M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9-1.9 5.1-1.9-5.1-5.1-1.9 5.1-1.9z", "M18.5 16v4", "M16.5 18h4"))
    val Mute = icon("Mute", listOf("M4 9.5h3.5L12 5.5v13l-4.5-4H4z", "M16 9.5l4.5 5", "M20.5 9.5l-4.5 5"))
    val Stop = icon("Stop", emptyList(), listOf("M7 7h10v10H7z"))
}
