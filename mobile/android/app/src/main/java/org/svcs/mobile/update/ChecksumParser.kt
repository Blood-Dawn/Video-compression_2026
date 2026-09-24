package org.svcs.mobile.update

/**
 * Parses a `SHA256SUMS.txt`-style body (`<hex>  <filename>` per line,
 * optionally with a leading `*` on the filename for binary mode) - the same
 * format every release in this project publishes (see
 * docs/RELEASE-CHECKLIST.md) and the same format the desktop's
 * `update_manager._fetch_checksum` parses. Split out as pure string logic,
 * with no Android or network dependency, so it is trivially unit-testable.
 */
object ChecksumParser {

    /** The lowercase sha256 hex digest for `fileName`, or null if the file
     * isn't listed or a line can't be parsed. Callers MUST treat null as
     * "cannot verify", never as "verified". */
    fun findSha256(body: String, fileName: String): String? {
        val target = fileName.trim().lowercase()
        for (rawLine in body.lineSequence()) {
            val line = rawLine.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            val parts = line.split(Regex("\\s+"), limit = 2)
            if (parts.size != 2) continue
            val digest = parts[0].trim().lowercase()
            val name = parts[1].trim().trimStart('*').trim().lowercase()
            if (digest.length == 64 && (name == target || name.endsWith("/$target"))) {
                return digest
            }
        }
        return null
    }
}
