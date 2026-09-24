package org.svcs.mobile.update

import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Fall 3.18: checks GitHub releases for a newer MOBILE build, mirroring the
 * desktop's `gui.services.update_manager.check_for_update()` (same repo,
 * same releases endpoint, same "silent on any failure" contract) but with
 * the roles reversed: a desktop release is picked by "has a .exe asset",
 * a mobile release here is picked by "has an .apk asset" - the two filters
 * are naturally disjoint since no release in this project's history has
 * shipped both.
 *
 * The pure selection logic ([pickBestMobileRelease]) is split from the
 * network call ([fetchReleases]) on purpose: it takes an already-parsed
 * `List<GitHubRelease>` and returns a result with no I/O, so it is
 * unit-testable with hand-built fixtures and needs no HTTP mocking
 * (UpdateCheckerTest.kt exercises it directly).
 */
object UpdateChecker {

    const val RELEASES_URL =
        "https://api.github.com/repos/Blood-Dawn/Video-compression_2026/releases"
    private const val USER_AGENT = "SVCS-mobile-update-check"
    private const val CHECKSUM_ASSET_NAME = "sha256sums.txt"

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    data class UpdateCheckResult(
        val currentVersion: String,
        val latestVersion: String? = null,
        val updateAvailable: Boolean = false,
        val releaseUrl: String? = null,
        val downloadUrl: String? = null,
        val downloadName: String? = null,
        val checksumUrl: String? = null,
        val checked: Boolean = false,
    )

    /** True if a release ships at least one `.apk` asset. */
    private fun hasApkAsset(release: GitHubRelease): Boolean =
        release.assets.any { it.name.lowercase().endsWith(".apk") }

    /**
     * Pure selection: the newest non-draft release with an APK asset.
     * Prereleases are NOT excluded - every release this project has
     * published so far is a beta, same reasoning as the desktop side.
     */
    fun pickBestMobileRelease(releases: List<GitHubRelease>): GitHubRelease? {
        var best: GitHubRelease? = null
        var bestTag: String? = null
        for (rel in releases) {
            if (rel.draft || rel.tagName.isBlank() || !hasApkAsset(rel)) continue
            if (bestTag == null || AppVersionCompare.isNewer(rel.tagName, bestTag)) {
                bestTag = rel.tagName
                best = rel
            }
        }
        return best
    }

    /**
     * Builds the full check result from a release list + the running app's
     * own version. Picks the arm64 APK over a universal one when both are
     * offered (smaller download, and this project's release checklist
     * always ships arm64 - see docs/RELEASE-CHECKLIST.md).
     */
    fun buildResult(releases: List<GitHubRelease>?, currentVersion: String): UpdateCheckResult {
        val base = UpdateCheckResult(currentVersion = currentVersion)
        if (releases == null) return base

        val best = pickBestMobileRelease(releases) ?: return base.copy(checked = true)
        val apkAssets = best.assets.filter { it.name.lowercase().endsWith(".apk") }
        val chosenApk = apkAssets.firstOrNull { !it.name.lowercase().contains("universal") }
            ?: apkAssets.firstOrNull()
        val checksumAsset = best.assets.firstOrNull {
            it.name.lowercase() == CHECKSUM_ASSET_NAME
        }

        return base.copy(
            latestVersion = best.tagName,
            updateAvailable = AppVersionCompare.isNewer(best.tagName, currentVersion),
            releaseUrl = best.htmlUrl.ifBlank { null },
            downloadUrl = chosenApk?.browserDownloadUrl,
            downloadName = chosenApk?.name,
            checksumUrl = checksumAsset?.browserDownloadUrl,
            checked = true,
        )
    }

    /** Best-effort fetch: the parsed release list, or null on ANY failure
     * (offline, GitHub down/rate-limited, an unparseable body). Never
     * throws - a flaky background check must never crash the app. */
    fun fetchReleases(client: OkHttpClient): List<GitHubRelease>? = try {
        val req = Request.Builder()
            .url(RELEASES_URL)
            .header("Accept", "application/vnd.github+json")
            .header("User-Agent", USER_AGENT)
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) null
            else json.decodeFromString<List<GitHubRelease>>(resp.body?.string().orEmpty())
        }
    } catch (e: Exception) {
        null
    }

    /** One-call convenience: fetch + build the result, never throwing. */
    fun checkForUpdate(client: OkHttpClient, currentVersion: String): UpdateCheckResult =
        buildResult(fetchReleases(client), currentVersion)

    /** A short-timeout client for this check alone - GitHub, not the SVCS
     * server, so it must not reuse SvcsApi's auth-interceptor client. */
    fun newHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .build()
}
