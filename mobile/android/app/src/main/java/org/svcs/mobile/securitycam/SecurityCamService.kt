package org.svcs.mobile.securitycam

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Quality
import androidx.camera.video.QualitySelector
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import java.io.File
import java.util.concurrent.Executors

/**
 * Records the phone's back camera in fixed-length clips and hands each one to
 * [ClipQueue] for upload to the paired desktop.
 *
 * Runs as a camera foreground service so it keeps recording with the screen
 * off. Android 14 and later refuse to START a camera service from the
 * background, so it is only ever started from the visible Security cam screen.
 *
 * One clip ends and the next begins in the same moment, but CameraX needs a
 * beat to close one file and open the next, so expect a gap of well under a
 * second between clips. That is the honest cost of cutting clips on the phone.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, roadmap 13.1).
 */
class SecurityCamService : LifecycleService() {

    companion object {
        const val ACTION_START = "org.svcs.mobile.securitycam.START"
        const val ACTION_STOP = "org.svcs.mobile.securitycam.STOP"
        const val EXTRA_SEGMENT_SECONDS = "segment_seconds"
        const val CHANNEL_ID = "svcs_security_cam"
        const val NOTIFICATION_ID = 4400
        private const val TAG = "SecurityCam"

        fun start(context: Context, segmentSeconds: Int) {
            val intent = Intent(context, SecurityCamService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_SEGMENT_SECONDS, segmentSeconds)
            ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, SecurityCamService::class.java).setAction(ACTION_STOP))
        }
    }

    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private var videoCapture: VideoCapture<Recorder>? = null
    private var recording: Recording? = null
    private var segmentSeconds = 600
    private var clipEndsAtMs = 0L
    private var stopping = false
    private var wakeLock: PowerManager.WakeLock? = null

    private val rotate = Runnable { recording?.stop() }
    private val tick = object : Runnable {
        override fun run() {
            val left = ((clipEndsAtMs - System.currentTimeMillis()) / 1000).toInt().coerceAtLeast(0)
            SecurityCamBus.update { it.copy(secondsLeft = left) }
            if (recording != null) main.postDelayed(this, 1000)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACTION_STOP -> beginStop()
            else -> beginStart(intent?.getIntExtra(EXTRA_SEGMENT_SECONDS, 600) ?: 600)
        }
        return START_NOT_STICKY
    }

    private fun beginStart(seconds: Int) {
        if (videoCapture != null) return
        segmentSeconds = seconds.coerceIn(10, 3600)
        stopping = false
        SecurityCamBus.reset(segmentSeconds)
        goForeground()
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "svcs:securitycam").apply { acquire() }

        io.execute { runCatching { ClipQueue.requeueLeftovers(applicationContext) } }

        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            try {
                val provider = future.get()
                val recorder = Recorder.Builder()
                    .setQualitySelector(
                        QualitySelector.fromOrderedList(listOf(Quality.HD, Quality.SD, Quality.LOWEST)),
                    )
                    .build()
                val capture = VideoCapture.withOutput(recorder)
                provider.unbindAll()
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, capture)
                videoCapture = capture
                startClip()
            } catch (e: Exception) {
                Log.w(TAG, "Could not open the camera", e)
                fail("Could not open the camera: ${e.message}")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun startClip() {
        val capture = videoCapture ?: return
        val dir = ClipQueue.clipDir(this)
        if (!ClipQueue.hasRoom(dir)) {
            fail("The phone is almost out of space, so recording stopped.")
            return
        }
        val file = File(dir, ClipQueue.clipName(System.currentTimeMillis()))
        recording = capture.output
            .prepareRecording(this, FileOutputOptions.Builder(file).build())
            .start(ContextCompat.getMainExecutor(this)) { event ->
                when (event) {
                    is VideoRecordEvent.Start -> {
                        clipEndsAtMs = System.currentTimeMillis() + segmentSeconds * 1000L
                        main.postDelayed(rotate, segmentSeconds * 1000L)
                        main.removeCallbacks(tick)
                        main.post(tick)
                    }
                    is VideoRecordEvent.Finalize -> onFinalized(file, event)
                    else -> Unit
                }
            }
    }

    private fun onFinalized(file: File, event: VideoRecordEvent.Finalize) {
        main.removeCallbacks(rotate)
        main.removeCallbacks(tick)
        recording = null
        val usable = file.isFile && file.length() >= ClipQueue.MIN_CLIP_BYTES
        if (usable) {
            SecurityCamBus.update { it.copy(clipsRecorded = it.clipsRecorded + 1) }
            io.execute { runCatching { ClipQueue.enqueue(applicationContext, file) } }
        } else {
            file.delete()
        }
        when {
            stopping -> finish()
            event.hasError() && !usable -> fail("The camera stopped (error ${event.error}).")
            else -> startClip()
        }
    }

    private fun beginStop() {
        if (stopping) return
        stopping = true
        val active = recording
        if (active != null) active.stop() else finish()
    }

    private fun fail(message: String) {
        SecurityCamBus.update { it.copy(error = message) }
        stopping = true
        val active = recording
        if (active != null) active.stop() else finish()
    }

    private fun finish() {
        videoCapture = null
        runCatching { ProcessCameraProvider.getInstance(this).get().unbindAll() }
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        SecurityCamBus.update { it.copy(running = false, secondsLeft = 0) }
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        wakeLock?.let { if (it.isHeld) it.release() }
        io.shutdown()
        if (SecurityCamBus.status.value.running) SecurityCamBus.update { it.copy(running = false) }
        super.onDestroy()
    }

    private fun goForeground() {
        val mgr = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Security cam", NotificationManager.IMPORTANCE_LOW)
                    .apply { description = "Shown while the phone is recording clips for the desktop." },
            )
        }
        val stopIntent = android.app.PendingIntent.getService(
            this, 0,
            Intent(this, SecurityCamService::class.java).setAction(ACTION_STOP),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Security cam is recording")
            .setContentText("Clips of $segmentSeconds seconds are sent to the desktop.")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Stop", stopIntent)
            .build()
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
    }
}
