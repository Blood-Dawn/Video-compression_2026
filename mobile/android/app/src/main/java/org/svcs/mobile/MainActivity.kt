package org.svcs.mobile

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import org.svcs.mobile.ui.ServerSettingsScreen
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
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setFlags(
            WindowManager.LayoutParams.FLAG_SECURE,
            WindowManager.LayoutParams.FLAG_SECURE,
        )
        enableEdgeToEdge()
        setContent {
            SvcsTheme {
                ServerSettingsScreen()
            }
        }
    }
}
