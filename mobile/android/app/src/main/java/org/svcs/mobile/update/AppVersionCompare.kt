package org.svcs.mobile.update

/**
 * Fall 3.18: version-comparison logic ported 1:1 from the desktop's
 * src/utils/version.py (parse_version/is_newer) so both platforms agree on
 * "newer", including its specific defensive behavior: a tag that doesn't
 * look like this project's own version strings (major.minor.patch, plus an
 * optional dev/alpha/beta/rc stage) parses to the lowest possible value
 * rather than raising or being treated as newer. That is deliberate - the
 * historical mobile tag "v1-beta" (no minor/patch numbers) is exactly this
 * case, and a malformed or unexpected GitHub tag must never be mistaken for
 * an update.
 *
 * Stage ranking and the "no suffix ranks highest" rule are copied verbatim
 * from the desktop's _STAGE_RANK / _VERSION_RE - see that file's comments
 * for why (a same-numbered beta must outrank a same-numbered dev build).
 */
object AppVersionCompare {

    private val STAGE_RANK: Map<String, Int> = mapOf(
        "dev" to 0,
        "alpha" to 1,
        "a" to 1,
        "beta" to 2,
        "b" to 2,
        "rc" to 3,
        "" to 4,
    )

    // Mirrors the desktop's _VERSION_RE: "2.2.0", "v2.2.0", "2.2.0.dev1",
    // "2.2.0-beta", "2.2.0-beta2", "2.2.0b1", "2.2.0rc1".
    private val VERSION_RE = Regex(
        "^[vV]?(\\d+)\\.(\\d+)\\.(\\d+)(?:[.\\-]?(dev|alpha|a|beta|b|rc)(\\d*))?$"
    )

    data class Parsed(
        val major: Int,
        val minor: Int,
        val patch: Int,
        val stageRank: Int,
        val stageNum: Int,
    ) : Comparable<Parsed> {
        override fun compareTo(other: Parsed): Int {
            var c = major.compareTo(other.major)
            if (c != 0) return c
            c = minor.compareTo(other.minor)
            if (c != 0) return c
            c = patch.compareTo(other.patch)
            if (c != 0) return c
            c = stageRank.compareTo(other.stageRank)
            if (c != 0) return c
            return stageNum.compareTo(other.stageNum)
        }

        companion object {
            val LOWEST = Parsed(0, 0, 0, 0, 0)
        }
    }

    /**
     * Parses a version string into a value that sorts correctly. Anything
     * that doesn't match [VERSION_RE] returns [Parsed.LOWEST] - the lowest
     * possible value - rather than throwing, so a malformed or unexpected
     * tag from GitHub can never be mistaken for a newer release; it is
     * silently ignored by the comparison.
     */
    fun parse(raw: String?): Parsed {
        val match = VERSION_RE.matchEntire(raw?.trim().orEmpty()) ?: return Parsed.LOWEST
        val (major, minor, patch, stage, num) = match.destructured
        return Parsed(
            major = major.toInt(),
            minor = minor.toInt(),
            patch = patch.toInt(),
            stageRank = STAGE_RANK[stage] ?: 4,
            stageNum = if (num.isBlank()) 0 else num.toInt(),
        )
    }

    /** True if [candidate] (e.g. a GitHub release tag) is a newer version
     * than [current] (this build's own version). */
    fun isNewer(candidate: String?, current: String?): Boolean =
        parse(candidate) > parse(current)
}
