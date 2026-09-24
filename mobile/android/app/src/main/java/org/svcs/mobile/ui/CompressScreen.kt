package org.svcs.mobile.ui

import android.util.Size
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.svcs.mobile.compress.CompressionMode
import org.svcs.mobile.compress.QualityPreset
import org.svcs.mobile.compress.QualityPresets
import org.svcs.mobile.compress.SizePresets
import org.svcs.mobile.compress.VideoCodecChoice
import org.svcs.mobile.ui.components.SvcsChip
import org.svcs.mobile.ui.components.SvcsIcons
import org.svcs.mobile.ui.components.SvcsPanel
import org.svcs.mobile.ui.components.SvcsPrimaryButton
import org.svcs.mobile.ui.components.SvcsProgressBar
import org.svcs.mobile.ui.components.SvcsSecondaryButton
import org.svcs.mobile.ui.components.SvcsSectionLabel
import org.svcs.mobile.ui.components.SvcsSegmented
import org.svcs.mobile.ui.components.SvcsStat
import org.svcs.mobile.ui.components.SvcsStatusPill
import org.svcs.mobile.ui.components.SvcsSwitchRow
import org.svcs.mobile.ui.components.VideoThumbnail
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsAmberContainer
import org.svcs.mobile.ui.theme.SvcsBg
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsBorderBright
import org.svcs.mobile.ui.theme.SvcsDisplay
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsMono
import org.svcs.mobile.ui.theme.SvcsOrange
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTeal
import org.svcs.mobile.ui.theme.SvcsText
import org.svcs.mobile.ui.theme.SvcsTextBright
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * COMPRESS tab (Fall roadmap Phase 1): the standalone, server-free compressor.
 *
 * 2026-09-23 UI pass. One layout per state instead of one long column that
 * kept every control on screen in every state:
 *  - EMPTY: a single large "pick a video" target plus lifetime stats.
 *  - CONFIGURE: the source, a quality-or-size-limit switch that shows only
 *    the relevant options, an estimated result (and a warning when a preset
 *    would make the file BIGGER), options, and a COMPRESS button pinned to
 *    the bottom so it's never scrolled away.
 *  - RUNNING: a hero readout (percent, stage, elapsed, time left).
 *  - DONE: the result on its own: before/after, savings, share first.
 *  - FAILED: what went wrong and a way back.
 * Visual language is the imported SVCS design (panels, mono labels, Bebas
 * numbers, amber action); see ui/components/SvcsComponents.kt.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1); UI pass 2026-09-23.
 */
private enum class CompressView { EMPTY, CONFIGURE, RUNNING, DONE, FAILED }

private fun viewFor(s: CompressState) = when {
    s.phase == JobPhase.FAILED -> CompressView.FAILED
    s.phase == JobPhase.RUNNING -> CompressView.RUNNING
    s.phase == JobPhase.DONE -> CompressView.DONE
    s.pickedUri == null -> CompressView.EMPTY
    else -> CompressView.CONFIGURE
}

@Composable
fun CompressScreen(vm: CompressViewModel) {
    val s by vm.state.collectAsState()
    val lifetime by vm.lifetime.collectAsState()
    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri -> uri?.let(vm::onVideoPicked) }
    val pick = { pickVideo.launch(arrayOf("video/*")) }

    AnimatedContent(
        targetState = viewFor(s),
        transitionSpec = {
            (fadeIn(androidx.compose.animation.core.tween(220)) +
                slideInVertically(androidx.compose.animation.core.tween(220)) { it / 24 }) togetherWith
                fadeOut(androidx.compose.animation.core.tween(150))
        },
        label = "compressView",
    ) { view ->
        when (view) {
            CompressView.EMPTY -> EmptyView(lifetime, onPick = pick)
            CompressView.CONFIGURE -> ConfigureView(s, vm, onPick = pick)
            CompressView.RUNNING -> RunningView(s, vm)
            CompressView.DONE -> DoneView(s, vm)
            CompressView.FAILED -> FailedView(s, onRetry = { vm.reset(); pick() }, onBack = vm::reset)
        }
    }
}

@Composable
private fun ScreenHeader(title: String, subtitle: String) {
    Column(Modifier.fillMaxWidth()) {
        Text(title, style = MaterialTheme.typography.titleLarge, color = SvcsTextBright)
        Text(subtitle.uppercase(), style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
    }
}

// ── EMPTY ─────────────────────────────────────────────────────────────────

@Composable
private fun EmptyView(lifetime: CompressViewModel.Lifetime, onPick: () -> Unit) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        ScreenHeader("COMPRESS", "On this phone - no upload, no server")
        SvcsPanel(accent = SvcsAmber, onClick = onPick, modifier = Modifier.fillMaxWidth()) {
            Column(
                Modifier.fillMaxWidth().heightIn(min = 250.dp).padding(vertical = 18.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Box(
                    Modifier
                        .size(76.dp)
                        .clip(RoundedCornerShape(50))
                        .background(SvcsAmberContainer)
                        .border(1.dp, SvcsAmber, RoundedCornerShape(50)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(SvcsIcons.Video, contentDescription = null, tint = SvcsAmber, modifier = Modifier.size(34.dp))
                }
                Spacer(Modifier.height(18.dp))
                Text("PICK A VIDEO", fontFamily = SvcsDisplay, fontSize = 34.sp, letterSpacing = 1.5.sp, color = SvcsTextBright)
                Spacer(Modifier.height(4.dp))
                Text(
                    "Shrink it for Discord, WhatsApp, email or just to save space.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = SvcsText,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                )
                Spacer(Modifier.height(12.dp))
                Text(
                    "OR SHARE ONE TO SVCS FROM ANY APP",
                    style = MaterialTheme.typography.labelSmall,
                    color = SvcsTextDim,
                )
            }
        }
        if (lifetime.videos > 0) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                SvcsStat(
                    label = "Compressed",
                    value = lifetime.videos.toString(),
                    caption = if (lifetime.videos == 1) "video" else "videos",
                    accent = SvcsTeal,
                    modifier = Modifier.weight(1f),
                )
                SvcsStat(
                    label = "Space saved",
                    value = humanBytes(lifetime.bytesSaved),
                    caption = "on this phone",
                    accent = SvcsGreen,
                    captionColor = SvcsGreen,
                    modifier = Modifier.weight(1f),
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Step("1", "Pick", Modifier.weight(1f))
            Step("2", "Choose", Modifier.weight(1f))
            Step("3", "Share", Modifier.weight(1f))
        }
    }
}

@Composable
private fun Step(n: String, label: String, modifier: Modifier) {
    Row(
        modifier.border(1.dp, SvcsBorder, RoundedCornerShape(2.dp)).padding(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(n, fontFamily = SvcsDisplay, fontSize = 22.sp, color = SvcsAmber)
        Spacer(Modifier.width(8.dp))
        Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = SvcsText)
    }
}

// ── CONFIGURE ─────────────────────────────────────────────────────────────

private fun qualityBlurb(p: QualityPreset): String = when (p) {
    QualityPresets.HIGH -> "Keeps the original resolution at about 10 Mbps. For videos you want to keep."
    QualityPresets.MEDIUM -> "Up to 1080p at about 6 Mbps. A good balance for sharing."
    QualityPresets.LOW -> "Up to 720p at about 3 Mbps. Smallest files, still fine on a phone screen."
    else -> ""
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ConfigureView(s: CompressState, vm: CompressViewModel, onPick: () -> Unit) {
    val sizeGoal = s.mode is CompressionMode.TargetSize
    Box(Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 104.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            ScreenHeader("COMPRESS", "On this phone - no upload, no server")
            SourceCard(s, onChange = onPick)

            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                SvcsSectionLabel("Goal")
                SvcsSegmented(
                    options = listOf("Quality", "Size limit"),
                    selectedIndex = if (sizeGoal) 1 else 0,
                    onSelect = { vm.setGoal(sizeLimit = it == 1) },
                )
            }

            if (!sizeGoal) {
                val current = (s.mode as? CompressionMode.Quality)?.preset
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    QualityPresets.ALL.forEach { p ->
                        SvcsChip(p.label, selected = current == p, onClick = { vm.setQualityPreset(p) }, modifier = Modifier.weight(1f))
                    }
                }
                if (current != null) {
                    SvcsPanel(modifier = Modifier.fillMaxWidth(), contentPadding = 12.dp) {
                        Text(current.label.uppercase(), fontFamily = SvcsDisplay, fontSize = 19.sp, letterSpacing = 0.8.sp, color = SvcsAmber)
                        Text(qualityBlurb(current), style = MaterialTheme.typography.bodySmall, color = SvcsText)
                    }
                }
            } else {
                val current = (s.mode as? CompressionMode.TargetSize)?.preset
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    SizePresets.ALL.forEach { p ->
                        SvcsChip(
                            p.label,
                            selected = s.customSizeText.isEmpty() && current == p,
                            onClick = { vm.setSizePreset(p) },
                        )
                    }
                }
                OutlinedTextField(
                    value = s.customSizeText,
                    onValueChange = vm::setCustomSizeText,
                    label = { Text("Exact size in MB") },
                    placeholder = { Text("e.g. 8") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    shape = RoundedCornerShape(2.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = SvcsAmber,
                        unfocusedBorderColor = SvcsBorder,
                        focusedLabelColor = SvcsAmber,
                        cursorColor = SvcsAmber,
                    ),
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            EstimatePanel(s, vm)

            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                SvcsSectionLabel("Format")
                SvcsSegmented(
                    options = listOf("H.265 smaller", "H.264 compatible"),
                    selectedIndex = if (s.codec == VideoCodecChoice.H265) 0 else 1,
                    onSelect = { vm.setCodec(if (it == 0) VideoCodecChoice.H265 else VideoCodecChoice.H264) },
                )
            }

            Column {
                SvcsSectionLabel("Options")
                SvcsSwitchRow(
                    title = "Smart Compress (beta)",
                    description = "Checks for people, vehicles and animals first. Footage where nothing happens gets squeezed harder.",
                    checked = s.smartCompress,
                    onCheckedChange = vm::setSmartCompress,
                    icon = SvcsIcons.Smart,
                )
                if (s.sourceHasAudio) {
                    SvcsSwitchRow(
                        title = "Remove audio",
                        description = "Silent output. With a size limit, the freed space goes to picture quality.",
                        checked = s.removeAudio,
                        onCheckedChange = vm::setRemoveAudio,
                        icon = SvcsIcons.Mute,
                    )
                }
            }
        }

        // Pinned action: never scrolled out of reach, with a fade so content
        // reads as passing under it rather than being cut off.
        Column(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .background(Brush.verticalGradient(listOf(Color.Transparent, SvcsBg, SvcsBg)))
                .padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 14.dp),
        ) {
            SvcsPrimaryButton("Compress", onClick = vm::startCompress, icon = SvcsIcons.Play)
        }
    }
}

@Composable
private fun SourceCard(s: CompressState, onChange: () -> Unit) {
    SvcsPanel(modifier = Modifier.fillMaxWidth(), contentPadding = 10.dp) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            VideoThumbnail(s.pickedUri, Modifier.size(width = 84.dp, height = 64.dp))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    s.pickedName ?: "Selected video",
                    style = MaterialTheme.typography.titleSmall,
                    color = SvcsTextBright,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val line1 = buildList {
                    if (s.pickedSizeBytes >= 0) add(humanBytes(s.pickedSizeBytes))
                    if (s.durationMs > 0) add(clock(s.durationMs))
                }
                Text(line1.joinToString(" · "), style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
                if (s.sourceWidth > 0 && s.sourceHeight > 0) {
                    val shape = if (s.sourceHeight > s.sourceWidth) "PORTRAIT" else "LANDSCAPE"
                    Text("${s.sourceWidth}x${s.sourceHeight} · $shape", style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
                }
            }
            Text(
                "CHANGE",
                style = MaterialTheme.typography.labelSmall,
                color = SvcsAmber,
                modifier = Modifier
                    .clip(RoundedCornerShape(2.dp))
                    .clickable(onClick = onChange)
                    .padding(horizontal = 8.dp, vertical = 12.dp),
            )
        }
    }
}

@Composable
private fun EstimatePanel(s: CompressState, vm: CompressViewModel) {
    val est = vm.estimatedBytes(s)
    val original = s.pickedSizeBytes
    val target = (s.mode as? CompressionMode.TargetSize)?.preset
    val alreadyUnder = target != null && original > 0 && original <= target.maxBytes

    // The source's own average bitrate. Asking the encoder for more than the
    // source already has buys no quality and may not shrink the file at all,
    // which is a far better warning than comparing against an estimate:
    // encoders treat the bitrate as a ceiling and usually land well under it
    // (8 MB on a 10 MB target in the Sep 22 field test).
    val sourceBps = if (original > 0 && s.durationMs > 0) original * 8.0 / (s.durationMs / 1000.0) else null
    val requestedBps = est?.let { it * 8.0 / (s.durationMs / 1000.0) }
    val wontShrink = target == null && sourceBps != null && requestedBps != null && requestedBps >= sourceBps * 0.9
    val warn = wontShrink || alreadyUnder

    SvcsPanel(
        modifier = Modifier.fillMaxWidth(),
        accent = if (warn) SvcsOrange else SvcsTeal,
        contentPadding = 12.dp,
    ) {
        Text("ESTIMATED RESULT", style = MaterialTheme.typography.labelSmall, color = SvcsTextDim)
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            val headline = when {
                target != null -> "UNDER " + decimalMb(target.maxBytes)
                est != null -> "UP TO " + humanBytes(est)
                else -> "UNKNOWN LENGTH"
            }
            Text(headline, fontFamily = SvcsDisplay, fontSize = 34.sp, lineHeight = 34.sp, color = SvcsTextBright)
            val bound = target?.maxBytes ?: est
            if (bound != null && original > 0 && !warn) {
                val pct = ((1.0 - bound.toDouble() / original) * 100).toInt()
                if (pct > 0) {
                    Spacer(Modifier.width(10.dp))
                    Text("-$pct%", fontFamily = SvcsDisplay, fontSize = 24.sp, color = SvcsGreen, modifier = Modifier.padding(bottom = 2.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("OR MORE", style = MaterialTheme.typography.labelSmall, color = SvcsGreen, modifier = Modifier.padding(bottom = 6.dp))
                }
            }
        }
        val mbps = { bps: Double -> "%.1f Mbps".format(bps / 1_000_000) }
        val note = when {
            alreadyUnder -> "This video is already under ${decimalMb(target!!.maxBytes)}. It will still shrink, but you may not need to."
            wontShrink -> "The original is only about ${mbps(sourceBps!!)}, and this preset allows ${mbps(requestedBps!!)}. " +
                "It may barely shrink. Try Low or a size limit."
            target != null -> "From ${humanBytes(original)}. Size limits leave a small safety margin."
            original > 0 -> "From ${humanBytes(original)}. Most videos come out well under this."
            else -> "Most videos come out well under this."
        }
        Text(note, style = MaterialTheme.typography.bodySmall, color = if (warn) SvcsOrange else SvcsTextDim)
    }
}

// ── RUNNING ───────────────────────────────────────────────────────────────

@Composable
private fun RunningView(s: CompressState, vm: CompressViewModel) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            now = System.currentTimeMillis()
            delay(1000)
        }
    }
    val elapsed = if (s.startedAtMs > 0) now - s.startedAtMs else 0L
    val p = s.progressPercent
    val eta = if (!s.analyzing && p in 3..99 && elapsed > 2000) elapsed * (100 - p) / p else null

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        ScreenHeader("COMPRESS", "Working on it")
        SvcsPanel(modifier = Modifier.fillMaxWidth(), accent = SvcsAmber) {
            SvcsStatusPill(if (s.analyzing) "Checking for activity" else "Encoding", SvcsAmber, live = true)
            Spacer(Modifier.height(14.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    if (s.analyzing) "--" else "$p",
                    fontFamily = SvcsDisplay,
                    fontSize = 88.sp,
                    lineHeight = 80.sp,
                    color = SvcsTextBright,
                )
                Text("%", fontFamily = SvcsDisplay, fontSize = 32.sp, color = SvcsAmber, modifier = Modifier.padding(bottom = 10.dp, start = 4.dp))
            }
            Text(
                (s.pickedName ?: "video").uppercase(),
                style = MaterialTheme.typography.labelSmall,
                color = SvcsTextDim,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(12.dp))
            SvcsProgressBar(if (s.analyzing) 0f else p / 100f)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SvcsStat("Elapsed", clock(elapsed), Modifier.weight(1f), accent = SvcsTeal)
            SvcsStat("Time left", eta?.let(::clock) ?: "--", Modifier.weight(1f), accent = SvcsAmber)
        }
        SvcsSecondaryButton("Cancel", onClick = vm::cancel, icon = SvcsIcons.Stop, danger = true, modifier = Modifier.fillMaxWidth())
        Text(
            "You can leave the app. It keeps going, and progress stays in your notifications.",
            style = MaterialTheme.typography.bodySmall,
            color = SvcsTextDim,
        )
    }
}

// ── DONE ──────────────────────────────────────────────────────────────────

@Composable
private fun DoneView(s: CompressState, vm: CompressViewModel) {
    val context = LocalContext.current
    val before = s.pickedSizeBytes
    val after = s.outputBytes
    val known = before > 0 && after > 0
    val savedPct = if (known) ((1.0 - after.toDouble() / before) * 100).toInt() else 0

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        ScreenHeader("COMPRESS", "Saved to Movies/SVCS")
        SvcsPanel(modifier = Modifier.fillMaxWidth(), accent = SvcsGreen) {
            SvcsStatusPill("Done", SvcsGreen)
            Spacer(Modifier.height(12.dp))
            if (known) {
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(
                        if (savedPct >= 0) "-$savedPct%" else "+${-savedPct}%",
                        fontFamily = SvcsDisplay,
                        fontSize = 80.sp,
                        lineHeight = 76.sp,
                        color = if (savedPct >= 0) SvcsGreen else SvcsOrange,
                    )
                    Spacer(Modifier.width(10.dp))
                    Text(
                        if (savedPct >= 0) "SMALLER" else "LARGER",
                        style = MaterialTheme.typography.labelMedium,
                        color = SvcsTextDim,
                        modifier = Modifier.padding(bottom = 12.dp),
                    )
                }
                Spacer(Modifier.height(12.dp))
                SizeBar("Original", before, 1f, SvcsBorderBright)
                Spacer(Modifier.height(8.dp))
                SizeBar("Compressed", after, (after.toFloat() / before).coerceIn(0.02f, 1f), SvcsGreen)
            } else {
                Text("FINISHED", fontFamily = SvcsDisplay, fontSize = 48.sp, color = SvcsGreen)
            }
            s.smartCompressActivityDetected?.let { hadActivity ->
                Spacer(Modifier.height(12.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(SvcsIcons.Smart, contentDescription = null, tint = SvcsAmber, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(
                        if (hadActivity) "Smart Compress found activity, so it kept full quality."
                        else "Smart Compress found nothing happening and squeezed it harder.",
                        style = MaterialTheme.typography.bodySmall,
                        color = SvcsText,
                    )
                }
            }
            if (s.usedFallback) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "This phone's encoder needed a safer resolution or codec to finish, so quality may be lower than requested.",
                    style = MaterialTheme.typography.bodySmall,
                    color = SvcsOrange,
                )
            }
        }
        s.outputUri?.let { out ->
            SvcsPrimaryButton(
                "Share",
                icon = SvcsIcons.Share,
                onClick = { VideoIntents.share(context, out) },
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                SvcsSecondaryButton(
                    "Play",
                    icon = SvcsIcons.Play,
                    modifier = Modifier.weight(1f),
                    onClick = { VideoIntents.play(context, out) },
                )
                SvcsSecondaryButton("New video", icon = SvcsIcons.Video, modifier = Modifier.weight(1f), onClick = vm::reset)
            }
        } ?: SvcsSecondaryButton("New video", icon = SvcsIcons.Video, modifier = Modifier.fillMaxWidth(), onClick = vm::reset)
    }
}

@Composable
private fun SizeBar(label: String, bytes: Long, fraction: Float, color: Color) {
    Column {
        Row {
            Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = SvcsTextDim, modifier = Modifier.weight(1f))
            Text(humanBytes(bytes), fontFamily = SvcsMono, fontSize = 12.sp, color = SvcsTextBright)
        }
        Spacer(Modifier.height(4.dp))
        SvcsProgressBar(fraction, color)
    }
}

// ── FAILED ────────────────────────────────────────────────────────────────

@Composable
private fun FailedView(s: CompressState, onRetry: () -> Unit, onBack: () -> Unit) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        ScreenHeader("COMPRESS", "Something went wrong")
        SvcsPanel(modifier = Modifier.fillMaxWidth(), accent = SvcsRed) {
            SvcsStatusPill("Failed", SvcsRed)
            Spacer(Modifier.height(12.dp))
            Text("COULDN'T COMPRESS THIS ONE", fontFamily = SvcsDisplay, fontSize = 28.sp, color = SvcsTextBright)
            Spacer(Modifier.height(4.dp))
            Text(s.error ?: "Unknown error.", style = MaterialTheme.typography.bodyMedium, color = SvcsText)
        }
        SvcsPrimaryButton("Choose a video", onClick = onRetry, icon = SvcsIcons.Video)
        SvcsSecondaryButton("Back", onClick = onBack, modifier = Modifier.fillMaxWidth())
    }
}
