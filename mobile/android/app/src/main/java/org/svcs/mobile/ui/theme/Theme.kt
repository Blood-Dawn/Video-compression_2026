package org.svcs.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import org.svcs.mobile.R

/**
 * SVCS theme.
 *
 * Dark only, on purpose. The design system is explicit that this is a
 * "dark-first surveillance terminal", and every token is authored for it;
 * there is no light palette to fall back to. isSystemInDarkTheme() is
 * deliberately ignored rather than silently producing an unstyled light screen.
 *
 * 2026-09-23 UI pass: the three design families are now bundled (res/font,
 * OFL-1.1, license texts in assets/licenses) instead of the platform-default
 * placeholders, and the color scheme covers every Material 3 role. The
 * earlier scheme set about a dozen roles, so Material filled the rest
 * (selected chips, cards, switch tracks, the nav indicator) from its own
 * baseline purple palette, which is where the stray lavender greys on every
 * screen came from.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1); fonts + full scheme 2026-09-23.
 */

/** Bebas Neue: display numbers and headings. Uppercase-only face. */
val SvcsDisplay = FontFamily(Font(R.font.bebas_neue_regular, FontWeight.Normal))

/** Space Mono: labels, data, anything terminal-flavoured. */
val SvcsMono = FontFamily(
    Font(R.font.space_mono_regular, FontWeight.Normal),
    Font(R.font.space_mono_bold, FontWeight.Bold),
)

/** Outfit: readable body copy. */
val SvcsBody = FontFamily(
    Font(R.font.outfit_regular, FontWeight.Normal),
    Font(R.font.outfit_medium, FontWeight.Medium),
    Font(R.font.outfit_semibold, FontWeight.SemiBold),
    Font(R.font.outfit_bold, FontWeight.Bold),
)

// Amber at ~15% over the surfaces: the design's "amber glow" fill, made
// opaque so it composites the same on every surface level.
private val SvcsAmberContainer = Color(0xFF2B2410)
private val SvcsTealContainer = Color(0xFF0F2B33)
private val SvcsPurpleContainer = Color(0xFF261F3A)
private val SvcsRedContainer = Color(0xFF34161C)

private val SvcsColorScheme = darkColorScheme(
    primary = SvcsAmber,
    onPrimary = Color(0xFF0A0800),
    primaryContainer = SvcsAmberContainer,
    onPrimaryContainer = SvcsAmber,
    inversePrimary = SvcsAmberDim,
    secondary = SvcsTeal,
    onSecondary = SvcsBg,
    // Selected chips and the nav indicator use secondaryContainer: keep them
    // on the amber accent, which is what the design marks "active" with.
    secondaryContainer = SvcsAmberContainer,
    onSecondaryContainer = SvcsAmber,
    tertiary = SvcsPurple,
    onTertiary = SvcsBg,
    tertiaryContainer = SvcsPurpleContainer,
    onTertiaryContainer = SvcsPurple,
    background = SvcsBg,
    onBackground = SvcsText,
    surface = SvcsBg,
    onSurface = SvcsText,
    surfaceVariant = SvcsSurface2,
    onSurfaceVariant = SvcsTextDim,
    surfaceTint = Color.Transparent,
    inverseSurface = SvcsText,
    inverseOnSurface = SvcsBg,
    error = SvcsRed,
    onError = SvcsBg,
    errorContainer = SvcsRedContainer,
    onErrorContainer = SvcsRed,
    outline = SvcsBorder,
    outlineVariant = SvcsBorder,
    scrim = Color.Black,
    surfaceBright = SvcsSurface3,
    surfaceDim = SvcsBg,
    surfaceContainerLowest = SvcsBg,
    surfaceContainerLow = SvcsSurface,
    surfaceContainer = SvcsSurface,
    surfaceContainerHigh = SvcsSurface2,
    surfaceContainerHighest = SvcsSurface2,
)

/**
 * Sizes and tracking from tokens/typography.css (1rem = 16sp), families now
 * real. Display roles are Bebas Neue, label roles Space Mono, body and title
 * roles Outfit. labelLarge is what Material buttons and chips render with,
 * so it's the mono chip/button label rather than a heading.
 */
private val SvcsTypography = Typography(
    displayLarge = TextStyle(fontFamily = SvcsDisplay, fontSize = 72.sp, lineHeight = 72.sp, letterSpacing = 0.02.em),
    // --text-3xl hero display.
    displayMedium = TextStyle(fontFamily = SvcsDisplay, fontSize = 57.6.sp, lineHeight = 58.sp, letterSpacing = 0.02.em),
    // --text-2xl stat values.
    displaySmall = TextStyle(fontFamily = SvcsDisplay, fontSize = 41.6.sp, lineHeight = 44.sp, letterSpacing = 0.04.em),
    headlineLarge = TextStyle(fontFamily = SvcsDisplay, fontSize = 32.sp, lineHeight = 36.sp, letterSpacing = 0.04.em),
    // --text-xl (logo).
    headlineMedium = TextStyle(fontFamily = SvcsDisplay, fontSize = 28.8.sp, lineHeight = 32.sp, letterSpacing = 0.04.em),
    // --text-lg sub headings.
    headlineSmall = TextStyle(fontFamily = SvcsDisplay, fontSize = 22.4.sp, lineHeight = 26.sp, letterSpacing = 0.05.em),
    // Screen titles ("COMPRESS", "SAVED").
    titleLarge = TextStyle(fontFamily = SvcsDisplay, fontSize = 30.sp, lineHeight = 32.sp, letterSpacing = 0.06.em),
    // --text-md panel titles.
    titleMedium = TextStyle(fontFamily = SvcsBody, fontWeight = FontWeight.SemiBold, fontSize = 16.8.sp, lineHeight = 22.sp, letterSpacing = 0.01.em),
    titleSmall = TextStyle(fontFamily = SvcsBody, fontWeight = FontWeight.Medium, fontSize = 14.4.sp, lineHeight = 20.sp),
    bodyLarge = TextStyle(fontFamily = SvcsBody, fontSize = 16.sp, lineHeight = 25.sp),
    // --text-base body copy, --leading-body 1.6.
    bodyMedium = TextStyle(fontFamily = SvcsBody, fontSize = 15.2.sp, lineHeight = 24.sp),
    // --text-sm small body.
    bodySmall = TextStyle(fontFamily = SvcsBody, fontSize = 13.sp, lineHeight = 19.sp),
    // Buttons and chips: mono, tracked.
    labelLarge = TextStyle(fontFamily = SvcsMono, fontSize = 12.5.sp, lineHeight = 16.sp, letterSpacing = 0.06.em),
    // --text-xs mono labels, section headings (--track-wider).
    labelMedium = TextStyle(fontFamily = SvcsMono, fontSize = 11.2.sp, lineHeight = 15.sp, letterSpacing = 0.15.em),
    // UPPERCASE micro labels, wide tracking (--track-label).
    labelSmall = TextStyle(fontFamily = SvcsMono, fontSize = 10.4.sp, lineHeight = 14.sp, letterSpacing = 0.18.em),
)

/** Corner radius is 2px everywhere. Sharp, never pill, except chips. (--radius) */
val SvcsRadius = 2.dp

private val SvcsShapes = Shapes(
    extraSmall = RoundedCornerShape(2.dp),
    small = RoundedCornerShape(2.dp),
    medium = RoundedCornerShape(3.dp),
    large = RoundedCornerShape(4.dp),
    extraLarge = RoundedCornerShape(4.dp),
)

@Composable
fun SvcsTheme(content: @Composable () -> Unit) {
    // isSystemInDarkTheme() is read but not branched on: see the note above.
    @Suppress("UNUSED_VARIABLE")
    val systemDark = isSystemInDarkTheme()
    MaterialTheme(
        colorScheme = SvcsColorScheme,
        typography = SvcsTypography,
        shapes = SvcsShapes,
        content = content,
    )
}
