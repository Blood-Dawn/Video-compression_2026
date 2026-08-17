package org.svcs.mobile.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private val Context.settingsStore by preferencesDataStore(name = "svcs_settings")

/**
 * Stores the server address and the device token.
 *
 * The token is a bearer credential for a system holding video of real people,
 * so it is encrypted at rest with AES-256-GCM under a key that lives in the
 * Android Keystore and never leaves it. Only ciphertext reaches DataStore.
 *
 * NOT `androidx.security:security-crypto` / EncryptedSharedPreferences: that
 * library was deprecated in April 2025. This is the hand-rolled equivalent of
 * what it did, using platform APIs directly, which is also fewer dependencies
 * for an AGPL project.
 *
 * The server address is stored in the clear on purpose. It is not a secret, and
 * keeping it readable means a failure to decrypt the token (see below) still
 * leaves the user looking at their own server address rather than a blank
 * screen they cannot diagnose.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */
class TokenStore(private val context: Context) {

    private companion object {
        const val KEY_ALIAS = "svcs_token_key_v1"
        const val KEYSTORE = "AndroidKeyStore"
        const val TRANSFORM = "AES/GCM/NoPadding"
        const val GCM_TAG_BITS = 128
        const val IV_BYTES = 12

        val SERVER_URL = stringPreferencesKey("server_url")
        val TOKEN_BLOB = stringPreferencesKey("token_blob")
        val LAST_LIVE_SOURCE = stringPreferencesKey("last_live_source")
        val AUTO_COMPRESS_UPLOAD = stringPreferencesKey("auto_compress_upload")
    }

    /**
     * Whether an upload should auto-start a compress (0.8.0). Defaults ON,
     * matching the behavior users saw first; the MORE screen offers the off
     * switch for people who want to upload now and choose a mode later.
     */
    suspend fun autoCompressUpload(): Boolean =
        context.settingsStore.data.first()[AUTO_COMPRESS_UPLOAD] != "off"

    suspend fun setAutoCompressUpload(on: Boolean) {
        context.settingsStore.edit {
            it[AUTO_COMPRESS_UPLOAD] = if (on) "on" else "off"
        }
    }

    /**
     * The camera source last used on the LIVE tab (M3).
     *
     * Stored in the clear, and deliberately so: this is the address the user
     * typed, and typing an RTSP URL on a phone keyboard once is enough. If it
     * carries credentials they are the user's own camera credentials, held on
     * the user's own device, and the alternative is retyping them every time.
     */
    suspend fun lastLiveSource(): String =
        context.settingsStore.data.first()[LAST_LIVE_SOURCE] ?: ""

    suspend fun setLastLiveSource(src: String) {
        context.settingsStore.edit { it[LAST_LIVE_SOURCE] = src.trim() }
    }

    suspend fun serverUrl(): String? =
        context.settingsStore.data.first()[SERVER_URL]

    suspend fun setServerUrl(url: String) {
        context.settingsStore.edit { it[SERVER_URL] = url.trim() }
    }

    /**
     * The stored device token, or null if absent or undecryptable.
     *
     * Returns null rather than throwing when the key has been invalidated,
     * which happens legitimately: the user changed their lock screen, restored
     * to a new device, or the OS rotated biometrics. The caller treats that as
     * "not paired" and asks the user to pair again, which is the only thing
     * that can actually be done about it. A crash here would strand the user
     * on a screen with no way forward.
     */
    suspend fun token(): String? {
        val blob = context.settingsStore.data.first()[TOKEN_BLOB] ?: return null
        return try {
            decrypt(blob)
        } catch (e: Exception) {
            null
        }
    }

    suspend fun setToken(token: String) {
        context.settingsStore.edit { it[TOKEN_BLOB] = encrypt(token) }
    }

    /** Forget the token. Used on unpair and after a failed decrypt. */
    suspend fun clearToken() {
        context.settingsStore.edit { it.remove(TOKEN_BLOB) }
    }

    // ── crypto ────────────────────────────────────────────────────────────

    private fun secretKey(): SecretKey {
        val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (ks.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)
            ?.let { return it.secretKey }

        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        gen.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                // Deliberately NOT setUserAuthenticationRequired(true). This
                // app fetches HLS segments in the background while the screen
                // is off, so requiring an unlock per crypto op would break
                // playback. The threat model here is a lost or stolen phone,
                // which device encryption plus per-device revocation on the
                // server already answers.
                .build(),
        )
        return gen.generateKey()
    }

    private fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val iv = cipher.iv
        val ct = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
        // iv || ciphertext, base64. The IV is not secret and GCM requires it
        // to be unique per encryption, which the Keystore provides.
        return android.util.Base64.encodeToString(
            iv + ct, android.util.Base64.NO_WRAP,
        )
    }

    private fun decrypt(blob: String): String {
        val raw = android.util.Base64.decode(blob, android.util.Base64.NO_WRAP)
        require(raw.size > IV_BYTES) { "stored blob is too short to be valid" }
        val iv = raw.copyOfRange(0, IV_BYTES)
        val ct = raw.copyOfRange(IV_BYTES, raw.size)
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(
            Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(GCM_TAG_BITS, iv),
        )
        return String(cipher.doFinal(ct), Charsets.UTF_8)
    }
}
