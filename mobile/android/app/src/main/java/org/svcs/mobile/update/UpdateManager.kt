package org.svcs.mobile.update

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.svcs.mobile.BuildConfig
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest

enum class UpdatePhase { IDLE, CHECKING, DOWNLOADING, VERIFYING, READY, ERROR }

data class UpdateState(
    val phase: UpdatePhase = UpdatePhase.IDLE,
    val error: String? = null,
    val latestVersion: String? = null,
    val releaseUrl: String? = null,
    val downloadedBytes: Long = 0,
    val totalBytes: Long = 0,
    val apkFile: File? = null,
    /** False when this install came from F-Droid - the UI must only ever
     * point such a user at the release page, never offer a direct
     * download/install action. See [UpdateManager] doc for why. */
    val selfUpdateAllowed: Boolean = true,
)

/**
 * Fall 3.18: the mobile half of the auto-update pipeline, mirroring the
 * desktop's gui.services.update_manager - check, then a SEPARATE explicit
 * download step, then a SEPARATE explicit install step, with the download
 * never trusted until its SHA256 matches the release's own SHA256SUMS.txt.
 * Same reasoning as the 2026-09-24 dishonesty audit: a feature that could
 * silently do something other than what it says (here: install an
 * unverified APK) is a liability, so every unverifiable state refuses
 * rather than falling back to "trust it anyway".
 *
 * F-DROID: this project ships through F-Droid as well as direct APK
 * sideload (see docs/RELEASE-CHECKLIST.md and the ABOUT panel in
 * ServerSettingsScreen, which already tells reviewers about bundled
 * licenses). F-Droid's inclusion policy does not allow an app to update
 * itself outside of F-Droid's own update mechanism - F-Droid rebuilds from
 * source and serves its own updates, and an app that also pulled and
 * installed its own APKs from GitHub would both violate that policy and
 * fight F-Droid's updater for control of the install. So [installedViaFDroid]
 * is checked before this ever offers a direct download/install: an F-Droid
 * install only gets a "new version available, update it from F-Droid"
 * notice pointing at the release page, never a Download/Install button.
 * A sideloaded install (this project's direct-APK flow) gets the full
 * pipeline below.
 *
 * Not a singleton like [UpdateChecker]/[ChecksumParser] because it holds a
 * StateFlow the UI observes - one instance is created and held (via
 * `remember`) by whatever screen owns the "Check for updates" UI.
 */
class UpdateManager(context: Context) {

    private val appContext = context.applicationContext
    private val client: OkHttpClient = UpdateChecker.newHttpClient()

    private val _state = MutableStateFlow(
        UpdateState(selfUpdateAllowed = !installedViaFDroid(appContext))
    )
    val state: StateFlow<UpdateState> = _state.asStateFlow()

    private fun update(block: (UpdateState) -> UpdateState) {
        _state.value = block(_state.value)
    }

    /** Fall 3.17-equivalent: check only, never downloads. Safe to call from
     * a background LaunchedEffect on every screen open. */
    suspend fun checkForUpdate(): UpdateChecker.UpdateCheckResult {
        update { it.copy(phase = UpdatePhase.CHECKING, error = null) }
        val result = withContext(Dispatchers.IO) {
            UpdateChecker.checkForUpdate(client, BuildConfig.VERSION_NAME)
        }
        update {
            it.copy(
                phase = UpdatePhase.IDLE,
                latestVersion = result.latestVersion,
                releaseUrl = result.releaseUrl,
            )
        }
        return result
    }

    /**
     * Downloads the chosen APK to this app's own external files dir (no
     * storage permission needed on modern Android) and verifies it against
     * the release's SHA256SUMS.txt before marking it READY. Callers should
     * not offer this action when [UpdateState.selfUpdateAllowed] is false
     * (F-Droid install), but this function also refuses to run in that case
     * as a second guard.
     */
    suspend fun downloadUpdate(result: UpdateChecker.UpdateCheckResult) {
        if (!_state.value.selfUpdateAllowed) {
            update {
                it.copy(phase = UpdatePhase.ERROR,
                    error = "Installed via F-Droid - update there instead.")
            }
            return
        }
        val url = result.downloadUrl
        val name = result.downloadName
        if (url.isNullOrBlank() || name.isNullOrBlank()) {
            update {
                it.copy(phase = UpdatePhase.ERROR,
                    error = "No downloadable APK for this release.")
            }
            return
        }

        update {
            it.copy(
                phase = UpdatePhase.DOWNLOADING, error = null,
                latestVersion = result.latestVersion,
                downloadedBytes = 0, totalBytes = 0, apkFile = null,
            )
        }

        withContext(Dispatchers.IO) { downloadAndVerify(url, name, result.checksumUrl) }
    }

    private fun downloadAndVerify(url: String, name: String, checksumUrl: String?) {
        val dir = File(appContext.getExternalFilesDir(null), "updates").apply { mkdirs() }
        val dest = File(dir, name)
        val tmp = File(dir, "$name.part")

        try {
            val req = Request.Builder().url(url).build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    update {
                        it.copy(phase = UpdatePhase.ERROR,
                            error = "Download failed: HTTP ${resp.code}")
                    }
                    return
                }
                val body = resp.body
                if (body == null) {
                    update {
                        it.copy(phase = UpdatePhase.ERROR,
                            error = "Download failed: empty response")
                    }
                    return
                }
                val total = body.contentLength()
                update { it.copy(totalBytes = if (total > 0) total else 0) }
                body.byteStream().use { input ->
                    FileOutputStream(tmp).use { output ->
                        val buf = ByteArray(64 * 1024)
                        var written = 0L
                        while (true) {
                            val n = input.read(buf)
                            if (n < 0) break
                            output.write(buf, 0, n)
                            written += n
                            update { it.copy(downloadedBytes = written) }
                        }
                    }
                }
            }
            tmp.copyTo(dest, overwrite = true)
            tmp.delete()
        } catch (e: Exception) {
            tmp.delete()
            update {
                it.copy(phase = UpdatePhase.ERROR,
                    error = "Download failed: ${e.message ?: e.javaClass.simpleName}")
            }
            return
        }

        update { it.copy(phase = UpdatePhase.VERIFYING) }
        val expected = if (checksumUrl != null) fetchChecksum(checksumUrl, name) else null
        if (expected == null) {
            dest.delete()
            update {
                it.copy(phase = UpdatePhase.ERROR, error =
                    "Could not verify the download's checksum (SHA256SUMS.txt " +
                        "was missing, unreachable, or didn't list this file). " +
                        "Refusing to install an unverified APK.")
            }
            return
        }

        val actual = sha256(dest)
        if (!actual.equals(expected, ignoreCase = true)) {
            dest.delete()
            update {
                it.copy(phase = UpdatePhase.ERROR, error =
                    "Checksum mismatch - the downloaded file does not match " +
                        "the published release. It has been discarded.")
            }
            return
        }

        update { it.copy(phase = UpdatePhase.READY, apkFile = dest) }
    }

    private fun fetchChecksum(url: String, fileName: String): String? = try {
        val req = Request.Builder().url(url).build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) null
            else ChecksumParser.findSha256(resp.body?.string().orEmpty(), fileName)
        }
    } catch (e: Exception) {
        null
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                digest.update(buf, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    /** True if this app can already silently install a package - if not,
     * the caller must send [unknownSourcesSettingsIntent] first. */
    fun canRequestInstalls(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            appContext.packageManager.canRequestPackageInstalls()
        } else {
            // Pre-O: "install unknown apps" is a single global Settings
            // switch the user controls directly, not a per-app grant.
            true
        }

    /** Sends the user to the per-app "install unknown apps" toggle for this
     * app. Only meaningful on API 26+ (see [canRequestInstalls]). */
    fun unknownSourcesSettingsIntent(): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
            .setData(Uri.parse("package:${appContext.packageName}"))

    /**
     * Launches the system package installer on the verified APK. Refuses
     * (returns false) unless the state is READY with a file that still
     * exists - downloadAndVerify() only ever reaches READY after the
     * checksum matched, so this can never install an unverified download.
     */
    fun installReadyUpdate(): Boolean {
        val current = _state.value
        val apk = current.apkFile
        if (current.phase != UpdatePhase.READY || apk == null || !apk.exists()) {
            update {
                it.copy(phase = UpdatePhase.ERROR,
                    error = "No verified update is ready to install.")
            }
            return false
        }
        val uri: Uri = FileProvider.getUriForFile(
            appContext, "${appContext.packageName}.fileprovider", apk,
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        appContext.startActivity(intent)
        return true
    }

    companion object {
        /**
         * True if this APK was installed by the F-Droid client. Checked via
         * the modern InstallSourceInfo API on 30+ and the deprecated
         * getInstallerPackageName below it; both return null for a plain
         * `adb install` or a manually opened APK (sideload) - exactly the
         * "direct APK sideload flow" this pipeline targets - so neither
         * path is ever mistaken for F-Droid.
         */
        fun installedViaFDroid(context: Context): Boolean {
            val pm = context.packageManager
            val installer = try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    pm.getInstallSourceInfo(context.packageName).installingPackageName
                } else {
                    @Suppress("DEPRECATION")
                    pm.getInstallerPackageName(context.packageName)
                }
            } catch (e: PackageManager.NameNotFoundException) {
                null
            } catch (e: IllegalArgumentException) {
                null
            }
            return installer == "org.fdroid.fdroid"
        }
    }
}
