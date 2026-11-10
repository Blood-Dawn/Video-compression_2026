package org.svcs.mobile.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.graphics.Color

/**
 * Colors derived from the design tokens, not tokens themselves.
 *
 * These are the few opaque fills the app computes from the tokens in Color.kt: each accent at
 * roughly 15% over the surfaces (the design's "amber glow" fill), made opaque so it composites
 * the same on every surface level. The values live in the two palettes in Color.kt, one set
 * for dark and one for light, and are exposed here under their original names.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (cleanup: one source for fills); palettes 2026-11.
 */

/** Selected chips, segments, the nav indicator, the empty-state badge. */
val SvcsAmberContainer: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.amberContainer

/** Danger button fill (Cancel, Stop) and Material's errorContainer. */
val SvcsRedContainer: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.redContainer

val SvcsTealContainer: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.tealContainer
val SvcsPurpleContainer: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.purpleContainer

/** Text and icons on the amber primary button. */
val SvcsOnAmber: Color @Composable @ReadOnlyComposable get() = LocalSvcsPalette.current.onAmber
