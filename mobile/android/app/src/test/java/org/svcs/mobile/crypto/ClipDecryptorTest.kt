package org.svcs.mobile.crypto

import java.io.File
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * Vectors were written by the desktop's own src/utils/encryption.py, so a pass
 * here means the phone opens what the desktop encrypts.
 */
class ClipDecryptorTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    private val plain = hex("53564353207465737420636c697020000102ff53564353207465737420636c697020000102ff53564353207465737420636c697020000102ff")
    private val pwEnc = hex("5a7445acb399ac00a820926a69245a40fe8f9ecde2a3b010dad662285033bb16d2b15264926eaae0ecf12c8ba7994972511c7ae14cbb1663a42229bb7cdf577ad6ceabb4192ef153c67180a60ab68abcb0497788cb82600359e8d0bbe4532e384ef45a4b4c")
    private val keyEnc = hex("47f5ec17c2dfba9c8d8a37180000000000000000000000000000000043bdc2b98ef208d70aae43357c9de1318020ef05da277d45f8c5194c073246c71c98022ad97a1ef11084e1a23e7b93cbd9835ed2a8a3c26c3c6826aec908862e78ef7d248ab4ebc01e")

    private fun enc(bytes: ByteArray): File = tmp.newFile().also { it.writeBytes(bytes) }

    @Test fun opensPasswordClip() {
        val out = File(tmp.root, "o.mp4")
        val r = ClipDecryptor.decrypt(enc(pwEnc), out, password = "correct horse battery".toCharArray())
        assertTrue(r is ClipDecryptor.Result.Ok)
        assertArrayEquals(plain, out.readBytes())
    }

    @Test fun opensRawKeyClip() {
        val out = File(tmp.root, "o2.mp4")
        val r = ClipDecryptor.decrypt(enc(keyEnc), out, rawKey = ByteArray(32) { it.toByte() })
        assertTrue(r is ClipDecryptor.Result.Ok)
        assertArrayEquals(plain, out.readBytes())
    }

    @Test fun wrongPasswordLeavesNoFile() {
        val out = File(tmp.root, "o3.mp4")
        val r = ClipDecryptor.decrypt(enc(pwEnc), out, password = "nope".toCharArray())
        assertEquals(ClipDecryptor.Result.WrongKeyOrCorrupt, r)
        assertFalse(out.exists())
    }

    @Test fun tamperedClipIsRejected() {
        val bad = pwEnc.copyOf().also { it[it.size - 1] = (it[it.size - 1].toInt() xor 1).toByte() }
        val out = File(tmp.root, "o4.mp4")
        val r = ClipDecryptor.decrypt(enc(bad), out, password = "correct horse battery".toCharArray())
        assertEquals(ClipDecryptor.Result.WrongKeyOrCorrupt, r)
        assertFalse(out.exists())
    }

    @Test fun shortFileAndBadKeyFile() {
        val out = File(tmp.root, "o5.mp4")
        assertEquals(ClipDecryptor.Result.NotAnEncryptedClip,
            ClipDecryptor.decrypt(enc(ByteArray(10)), out, password = "x".toCharArray()))
        assertEquals(ClipDecryptor.Result.BadKeyFile,
            ClipDecryptor.decrypt(enc(keyEnc), out, rawKey = ByteArray(5)))
    }
}
