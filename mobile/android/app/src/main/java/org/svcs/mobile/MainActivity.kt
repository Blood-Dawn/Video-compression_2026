package org.svcs.mobile

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.mutableStateOf
import org.svcs.mobile.ui.SvcsApp
import org.svcs.mobile.ui.theme.SvcsTheme

/**
 * Single activity hosting the whole Compose app (SvcsApp): the standalone
 * compressor tabs, and Server Mode once paired. It also receives videos
 * shared in from other apps (ACTION_SEND) and hands them to COMPRESS.
 *
 * Screenshots and screen recording are allowed. The window used to set
 * FLAG_SECURE app-wide, which also blocked screenshots of the standalone
 * compressor, bug reports and store listings. The owner removed it on
 * 2026-09-24 (docs/BLOCKERS.md). The pairing token stays encrypted at rest in
 * TokenStore and is never drawn in clear text.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1); FLAG_SECURE removed 2026-09-24.
 */
class MainActivity : ComponentActivity() {

    // M5 slice: ask once for notification permission (Android 13+). Declining
    // is fine; job-completion notifications just stay off.
    private val notifPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    /** A video handed in via the share sheet, waiting for the COMPRESS tab
     *  to pick it up. Cleared once consumed so rotation doesn't re-load it. */
    private val sharedVideo = mutableStateOf<Uri?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        JobNotifier.ensureChannel(this)
        if (Build.VERSION.SDK_INT >= 33 && !JobNotifier.canNotify(this)) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        if (savedInstanceState == null) handleShare(intent)
        setContent {
            SvcsTheme {
                SvcsApp(
                    sharedVideo = sharedVideo.value,
                    onSharedVideoConsumed = { sharedVideo.value = null },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    private fun handleShare(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        val type = intent.type ?: return
        if (!type.startsWith("video/")) return
        val uri = if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_STREAM)
        }
        if (uri != null) sharedVideo.value = uri
    }
}
