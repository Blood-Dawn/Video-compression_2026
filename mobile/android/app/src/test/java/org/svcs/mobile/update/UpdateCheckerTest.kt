package org.svcs.mobile.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Exercises the pure selection logic ([UpdateChecker.pickBestMobileRelease]
 * / [UpdateChecker.buildResult]) with hand-built fixtures - no HTTP mocking,
 * since [UpdateChecker.fetchReleases] is intentionally the only I/O-touching
 * function and is not covered here (mirrors the desktop's split between
 * pure selection tests and network tests).
 */
class UpdateCheckerTest {

    private fun apkAsset(name: String) = GitHubAsset(name = name, browserDownloadUrl = "https://example.test/$name")
    private fun checksumAsset() = GitHubAsset(name = "SHA256SUMS.txt", browserDownloadUrl = "https://example.test/SHA256SUMS.txt")

    @Test
    fun ignoresDraftsAndReleasesWithNoApk() {
        val releases = listOf(
            GitHubRelease(tagName = "v2.0.0", draft = true, assets = listOf(apkAsset("svcs.apk"))),
            GitHubRelease(tagName = "v1.9.0", draft = false, assets = emptyList()),
            GitHubRelease(tagName = "v1.5.0", draft = false, assets = listOf(apkAsset("svcs.apk"))),
        )
        val best = UpdateChecker.pickBestMobileRelease(releases)
        assertEquals("v1.5.0", best?.tagName)
    }

    @Test
    fun picksTheNewestApkRelease() {
        val releases = listOf(
            GitHubRelease(tagName = "v1.2.1-beta", assets = listOf(apkAsset("svcs-universal.apk"))),
            GitHubRelease(tagName = "v1.3.0-beta", assets = listOf(apkAsset("svcs-arm64-v8a.apk"))),
            GitHubRelease(tagName = "v1.0.0-beta", assets = listOf(apkAsset("svcs-universal.apk"))),
        )
        val best = UpdateChecker.pickBestMobileRelease(releases)
        assertEquals("v1.3.0-beta", best?.tagName)
    }

    @Test
    fun prefersArm64ApkOverUniversalWhenBothOffered() {
        val release = GitHubRelease(
            tagName = "v1.3.0-beta",
            htmlUrl = "https://example.test/releases/v1.3.0-beta",
            assets = listOf(apkAsset("svcs-universal.apk"), apkAsset("svcs-arm64-v8a.apk"), checksumAsset()),
        )
        val result = UpdateChecker.buildResult(listOf(release), currentVersion = "1.2.1-beta")
        assertEquals("svcs-arm64-v8a.apk", result.downloadName)
        assertEquals("https://example.test/SHA256SUMS.txt", result.checksumUrl)
        assertTrue(result.updateAvailable)
        assertTrue(result.checked)
    }

    @Test
    fun noNewerReleaseMeansNotAvailableButStillChecked() {
        val release = GitHubRelease(tagName = "v1.0.0-beta", assets = listOf(apkAsset("svcs-arm64-v8a.apk")))
        val result = UpdateChecker.buildResult(listOf(release), currentVersion = "1.2.1-beta")
        assertFalse(result.updateAvailable)
        assertTrue(result.checked)
    }

    @Test
    fun nullReleaseListNeverThrowsAndIsNotChecked() {
        val result = UpdateChecker.buildResult(null, currentVersion = "1.2.1-beta")
        assertFalse(result.checked)
        assertFalse(result.updateAvailable)
        assertNull(result.downloadUrl)
    }

    @Test
    fun emptyReleaseListIsCheckedButHasNoDownload() {
        val result = UpdateChecker.buildResult(emptyList(), currentVersion = "1.2.1-beta")
        assertTrue(result.checked)
        assertFalse(result.updateAvailable)
        assertNull(result.downloadUrl)
    }

    @Test
    fun missingChecksumAssetLeavesChecksumUrlNull() {
        val release = GitHubRelease(tagName = "v1.3.0-beta", assets = listOf(apkAsset("svcs-arm64-v8a.apk")))
        val result = UpdateChecker.buildResult(listOf(release), currentVersion = "1.2.1-beta")
        assertNull(result.checksumUrl)
    }
}
