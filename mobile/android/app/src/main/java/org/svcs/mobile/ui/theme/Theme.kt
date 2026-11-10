package org.svcs.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.CompositionLocalProvider
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
 * Dark and light. The design system's home is a "dark-first surveillance terminal"; a light
 * palette was added in the 2026-11 redesign and the app follows the system setting.
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

// Container fills (SvcsAmberContainer and friends) are in DerivedColors.kt.

private fun svcsColorScheme(p: SvcsPalette, dark: Boolean): ColorScheme =
    if (dark) darkColorScheme(
    primary = p.amber,
    onPrimary = p.onAmber,
    primaryContainer = p.amberContainer,
    onPrimaryContainer = p.amber,
    inversePrimary = p.amberDim,
    secondary = p.teal,
    onSecondary = p.bg,
    // Selected chips and the nav indicator use secondaryContainer: keep them
    // on the amber accent, which is what the design marks "active" with.
    secondaryContainer = p.amberContainer,
    onSecondaryContainer = p.amber,
    tertiary = p.purple,
    onTertiary = p.bg,
    tertiaryContainer = p.purpleContainer,
    onTertiaryContainer = p.purple,
    background = p.bg,
    onBackground = p.text,
    surface = p.bg,
    onSurface = p.text,
    surfaceVariant = p.surface2,
    onSurfaceVariant = p.textDim,
    surfaceTint = Color.Transparent,
    inverseSurface = p.text,
    inverseOnSurface = p.bg,
    error = p.red,
    onError = p.bg,
    errorContainer = p.redContainer,
    onErrorContainer = p.red,
    outline = p.border,
    outlineVariant = p.border,
    scrim = Color.Black,
    surfaceBright = p.surface3,
    surfaceDim = p.bg,
    surfaceContainerLowest = p.bg,
    surfaceContainerLow = p.surface,
    surfaceContainer = p.surface,
    surfaceContainerHigh = p.surface2,
    surfaceContainerHighest = p.surface2,
    ) else lightColorScheme(
    primary = p.amber,
    onPrimary = p.onAmber,
    primaryContainer = p.amberContainer,
    onPrimaryContainer = p.amber,
    inversePrimary = p.amberDim,
    secondary = p.teal,
    onSecondary = p.bg,
    // Selected chips and the nav indicator use secondaryContainer: keep them
    // on the amber accent, which is what the design marks "active" with.
    secondaryContainer = p.amberContainer,
    onSecondaryContainer = p.amber,
    tertiary = p.purple,
    onTertiary = p.bg,
    tertiaryContainer = p.purpleContainer,
    onTertiaryContainer = p.purple,
    background = p.bg,
    onBackground = p.text,
    surface = p.bg,
    onSurface = p.text,
    surfaceVariant = p.surface2,
    onSurfaceVariant = p.textDim,
    surfaceTint = Color.Transparent,
    inverseSurface = p.text,
    inverseOnSurface = p.bg,
    error = p.red,
    onError = p.bg,
    errorContainer = p.redContainer,
    onErrorContainer = p.red,
    outline = p.border,
    outlineVariant = p.border,
    scrim = Color.Black,
    surfaceBright = p.surface3,
    surfaceDim = p.bg,
    surfaceContainerLowest = p.bg,
    surfaceContainerLow = p.surface,
    surfaceContainer = p.surface,
    surfaceContainerHigh = p.surface2,
    surfaceContainerHighest = p.surface2,
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
    // Follows the system light or dark setting. Dark is the design's home; light was added in
    // the 2026-11 redesign (see Color.kt for the two palettes).
    val dark = isSystemInDarkTheme()
    val palette = if (dark) SvcsDarkPalette else SvcsLightPalette
    CompositionLocalProvider(LocalSvcsPalette provides palette) {
        MaterialTheme(
            colorScheme = svcsColorScheme(palette, dark),
            typography = SvcsTypography,
            shapes = SvcsShapes,
            content = content,
        )
    }
}