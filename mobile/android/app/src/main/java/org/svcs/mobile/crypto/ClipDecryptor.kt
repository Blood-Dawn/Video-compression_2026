package org.svcs.mobile.crypto

import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * Opens the .enc clips the desktop writes (src/utils/encryption.py).
 *
 * Layout: nonce (12) | salt (16) | GCM tag (16) | ciphertext. Password mode
 * derives the key with PBKDF2-HMAC-SHA256, 600,000 iterations. Raw-key mode
 * takes a 32 byte key file and ignores the salt.
 *
 * The password and key stay on the phone. Decryption runs here, never on the
 * server.
 *
 * Android's GCM decrypt holds the ciphertext until the tag is checked, so
 * clips above [MAX_BYTES] are refused instead of risking an out-of-memory
 * crash. Segments the desktop writes are far smaller than that.
 *
 * Author: Bloodawn (KheivenD), 2026-11-24 (3.0 dev).
 */
object ClipDecryptor {

    const val NONCE_SIZE = 12
    const val SALT_SIZE = 16
    const val TAG_SIZE = 16
    const val HEADER_SIZE = NONCE_SIZE + SALT_SIZE + TAG_SIZE
    const val PBKDF2_ITERS = 600_000
    const val MAX_BYTES = 200L * 1024 * 1024

    sealed interface Result {
        data class Ok(val output: File) : Result
        /** Wrong password or key, or the file was changed after encryption. */
        data object WrongKeyOrCorrupt : Result
        data object NotAnEncryptedClip : Result
        data object TooLarge : Result
        data object BadKeyFile : Result
    }

    fun deriveKey(password: CharArray, salt: ByteArray): ByteArray {
        val spec = PBEKeySpec(password, salt, PBKDF2_ITERS, 256)
        try {
            return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                .generateSecret(spec).encoded
        } finally {
            spec.clearPassword()
        }
    }

    /** Decrypt [input] into [output]. Exactly one of [password] or [rawKey]. */
    fun decrypt(
        input: File,
        output: File,
        password: CharArray? = null,
        rawKey: ByteArray? = null,
    ): Result {
        if (rawKey != null && rawKey.size != 32) return Result.BadKeyFile
        val size = input.length()
        if (size <= HEADER_SIZE) return Result.NotAnEncryptedClip
        if (size > MAX_BYTES) return Result.TooLarge
        val header = ByteArray(HEADER_SIZE)
        RandomAccessFile(input, "r").use { it.readFully(header) }
        val nonce = header.copyOfRange(0, NONCE_SIZE)
        val salt = header.copyOfRange(NONCE_SIZE, NONCE_SIZE + SALT_SIZE)
        val tag = header.copyOfRange(NONCE_SIZE + SALT_SIZE, HEADER_SIZE)
        val keyBytes = when {
            rawKey != null -> rawKey
            password != null -> deriveKey(password, salt)
            else -> return Result.BadKeyFile
        }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.DECRYPT_MODE,
            SecretKeySpec(keyBytes, "AES"),
            GCMParameterSpec(TAG_SIZE * 8, nonce),
        )
        output.parentFile?.mkdirs()
        try {
            RandomAccessFile(input, "r").use { src ->
                src.seek(HEADER_SIZE.toLong())
                FileOutputStream(output).use { dst ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = src.read(buf)
                        if (n < 0) break
                        cipher.update(buf, 0, n)?.let { if (it.isNotEmpty()) dst.write(it) }
                    }
                    // The tag is stored in the header, so it goes in last.
                    dst.write(cipher.doFinal(tag))
                }
            }
        } catch (e: AEADBadTagException) {
            output.delete()
            return Result.WrongKeyOrCorrupt
        } catch (e: javax.crypto.BadPaddingException) {
            output.delete()
            return Result.WrongKeyOrCorrupt
        }
        return Result.Ok(output)
    }
}
