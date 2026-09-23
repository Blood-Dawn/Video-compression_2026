package org.svcs.mobile

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.mutableStateOf
import org.svcs.mobile.ui.SvcsApp
import org.svcs.mobile.ui.theme.SvcsTheme

/**
 * Single activity. M1.1 shows exactly one screen: pair with a server.
 *
 * FLAG_SECURE is set for the whole window. It keeps the app out of the
 * task-switcher thumbnail and blocks screenshots and screen recording. That
 * matters here for two reasons: this screen holds a bearer credential for a
 * surveillance system, and every later screen shows footage of real people.
 * Setting it once at the activity means a future screen cannot forget it.
 *
 * The cost is real and deliberate: users cannot screenshot the app, including
 * to file a bug. That is the right trade for a camera system.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
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
        if (!BuildConfig.ALLOW_SCREENSHOTS) {
            window.setFlags(
                WindowManager.LayoutParams.FLAG_SECURE,
                WindowManager.LayoutParams.FLAG_SECURE,
            )
        }
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
