package org.svcs.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.grid.rememberLazyGridState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.request.CachePolicy
import coil.request.ImageRequest
import org.svcs.mobile.net.LibraryItem
import org.svcs.mobile.net.isPlayable
import org.svcs.mobile.ui.theme.SvcsAmber
import org.svcs.mobile.ui.theme.SvcsBorder
import org.svcs.mobile.ui.theme.SvcsGreen
import org.svcs.mobile.ui.theme.SvcsRed
import org.svcs.mobile.ui.theme.SvcsSurface2
import org.svcs.mobile.ui.theme.SvcsTextDim
import org.svcs.mobile.ui.theme.SvcsYellow

/**
 * LIBRARY tab: a paginated grid of recorded clips (M2.1).
 *
 * Two decisions here are about privacy rather than looks:
 *
 *  * Thumbnails are memory-cached ONLY. Every one is a frame of a real place
 *    and often real people, so writing them into the app's disk cache would
 *    scatter surveillance stills across the phone's storage where nothing in
 *    this app manages their lifetime. Coil's disk cache is disabled per request
 *    below. The cost is re-fetching on process death, which is cheap because
 *    the SERVER caches them (measured: 93 ms cold, 6 ms warm).
 *  * The screen inherits FLAG_SECURE from MainActivity, so this grid cannot be
 *    screenshotted or appear in the task switcher.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2.1).
 */
@Composable
fun LibraryScreen(vm: LibraryViewModel) {
    val state by vm.state.collectAsState()
    val gridState = rememberLazyGridState()
    val context = androidx.compose.ui.platform.LocalContext.current

    // M4: tap-to-play. Local state rather than a nav library on purpose; the
    // player is the only pushed screen the app has.
    var playing by remember { mutableStateOf<LibraryItem?>(null) }
    playing?.let { item ->
        val url = vm.fileUrl(item)
        if (url != null) {
            PlayerScreen(
                url = url,
                title = item.displayName(),
                httpClient = vm.httpClient(),
                onClose = { playing = null },
            )
            return
        }
    }

    // Coil MUST be handed the app's authenticated OkHttp client. Its default
    // client has no Authorization header, so every thumbnail 401s and the grid
    // silently renders empty tiles with no error anywhere. Verified on device:
    // before this, the server's thumbnail cache stayed empty while the phone
    // scrolled a full page of clips.
    val imageLoader = remember(vm.httpClient()) {
        val builder = coil.ImageLoader.Builder(context)
            // Never write surveillance frames to the phone's disk. Memory only.
            .diskCachePolicy(CachePolicy.DISABLED)
        vm.httpClient()?.let { builder.okHttpClient(it) }
        builder.build()
    }

    LaunchedEffect(Unit) { vm.loadFirstPageIfNeeded() }

    // Infinite scroll: ask for the next page when the tail comes into view.
    // Cheap on the server since M2.1a caches the folder walk, so page N costs
    // ~5 ms instead of re-walking the tree.
    LaunchedEffect(gridState) {
        snapshotFlow {
            val last = gridState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0
            val total = gridState.layoutInfo.totalItemsCount
            total > 0 && last >= total - 6
        }.collect { nearEnd -> if (nearEnd) vm.loadNextPage() }
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Text("LIBRARY", style = MaterialTheme.typography.labelSmall, color = SvcsAmber,
            modifier = Modifier.padding(top = 12.dp, bottom = 2.dp))

        val subtitle = when {
            state.error != null -> state.error!!
            state.total > 0 -> "${state.items.size} of ${state.total} clips"
            state.loading -> "Loading..."
            else -> "No clips found"
        }
        Text(subtitle, style = MaterialTheme.typography.bodyMedium,
            color = if (state.error != null) SvcsRed else SvcsTextDim)

        // The desktop library's Originals | Compressed | All views (M4).
        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.padding(top = 6.dp),
        ) {
            KindChip("ALL", state.kind == "all") { vm.setKind("all") }
            KindChip("ORIGINALS", state.kind == "original") { vm.setKind("original") }
            KindChip("COMPRESSED", state.kind == "compressed") { vm.setKind("compressed") }
            KindChip("OUTPUTS", false) { vm.showOutputs() }
            KindChip("REFRESH", false) { vm.refresh() }
        }

        // Outcome of the last compress action ("started", "server busy", ...).
        state.actionMessage?.let {
            Text(it, style = MaterialTheme.typography.bodyMedium,
                color = SvcsGreen, modifier = Modifier.padding(top = 6.dp))
        }

        // The server caps a listing at 5000 files. Say so rather than let an
        // operator believe they have scrolled past everything they recorded.
        if (state.truncated) {
            Text(
                "This folder holds more than the server will list at once. " +
                    "Narrow to a camera subfolder to see the rest.",
                style = MaterialTheme.typography.bodyMedium,
                color = SvcsYellow,
                modifier = Modifier.padding(top = 6.dp),
            )
        }

        if (state.items.isEmpty() && state.loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Column
        }

        LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 150.dp),
            state = gridState,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            modifier = Modifier.fillMaxSize().padding(top = 10.dp),
        ) {
            items(state.items, key = { it.path }) { item ->
                ClipTile(
                    item = item,
                    thumbUrl = vm.thumbUrl(item),
                    imageLoader = imageLoader,
                    compressEnabled = !state.compressing,
                    onPlay = { playing = item },
                    onCompress = { vm.compress(item) },
                )
            }
        }
    }
}

/** One filter chip. Text-only to match the app's flat design tokens. */
@Composable
private fun KindChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        label,
        style = MaterialTheme.typography.labelSmall,
        color = if (selected) SvcsAmber else SvcsTextDim,
        modifier = Modifier
            .border(1.dp, if (selected) SvcsAmber else SvcsBorder, RoundedCornerShape(2.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

@Composable
private fun ClipTile(
    item: LibraryItem,
    thumbUrl: String?,
    imageLoader: coil.ImageLoader,
    compressEnabled: Boolean = true,
    onPlay: () -> Unit = {},
    onCompress: () -> Unit = {},
) {
    // Vendor originals Android cannot demux stay thumbnail-only (M4 scope
    // decision); everything else opens the in-app player on tap.
    val playable = item.isPlayable()
    Column(
        Modifier
            .fillMaxWidth()
            .border(1.dp, SvcsBorder, RoundedCornerShape(2.dp))
            .background(SvcsSurface2)
            .clickable(enabled = playable, onClick = onPlay),
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .aspectRatio(16f / 9f)
                .clip(RoundedCornerShape(topStart = 2.dp, topEnd = 2.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (thumbUrl != null) {
                AsyncImage(
                    imageLoader = imageLoader,
                    model = ImageRequest.Builder(androidx.compose.ui.platform.LocalContext.current)
                        .data(thumbUrl)
                        // Memory only. See the class note: these are frames of
                        // real people and must not be written to phone storage.
                        .diskCachePolicy(CachePolicy.DISABLED)
                        .memoryCachePolicy(CachePolicy.ENABLED)
                        .crossfade(true)
                        .build(),
                    contentDescription = item.displayName(),
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Text("NO PREVIEW", style = MaterialTheme.typography.labelSmall,
                    color = SvcsTextDim)
            }
        }
        Column(Modifier.padding(8.dp)) {
            Text(
                item.displayName(),
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
            )
            val badge = if (item.isCompressed) "COMPRESSED"
                        else if (item.compressed) "HAS COMPRESSED" else "ORIGINAL"
            Text(
                "${item.humanSize()}  $badge",
                style = MaterialTheme.typography.labelSmall,
                color = if (item.isCompressed) SvcsGreen else SvcsTextDim,
                maxLines = 1,
            )
            item.folderLabel()?.let {
                Text(it, style = MaterialTheme.typography.labelSmall,
                    color = SvcsTextDim, maxLines = 1)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                if (playable) {
                    Text("PLAY", style = MaterialTheme.typography.labelSmall,
                        color = SvcsAmber,
                        modifier = Modifier.clickable(onClick = onPlay)
                            .padding(top = 6.dp))
                }
                // Compress an original that has no verified compressed copy
                // yet. Runs on the SERVER (M4: server-side path, zero phone
                // bytes); progress shows on HOME like a desktop-started job.
                if (!item.isCompressed && !item.compressed) {
                    Text("COMPRESS", style = MaterialTheme.typography.labelSmall,
                        color = if (compressEnabled) SvcsGreen else SvcsTextDim,
                        modifier = Modifier.clickable(enabled = compressEnabled,
                            onClick = onCompress).padding(top = 6.dp))
                }
            }
        }
    }
}
