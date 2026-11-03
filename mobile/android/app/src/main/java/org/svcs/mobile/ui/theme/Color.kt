package org.svcs.mobile.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * SVCS color tokens.
 *
 * Originally generated from mobile/design/tokens/colors.css (imported from the
 * Claude Design project). As of the 2026-11 UI redesign, SvcsTextDim was lightened and
 * SvcsBorderCtl and SvcsAmberText were added by hand to fix contrast; the old
 * generator input does not know about them. Update both together if you regenerate.
 * The design folder is no longer on this branch; recover it with
 * `git show 4558c5e:mobile/design/tokens/colors.css`. Fills computed from these
 * tokens (container colors, on-amber) are in DerivedColors.kt, not here.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */

// ---- Surfaces ----
val SvcsBg = Color(0xFF0A0E14)
val SvcsSurface = Color(0xFF10192A)
val SvcsSurface2 = Color(0xFF162238)
val SvcsSurface3 = Color(0xFF1E3A52)

// ---- Borders ----
val SvcsBorder = Color(0xFF2A4466)
val SvcsBorderBright = Color(0xFF3A5A7A)
val SvcsBorderCtl = Color(0xFF5D7DA3) // inputs and buttons, 3.7:1 or better (redesign 2026-11)

// ---- Accents ----
val SvcsAmber = Color(0xFFFFB900)
val SvcsAmberDim = Color(0xFF8A6300)
val SvcsAmberText = Color(0xFFD99A00) // dim amber that is readable as text, 7.9:1 (redesign 2026-11)
val SvcsTeal = Color(0xFF1FD4C8)
val SvcsGreen = Color(0xFF2DD6A0)
val SvcsYellow = Color(0xFFFFC800)
val SvcsPurple = Color(0xFFB888FF)
val SvcsBlue = Color(0xFF5AA9FF)
val SvcsOrange = Color(0xFFFF9E5E)
val SvcsRed = Color(0xFFFF5555)

// ---- Text ----
val SvcsText = Color(0xFFD8E8F5)
val SvcsTextDim = Color(0xFF95A9C0) // was 0xFF7A8FA8 (3.55:1 on surface3); now 4.89:1
val SvcsTextBright = Color(0xFFF0F8FF)

// ---- Translucent accents (alpha baked in) ----
val SvcsAmberGlow = Color(0x26FFB900)
val SvcsTealDim = Color(0x1F1FD4C8)
val SvcsGreenDim = Color(0x1F2DD6A0)
val SvcsYellowDim = Color(0x1FFFC800)
val SvcsPurpleDim = Color(0x24B888FF)
val SvcsRedDim = Color(0x1FFF5555)
