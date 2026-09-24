package org.svcs.mobile.ui.components

import android.media.MediaMetadataRetriever
import android.net.Uri
import android.util.Size
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.svcs.mobile.ui.theme.SvcsSurface3
import org.svcs.mobile.ui.theme.SvcsTextDim

/**
 * A still from a video, cropped to fill [modifier]'s size, with a video icon
 * while it loads or when no frame can be had.
 *
 * Tries the provider's own thumbnail first (ContentResolver.loadThumbnail,
 * API 29 = this app's minSdk, which MediaStore serves from its cache), then
 * decodes a frame half a second in. The picked source on COMPRESS often comes
 * from a documents provider with no thumbnail, which is why the decode
 * fallback exists; SAVED's MediaStore outputs usually hit the first path.
 * Replaces the two near-identical loaders those screens had.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (cleanup: one thumbnail loader).
 */
@Composable
fun VideoThumbnail(uri: Uri?, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val thumb by produceState<ImageBitmap?>(initialValue = null, uri) {
        value = if (uri == null) null else withContext(Dispatchers.IO) {
            runCatching {
                context.contentResolver.loadThumbnail(uri, Size(320, 240), null).asImageBitmap()
            }.getOrNull() ?: runCatching {
                val r = MediaMetadataRetriever()
                try {
                    r.setDataSource(context, uri)
                    r.getScaledFrameAtTime(500_000, MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 320, 240)
                        ?.asImageBitmap()
                } finally {
                    r.release()
                }
            }.getOrNull()
        }
    }
    Box(modifier.clip(RoundedCornerShape(2.dp)).background(SvcsSurface3), contentAlignment = Alignment.Center) {
        val t = thumb
        if (t != null) {
            Image(t, contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        } else {
            Icon(SvcsIcons.Video, contentDescription = null, tint = SvcsTextDim, modifier = Modifier.size(22.dp))
        }
    }
}
