package org.svcs.mobile.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import okhttp3.OkHttpClient
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * In-app clip playback (M4).
 *
 * A full-screen progressive player over GET /api/library/file, which is
 * range-enabled server-side, so seeking issues Range requests instead of
 * re-downloading the clip. The OkHttp data source wraps the app's own client
 * for the same reason the LIVE tab does: every range request must carry the
 * Bearer token or the server answers 401 (verified for HLS in M3; the media
 * route enforces the same auth).
 *
 * Codec reality: compressed outputs are H.264 (mode0/1, plays on any phone) or
 * AV1 (mode2/3, hardware or platform-software decode on modern devices).
 * Vendor originals the platform cannot demux never reach this screen; the
 * library tap gates on isPlayable() per the M4 scope decision.
 *
 * Author: Bloodawn (KheivenD), 2026-08-16 (M4 playback).
 */
@Composable
fun PlayerScreen(
    url: String,
    title: String,
    httpClient: OkHttpClient?,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    var error by remember { mutableStateOf<String?>(null) }
    var buffering by remember { mutableStateOf(true) }

    BackHandler(onBack = onClose)

    val player = remember(url) {
        val callFactory = httpClient ?: return@remember null
        val dataSourceFactory = OkHttpDataSource.Factory(callFactory)
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(DefaultMediaSourceFactory(dataSourceFactory))
            .build()
            .apply {
                setMediaItem(MediaItem.fromUri(url))
                playWhenReady = true
                addListener(object : Player.Listener {
                    override fun onPlaybackStateChanged(playbackState: Int) {
                        buffering = playbackState == Player.STATE_BUFFERING
                    }

                    override fun onPlayerError(e: PlaybackException) {
                        // Phrase decoder gaps honestly: an AV1 clip on a phone
                        // with no AV1 decoder is the one likely failure here.
                        error = if (e.errorCode ==
                            PlaybackException.ERROR_CODE_DECODING_FORMAT_UNSUPPORTED
                        ) {
                            "This phone has no decoder for this clip's codec " +
                                "(likely AV1). H.264 clips (mode0/mode1) play " +
                                "on any device."
                        } else {
                            e.errorCodeName
                        }
                    }
                })
                prepare()
            }
    }

    DisposableEffect(player) {
        onDispose { player?.release() }
    }

    Column(Modifier.fillMaxSize().background(Color.Black)) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onClose) { Text("BACK") }
            Text(
                title,
                style = MaterialTheme.typography.titleSmall,
                color = SvcsTextDim,
                maxLines = 1,
                modifier = Modifier.weight(1f),
            )
        }
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (player != null && error == null) {
                AndroidView(
                    factory = { ctx ->
                        PlayerView(ctx).apply {
                            this.player = player
                            useController = true
                            setShowNextButton(false)
                            setShowPreviousButton(false)
                        }
                    },
                    modifier = Modifier.fillMaxSize(),
                )
                if (buffering) CircularProgressIndicator()
            }
            error?.let {
                Text(
                    it,
                    color = SvcsRed,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier.padding(24.dp),
                )
            }
        }
    }
}
