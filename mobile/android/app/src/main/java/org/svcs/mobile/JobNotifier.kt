package org.svcs.mobile

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

/**
 * M5 slice: job-completion notifications.
 *
 * Scope, stated honestly: notifications fire while the APP PROCESS IS ALIVE
 * (foreground or recent background), driven by the shell's poll of
 * /api/jobs/recent. Closed-app delivery needs a push transport - per
 * MOBILE-ARCHITECTURE the choices are self-hosted UnifiedPush/ntfy or a
 * foreground service, and FCM is excluded by the no-cloud rule - and that
 * remains open work, not something this class pretends to do.
 *
 * Author: Bloodawn (KheivenD), 2026-08-17 (M5 first slice).
 */
object JobNotifier {

    private const val CHANNEL_ID = "svcs_jobs"
    private var nextId = 1000

    fun ensureChannel(context: Context) {
        val mgr = context.getSystemService(Context.NOTIFICATION_SERVICE)
            as NotificationManager
        if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID, "Server jobs",
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply {
                    description = "A compression job on your SVCS server finished."
                },
            )
        }
    }

    fun canNotify(context: Context): Boolean =
        ContextCompat.checkSelfPermission(
            context, Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED

    /** Post one completion notification. Silently a no-op without permission. */
    fun notifyJobDone(context: Context, label: String, status: String) {
        if (!canNotify(context)) return
        ensureChannel(context)
        val mgr = context.getSystemService(Context.NOTIFICATION_SERVICE)
            as NotificationManager
        val text = when (status) {
            "completed" -> "$label finished compressing."
            "stopped" -> "$label was stopped."
            else -> "$label ended: $status."
        }
        val notif = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("SVCS job ${status}")
            .setContentText(text)
            .setAutoCancel(true)
            .build()
        mgr.notify(nextId++, notif)
    }
}
