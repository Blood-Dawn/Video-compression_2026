package org.svcs.mobile.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/**
 * SVCS color tokens, in a dark palette and a light palette.
 *
 * The dark palette was originally generated from mobile/design/tokens/colors.css (imported
 * from the Claude Design project). As of the 2026-11 UI redesign, SvcsTextDim was lightened
 * and SvcsBorderCtl and SvcsAmberText were added by hand to fix contrast, and a light palette
 * was added. The old generator input does not know about any of this. Update both palettes
 * and docs/DESIGN_SYSTEM.md together, and keep the dashboard's CSS variables in step.
 * The design folder is no longer on this branch; recover it with
 * `git show 4558c5e:mobile/design/tokens/colors.css`.
 *
 * Call sites keep using the same names (SvcsBg, SvcsAmber and so on). Each name is a
 * composable getter that reads the active palette, so it can only be read from composable
 * code. In non-composable code, read the value in a composable first and pass it in.
 *
 * Light palette contrast, measured: body text 14:1 or better, dim text 5.7:1, every accent
 * 4.8:1 or better on all four surfaces, control border 4:1.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1); light palette 2026-11.
 */
@Immutable
class SvcsPalette(
    val bg: Color,
    val surface: Color,
    val surface2: Color,
    val surface3: Color,
    val border: Color,
    val borderBright: Color,
    val borderCtl: Color,
    val amber: Color,
    val amberDim: Color,
    val amberText: Color,
    val teal: Color,
    val green: Color,
    val yellow: Color,
    val purple: Color,
    val blue: Color,
    val orange: Color,
    val red: Color,
    val text: Color,
    val textDim: Color,
    val textBright: Color,
    val amberGlow: Color,
    val tealDim: Color,
    val greenDim: Color,
    val yellowDim: Color,
    val purpleDim: Color,
    val redDim: Color,
    // Opaque fills computed from the accents over the surfaces (see DerivedColors.kt).
    val amberContainer: Color,
    val redContainer: Color,
    val tealContainer: Color,
    val purpleContainer: Color,
    val onAmber: Color,
)

val SvcsDarkPalette = SvcsPalette(
    bg = Color(0xFF0A0E14),
    surface = Color(0xFF10192A),
    surface2 = Color(0xFF162238),
    surface3 = Color(0xFF1E3A52),
    border = Color(0xFF2A4466),
    borderBright = Color(0xFF3A5A7A),
    borderCtl = Color(0xFF5D7DA3), // inputs and buttons, 3.7:1 or better (redesign 2026-11)
    amber = Color(0xFFFFB900),
    amberDim = Color(0xFF8A6300),
    amberText = Color(0xFFD99A00), // dim amber that is readable as text, 7.9:1 (redesign 2026-11)
    teal = Color(0xFF1FD4C8),
    green = Color(0xFF2DD6A0),
    yellow = Color(0xFFFFC800),
    purple = Color(0xFFB888FF),
    blue = Color(0xFF5AA9FF),
    orange = Color(0xFFFF9E5E),
    red = Color(0xFFFF5555),
    text = Color(0xFFD8E8F5),
    textDim = Color(0xFF95A9C0), // was 0xFF7A8FA8 (3.55:1 on surface3); now 4.89:1
    textBright = Color(0xFFF0F8FF),
    amberGlow = Color(0x26FFB900),
    tealDim = Color(0x1F1FD4C8),
    greenDim = Color(0x1F2DD6A0),
    yellowDim = Color(0x1FFFC800),
    purpleDim = Color(0x24B888FF),
    redDim = Color(0x1FFF5555),
    amberContainer = Color(0xFF2B2410),
    redContainer = Color(0xFF34161C),
    tealContainer = Color(0xFF0F2B33),
    purpleContainer = Color(0xFF261F3A),
    onAmber = Color(0xFF0A0800),
)

val SvcsLightPalette = SvcsPalette(
    bg = Color(0xFFF3F6FA),
    surface = Color(0xFFFFFFFF),
    surface2 = Color(0xFFEAF0F7),
    surface3 = Color(0xFFE1E9F2),
    border = Color(0xFFB9C8DA),
    borderBright = Color(0xFF9DB2CB),
    borderCtl = Color(0xFF587394), // 4:1 or better on every surface
    amber = Color(0xFF8F5400), // darker than the dark theme's amber so it reads as text on white
    amberDim = Color(0xFFC99A4A),
    amberText = Color(0xFF7D4A00),
    teal = Color(0xFF08706A),
    green = Color(0xFF09694A),
    yellow = Color(0xFF6F5600),
    purple = Color(0xFF6A3FC2),
    blue = Color(0xFF0B5AA8),
    orange = Color(0xFFA34700),
    red = Color(0xFFB71C1C),
    text = Color(0xFF14233A),
    textDim = Color(0xFF475A73),
    textBright = Color(0xFF0A1626),
    amberGlow = Color(0x248F5400),
    tealDim = Color(0x1F08706A),
    greenDim = Color(0x1F09694A),
    yellowDim = Color(0x1F6F5600),
    purpleDim = Color(0x1F6A3FC2),
    redDim = Color(0x1AB71C1C),
    amberContainer = Color(0xFFEFE7DB),
    redContainer = Color(0xFFF8E8E8),
    tealContainer = Color(0xFFE1EEED),
    purpleContainer = Color(0xFFEDE8F8),
    onAmber = Color(0xFFFFFFFF),
)

val LocalSvcsPalette = staticCompositionLocalOf { SvcsDarkPalette }

// ---- Surfaces ----
val SvcsBg: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.bg
val SvcsSurface: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.surface
val SvcsSurface2: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.surface2
val SvcsSurface3: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.surface3

// ---- Borders ----
val SvcsBorder: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.border
val SvcsBorderBright: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.borderBright
val SvcsBorderCtl: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.borderCtl

// ---- Accents ----
val SvcsAmber: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.amber
val SvcsAmberDim: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.amberDim
val SvcsAmberText: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.amberText
val SvcsTeal: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.teal
val SvcsGreen: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.green
val SvcsYellow: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.yellow
val SvcsPurple: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.purple
val SvcsBlue: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.blue
val SvcsOrange: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.orange
val SvcsRed: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.red

// ---- Text ----
val SvcsText: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.text
val SvcsTextDim: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.textDim
val SvcsTextBright: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.textBright

// ---- Translucent accents (alpha baked in) ----
val SvcsAmberGlow: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.amberGlow
val SvcsTealDim: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.tealDim
val SvcsGreenDim: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.greenDim
val SvcsYellowDim: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.yellowDim
val SvcsPurpleDim: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.purpleDim
val SvcsRedDim: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.redDim
