package org.svcs.mobile.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Colors derived from the design tokens, not tokens themselves.
 *
 * Color.kt holds the design system's tokens verbatim and says not to hand-edit
 * it. These are the few opaque fills the app computes from those tokens: each
 * accent at roughly 15% over the surfaces (the design's "amber glow" fill),
 * made opaque so it composites the same on every surface level. They live in
 * one place because the amber one had been pasted as a literal into the theme,
 * the components, the COMPRESS screen and the bottom bar, and the red one into
 * the theme and the components.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (cleanup: one source for fills).
 */

/** Selected chips, segments, the nav indicator, the empty-state badge. */
val SvcsAmberContainer = Color(0xFF2B2410)

/** Danger button fill (Cancel, Stop) and Material's errorContainer. */
val SvcsRedContainer = Color(0xFF34161C)

val SvcsTealContainer = Color(0xFF0F2B33)
val SvcsPurpleContainer = Color(0xFF261F3A)

/** Text and icons on the amber primary button. */
val SvcsOnAmber = Color(0xFF0A0800)
