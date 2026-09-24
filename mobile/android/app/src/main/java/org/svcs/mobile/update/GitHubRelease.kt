package org.svcs.mobile.update

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Minimal shape of a GitHub Releases API entry - only the fields
 * [UpdateChecker] actually needs, so a future API field never breaks
 * deserialization (ignoreUnknownKeys is set on the Json instance too). */
@Serializable
data class GitHubRelease(
    @SerialName("tag_name") val tagName: String = "",
    @SerialName("html_url") val htmlUrl: String = "",
    val draft: Boolean = false,
    val assets: List<GitHubAsset> = emptyList(),
)

@Serializable
data class GitHubAsset(
    val name: String = "",
    @SerialName("browser_download_url") val browserDownloadUrl: String = "",
)
