package org.svcs.mobile.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ChecksumParserTest {

    private val sample = """
        # SHA256 checksums for release v1.2.1-beta
        3b1c1b6f6f6a6d6c6e6f6a6d6c6e6f6a6d6c6e6f6a6d6c6e6f6a6d6c6e6f6a6d  svcs-1.2.1-beta-arm64-v8a.apk
        4c2d2c7d7d7b7d6f7d7f7b7d6f7d7f7b7d6f7d7f7b7d6f7d7f7b7d6f7d7f7b7e *svcs-1.2.1-beta-universal.apk
        not-a-valid-line-at-all
    """.trimIndent()

    @Test
    fun findsTheMatchingFileCaseInsensitively() {
        assertEquals(
            "3b1c1b6f6f6a6d6c6e6f6a6d6c6e6f6a6d6c6e6f6a6d6c6e6f6a6d6c6e6f6a6d",
            ChecksumParser.findSha256(sample, "SVCS-1.2.1-beta-ARM64-V8A.apk"),
        )
    }

    @Test
    fun stripsTheLeadingBinaryModeStar() {
        assertEquals(
            "4c2d2c7d7d7b7d6f7d7f7b7d6f7d7f7b7d6f7d7f7b7d6f7d7f7b7d6f7d7f7b7e",
            ChecksumParser.findSha256(sample, "svcs-1.2.1-beta-universal.apk"),
        )
    }

    @Test
    fun returnsNullWhenFileIsNotListed() {
        assertNull(ChecksumParser.findSha256(sample, "svcs-does-not-exist.apk"))
    }

    @Test
    fun returnsNullOnEmptyOrGarbageBody() {
        assertNull(ChecksumParser.findSha256("", "svcs.apk"))
        assertNull(ChecksumParser.findSha256("not even close to the format", "svcs.apk"))
    }

    @Test
    fun matchesAPathPrefixedEntry() {
        val body = "5d3e3d8e8e8c8e7f8e8f8c8e7f8e8f8c8e7f8e8f8c8e7f8e8f8c8e7f8e8f8c8f  dist/svcs.apk"
        assertEquals(
            "5d3e3d8e8e8c8e7f8e8f8c8e7f8e8f8c8e7f8e8f8c8e7f8e8f8c8e7f8e8f8c8f",
            ChecksumParser.findSha256(body, "svcs.apk"),
        )
    }
}
