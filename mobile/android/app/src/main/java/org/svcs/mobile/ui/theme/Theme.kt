package org.svcs.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp

/**
 * SVCS theme.
 *
 * Dark only, on purpose. The design system is explicit that this is a
 * "dark-first surveillance terminal", and every token is authored for it;
 * there is no light palette to fall back to. isSystemInDarkTheme() is
 * deliberately ignored rather than silently producing an unstyled light screen.
 *
 * Typography is a placeholder. The design calls for Bebas Neue (display),
 * Space Mono (data and labels) and Outfit (body), all OFL-1.1. They are NOT
 * bundled yet: mobile/design/tokens/fonts.css pulls them from the Google Fonts
 * CDN, which is a cloud call this project does not make, so the .ttf files need
 * to be vendored under res/font/ with their license text before the real
 * families can be wired up here. Until then this uses platform defaults with
 * the correct SIZES and TRACKING from tokens/typography.css, so layout is
 * right even though the faces are not.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */

private val SvcsColorScheme = darkColorScheme(
    primary = SvcsAmber,
    onPrimary = SvcsBg,
    secondary = SvcsTeal,
    onSecondary = SvcsBg,
    tertiary = SvcsPurple,
    background = SvcsBg,
    onBackground = SvcsText,
    surface = SvcsSurface,
    onSurface = SvcsText,
    surfaceVariant = SvcsSurface2,
    onSurfaceVariant = SvcsTextDim,
    outline = SvcsBorder,
    outlineVariant = SvcsBorderBright,
    error = SvcsRed,
    onError = SvcsBg,
)

/** Sizes and tracking from tokens/typography.css. Families pending. */
private val SvcsTypography = Typography(
    // --text-2xl, display: stat values.
    displaySmall = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Bold,
        fontSize = 41.6.sp,          // 2.6rem
        letterSpacing = 0.04.em,
    ),
    // --text-md: panel titles.
    titleMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.8.sp,          // 1.05rem
        letterSpacing = 0.1.em,
    ),
    // --text-base: body copy.
    bodyMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 15.2.sp,          // 0.95rem
        lineHeight = 24.sp,          // --leading-body 1.6
    ),
    // --text-xs, mono: UPPERCASE labels with wide tracking (--track-label).
    labelSmall = TextStyle(
        fontFamily = FontFamily.Monospace,
        fontWeight = FontWeight.Normal,
        fontSize = 11.2.sp,          // 0.7rem
        letterSpacing = 0.2.em,
    ),
)


/** Corner radius is 2px everywhere. Sharp, never pill. (--radius) */
val SvcsRadius = 2.dp

@Composable
fun SvcsTheme(content: @Composable () -> Unit) {
    // isSystemInDarkTheme() is read but not branched on: see the note above.
    @Suppress("UNUSED_VARIABLE")
    val systemDark = isSystemInDarkTheme()
    MaterialTheme(
        colorScheme = SvcsColorScheme,
        typography = SvcsTypography,
        content = content,
    )
}
