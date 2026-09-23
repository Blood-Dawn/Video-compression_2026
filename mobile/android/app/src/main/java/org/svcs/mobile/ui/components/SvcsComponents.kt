package org.svcs.mobile.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBg
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsBorderBright
import org.svcs.mobile.ui.theme.SvcsDisplay
import org.svcs.mobile.ui.theme.SvcsMono
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsSurface2
import org.svcs.mobile.ui.theme.SvcsSurface3
import org.svcs.mobile.ui.theme.SvcsText
import org.svcs.mobile.ui.theme.SvcsTextBright
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * The SVCS design system's building blocks in Compose, translated from the
 * inline styles in the imported mockup (SVCS-Mobile.dc.html, commit 4558c5e):
 * surface-2 panels with a 1px border and a 2px accent rule on top, UPPERCASE
 * Space Mono labels with wide tracking, Bebas Neue numbers, the amber
 * START button with its glow, pill-shaped mode chips. Stock Material
 * buttons and chips are rounded pills in the baseline palette, which is
 * what made the compressor screens look like a different app from the
 * design they were supposed to follow.
 *
 * Author: Bloodawn (KheivenD), 2026-09-23 (UI pass).
 */

private val Sharp = RoundedCornerShape(2.dp)
private val AmberFill = Color(0xFF2B2410)
private val RedFill = Color(0xFF34161C)

/** Surface-2 panel with a 1px border and an optional 2px accent rule. */
@Composable
fun SvcsPanel(
    modifier: Modifier = Modifier,
    accent: Color? = null,
    onClick: (() -> Unit)? = null,
    contentPadding: Dp = 14.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .clip(Sharp)
            .background(SvcsSurface2)
            .border(1.dp, SvcsBorder, Sharp)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        if (accent != null) {
            Box(Modifier.fillMaxWidth().height(2.dp).background(accent.copy(alpha = 0.6f)))
        }
        Column(Modifier.padding(contentPadding), content = content)
    }
}

/** UPPERCASE mono section label, optionally with an amber action on the right. */
@Composable
fun SvcsSectionLabel(
    text: String,
    modifier: Modifier = Modifier,
    action: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(
            text.uppercase(),
            style = MaterialTheme.typography.labelMedium,
            color = SvcsTextDim,
            modifier = Modifier.weight(1f),
        )
        if (action != null && onAction != null) {
            Text(
                action.uppercase(),
                style = MaterialTheme.typography.labelSmall,
                color = SvcsAmber,
                modifier = Modifier
                    .clip(Sharp)
                    .clickable(onClick = onAction)
                    .padding(horizontal = 6.dp, vertical = 8.dp),
            )
        }
    }
}

/** The amber call to action: Bebas label, glow, 52dp. */
@Composable
fun SvcsPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    enabled: Boolean = true,
) {
    Row(
        modifier
            .fillMaxWidth()
            .height(52.dp)
            .shadow(if (enabled) 10.dp else 0.dp, Sharp, ambientColor = SvcsAmber, spotColor = SvcsAmber)
            .clip(Sharp)
            .background(if (enabled) SvcsAmber else SvcsSurface3)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val fg = if (enabled) Color(0xFF0A0800) else SvcsTextDim
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(10.dp))
        }
        Text(text.uppercase(), fontFamily = SvcsDisplay, fontSize = 21.sp, letterSpacing = 1.8.sp, color = fg)
    }
}

/** Outlined companion to [SvcsPrimaryButton]. Red variant for stop/cancel. */
@Composable
fun SvcsSecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    danger: Boolean = false,
) {
    val fg = if (danger) SvcsRed else SvcsText
    Row(
        modifier
            .height(48.dp)
            .clip(Sharp)
            .background(if (danger) RedFill else Color.Transparent)
            .border(1.dp, if (danger) SvcsRed else SvcsBorderBright, Sharp)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 14.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = fg, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
        }
        Text(text.uppercase(), fontFamily = SvcsDisplay, fontSize = 18.sp, letterSpacing = 1.5.sp, color = fg)
    }
}

/** Pill chip: mono UPPERCASE, amber border + glow fill when selected. */
@Composable
fun SvcsChip(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(50)
    Box(
        modifier
            .heightIn(min = 40.dp)
            .clip(shape)
            .background(if (selected) AmberFill else Color.Transparent)
            .border(1.dp, if (selected) SvcsAmber else SvcsBorder, shape)
            .clickable(role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text.uppercase(),
            style = MaterialTheme.typography.labelLarge,
            color = if (selected) SvcsAmber else SvcsText,
            maxLines = 1,
        )
    }
}

/** Sharp segmented control: equal-width options in one bordered strip. */
@Composable
fun SvcsSegmented(
    options: List<String>,
    selectedIndex: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier
            .fillMaxWidth()
            .height(46.dp)
            .clip(Sharp)
            .border(1.dp, SvcsBorder, Sharp),
    ) {
        options.forEachIndexed { i, label ->
            val selected = i == selectedIndex
            if (i > 0) Box(Modifier.width(1.dp).fillMaxHeight().background(SvcsBorder))
            Box(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .height(46.dp)
                    .background(if (selected) AmberFill else Color.Transparent)
                    .clickable(role = Role.Tab) { onSelect(i) },
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    label.uppercase(),
                    style = MaterialTheme.typography.labelLarge,
                    color = if (selected) SvcsAmber else SvcsTextDim,
                )
            }
        }
    }
}

/** Stat tile: mono label, Bebas value, mono caption, accent rule on top. */
@Composable
fun SvcsStat(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    caption: String? = null,
    accent: Color = SvcsAmber,
    captionColor: Color = SvcsTextDim,
) {
    SvcsPanel(modifier = modifier, accent = accent, contentPadding = 12.dp) {
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
        Spacer(Modifier.height(4.dp))
        Text(value, fontFamily = SvcsDisplay, fontSize = 32.sp, lineHeight = 32.sp, color = SvcsTextBright, maxLines = 1)
        if (caption != null) {
            Text(caption, style = MaterialTheme.typography.labelSmall, color = captionColor, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Setting row: icon, title, one-line explanation, switch. Whole row toggles. */
@Composable
fun SvcsSwitchRow(
    title: String,
    description: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    icon: ImageVector,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier
            .fillMaxWidth()
            .clip(Sharp)
            .clickable(role = Role.Switch) { onCheckedChange(!checked) }
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = if (checked) SvcsAmber else SvcsTextDim, modifier = Modifier.size(22.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = SvcsText)
            Text(description, style = MaterialTheme.typography.bodySmall, color = SvcsTextDim)
        }
        Spacer(Modifier.width(12.dp))
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedTrackColor = SvcsAmber,
                checkedThumbColor = SvcsBg,
                uncheckedTrackColor = SvcsBg,
                uncheckedBorderColor = SvcsBorderBright,
                uncheckedThumbColor = SvcsTextDim,
            ),
        )
    }
}

/** Status pill with a dot; the dot blinks while [live]. */
@Composable
fun SvcsStatusPill(text: String, color: Color, live: Boolean = false) {
    val blink = if (live) {
        val t = rememberInfiniteTransition(label = "blink")
        val a by t.animateFloat(1f, 0.3f, infiniteRepeatable(tween(700), RepeatMode.Reverse), label = "blinkAlpha")
        a
    } else {
        1f
    }
    Row(
        Modifier
            .clip(RoundedCornerShape(50))
            .border(BorderStroke(1.dp, color), RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).alpha(blink).clip(CircleShape).background(color))
        Spacer(Modifier.width(6.dp))
        Text(text.uppercase(), fontFamily = SvcsMono, fontSize = 10.5.sp, letterSpacing = 1.4.sp, color = color)
    }
}

/** 6dp track with a filled bar, the design's progress style. */
@Composable
fun SvcsProgressBar(fraction: Float, color: Color = SvcsAmber, modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .height(6.dp)
            .clip(Sharp)
            .background(SvcsSurface3),
    ) {
        Box(
            Modifier
                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                .height(6.dp)
                .background(color),
        )
    }
}

/** Small mono tag, e.g. "SMART COMPRESS" on a library row. */
@Composable
fun SvcsTag(text: String, color: Color, modifier: Modifier = Modifier) {
    Text(
        text.uppercase(),
        fontFamily = SvcsMono,
        fontSize = 9.5.sp,
        letterSpacing = 1.2.sp,
        color = color,
        modifier = modifier
            .border(1.dp, color.copy(alpha = 0.5f), Sharp)
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}
