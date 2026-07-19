package org.svcs.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.LifecycleEventObserver
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.HttpDataSource
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.ui.PlayerView
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsSurface2
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * LIVE tab (M3): the annotated stream, played on-device.
 *
 * The player is only ever constructed against a playlist the ViewModel has
 * already confirmed is serving segments. See LiveViewModel for why: there is a
 * measured ~3.2s window after the stream starts where the playlist 404s, which
 * is longer than ExoPlayer's default retry budget.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M3).
 */
@Composable
fun LiveScreen(vm: LiveViewModel) {
    val s by vm.state.collectAsState()

    val lifecycleOwner = LocalLifecycleOwner.current

    // Attach/detach is driven by BOTH the composable's lifetime and the
    // process lifecycle, because they fail differently:
    //
    //   * switching tabs disposes this composable but does NOT stop the
    //     activity, so onDispose is the only signal;
    //   * backgrounding the app stops the activity but leaves the composable
    //     composed, so ON_STOP is the only signal.
    //
    // Handling only the first left a backgrounded phone holding the single
    // server-wide stream slot until the server's 30s watchdog reaped it, after
    // which the UI came back still claiming STREAMING over a dead picture.
    //
    // addObserver dispatches ON_START immediately when the owner is already
    // started, which is what performs the initial attach on first composition.
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> vm.onAppear()
                Lifecycle.Event.ON_STOP -> vm.onLeave()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            vm.onLeave()
        }
    }

    Column(
        Modifier.fillMaxSize().padding(horizontal = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text("LIVE", style = MaterialTheme.typography.displaySmall,
            modifier = Modifier.padding(top = 12.dp))

        when (val st = s) {
            is LiveState.Idle -> SourcePrompt(
                initial = st.lastSource,
                onStart = { vm.start(it) },
            )

            is LiveState.Starting -> Card {
                Text("CONNECTING", style = MaterialTheme.typography.titleMedium,
                    color = SvcsAmber)
                LinearProgressIndicator(
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp))
                Text(
                    // Naming the reason keeps a normal 3s wait from reading as
                    // a hang, and matches what the server is actually doing.
                    "Waiting for the first video segment. The encoder writes " +
                        "one every 2 seconds, so this usually takes a few " +
                        "seconds. (${st.elapsedS}s)",
                    style = MaterialTheme.typography.bodyMedium,
                    color = SvcsTextDim,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }

            is LiveState.Ready -> {
                Player(url = st.url, vm = vm)
                Row(
                    Modifier.fillMaxWidth().padding(top = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("STREAMING", style = MaterialTheme.typography.labelSmall,
                        color = SvcsGreen, modifier = Modifier.weight(1f))
                    Text(st.cameraId, style = MaterialTheme.typography.labelSmall,
                        color = SvcsTextDim)
                }
                st.sourceLabel?.takeIf { it.isNotBlank() }?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodyMedium,
                        color = SvcsTextDim,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (!st.weStartedIt) {
                    Text(
                        "This stream was already running on the server. " +
                            "Leaving this tab will not stop it.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = SvcsTextDim,
                    )
                }
                OutlinedButton(onClick = { vm.stopStream() }) { Text("STOP STREAM") }
            }

            is LiveState.Error -> {
                Card {
                    Text("NOT STREAMING", style = MaterialTheme.typography.titleMedium,
                        color = SvcsRed)
                    Text(st.message, style = MaterialTheme.typography.bodyMedium,
                        color = SvcsTextDim, modifier = Modifier.padding(top = 6.dp))
                }
                // A revoked token is not fixed by starting another stream, so
                // offering the source form would send the user in a loop. The
                // fix is under MORE, and the only useful thing here is to say
                // so and let them re-check once they have done it.
                if (st.needsRepair) {
                    OutlinedButton(onClick = { vm.onAppear() }) { Text("RETRY") }
                } else {
                    SourcePrompt(initial = st.lastSource, onStart = { vm.start(it) })
                }
            }
        }
    }
}

/**
 * The ExoPlayer surface.
 *
 * Two things here are load-bearing and were verified against the running
 * server rather than assumed:
 *
 *  1. OkHttpDataSource wrapping the app's own client. HLS fetches each .ts as
 *     a SEPARATE request, and a measured GET of a segment with no
 *     Authorization header returns 401. Reusing the client means the existing
 *     AuthInterceptor covers the playlist and every segment, with no header
 *     handling here to drift out of sync.
 *  2. HlsMediaSource explicitly, with the MIME type set. Left to inference,
 *     ExoPlayer guesses the container from the URL, and the query-string
 *     cache-buster the server appends to playlist URLs is exactly the kind of
 *     thing that breaks that guess.
 */
@Composable
private fun Player(url: String, vm: LiveViewModel) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var error by remember { mutableStateOf<String?>(null) }

    val player = remember(url) {
        val callFactory = vm.httpClient()
            ?: return@remember null
        val dataSourceFactory = OkHttpDataSource.Factory(callFactory)
        val mediaSourceFactory = HlsMediaSource.Factory(dataSourceFactory)
            // The playlist is confirmed live before we get here, but a live
            // stream still drops segments on a flaky Wi-Fi link. A slightly
            // more patient policy than the default rides that out instead of
            // ending playback on the first miss.
            .setLoadErrorHandlingPolicy(
                object : DefaultLoadErrorHandlingPolicy() {
                    override fun getMinimumLoadableRetryCount(dataType: Int): Int = 6
                },
            )
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(mediaSourceFactory)
            .build()
            .apply {
                setMediaItem(
                    MediaItem.Builder()
                        .setUri(url)
                        .setMimeType(MimeTypes.APPLICATION_M3U8)
                        .build(),
                )
                playWhenReady = true
                addListener(object : Player.Listener {
                    override fun onPlayerError(e: PlaybackException) {
                        // Route it into the state machine. Leaving it as a
                        // local string kept a green STREAMING label over a
                        // dead picture, and printed an enum name the user
                        // cannot act on. A 401 here means the token was
                        // revoked mid-playback, which needs re-pairing, not
                        // a retry, so it has to be told apart from a normal
                        // network drop.
                        val http = (e.cause as? HttpDataSource
                            .InvalidResponseCodeException)?.responseCode
                        error = e.errorCodeName
                        vm.onPlaybackError(e.errorCodeName, isAuth = http == 401)
                    }
                })
                prepare()
            }
    }

    // Pause the instant the app is backgrounded, and release when this leaves
    // composition. The screen-level observer also tells the ViewModel to give
    // the stream back on ON_STOP, which drops the state out of Ready and takes
    // this composable with it; pausing here is what stops segment fetches in
    // the meantime, since a paused ExoPlayer still fills its buffer but a
    // running one would keep pulling video into a pocket.
    DisposableEffect(lifecycleOwner, player) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) player?.pause()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            player?.release()
        }
    }

    Box(
        Modifier
            .fillMaxWidth()
            .aspectRatio(16f / 9f)
            .background(androidx.compose.ui.graphics.Color.Black)
            .border(1.dp, SvcsBorder),
        contentAlignment = Alignment.Center,
    ) {
        if (player == null) {
            Text("No server connection.", color = SvcsTextDim,
                style = MaterialTheme.typography.bodyMedium)
        } else {
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { ctx ->
                    PlayerView(ctx).apply {
                        this.player = player
                        useController = false
                        // The frames are of real people. Keep them out of the
                        // recents thumbnail and screenshots, matching the rest
                        // of the app's FLAG_SECURE posture.
                        setKeepContentOnPlayerReset(false)
                    }
                },
            )
        }
        error?.let {
            Text("Playback error: $it", color = SvcsRed,
                style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
private fun SourcePrompt(initial: String, onStart: (String) -> Unit) {
    var text by remember(initial) { mutableStateOf(initial) }
    Card {
        Text("CAMERA SOURCE", style = MaterialTheme.typography.labelSmall,
            color = SvcsAmber)
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            placeholder = { Text("rtsp://192.168.1.50:554/stream1") },
        )
        Text(
            "An RTSP address, or a webcam index like 0 for a camera attached " +
                "to the server.",
            style = MaterialTheme.typography.bodyMedium,
            color = SvcsTextDim,
            modifier = Modifier.padding(top = 6.dp),
        )
        Button(
            onClick = { onStart(text) },
            modifier = Modifier.padding(top = 10.dp),
        ) { Text("START STREAM") }
    }
}

@Composable
private fun Card(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .border(1.dp, SvcsBorder, RoundedCornerShape(2.dp))
            .background(SvcsSurface2)
            .padding(12.dp),
        content = content,
    )
}
