package org.svcs.mobile.ui

import android.content.Context
import android.content.Intent
import android.net.Uri

/**
 * Hand a compressed video to another app. The COMPRESS result screen and the
 * SAVED rows both do this; before 2026-09-24 each built the intents by hand.
 *
 * Both grant read access to the MediaStore URI for that one hand-off only.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (cleanup).
 */
object VideoIntents {

    /** System share sheet for one MP4. */
    fun share(context: Context, uri: Uri) {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "video/mp4"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(Intent.createChooser(send, "Share compressed video"))
    }

    /**
     * Open in the user's video player. Returns false instead of crashing when
     * nothing can play it: no video player at all is rare but real on
     * stripped-down ROMs.
     */
    fun play(context: Context, uri: Uri): Boolean {
        val view = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "video/mp4")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return runCatching { context.startActivity(view) }.isSuccess
    }
}
