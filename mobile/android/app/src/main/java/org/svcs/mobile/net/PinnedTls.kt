package org.svcs.mobile.net

import okhttp3.OkHttpClient
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/**
 * HTTPS to a server that has a self-signed certificate, safely.
 *
 * The desktop server makes its own certificate, so there is no authority to
 * check it against. Instead the pairing carries the certificate's SHA-256
 * fingerprint (shown in the dashboard's Pair panel and inside its QR code),
 * and this trust manager accepts exactly one certificate: the one whose
 * fingerprint matches. Anyone else on the Wi-Fi presenting a different
 * certificate fails the handshake.
 *
 * Because the certificate itself is pinned, the host name check is skipped.
 * The server's address can change (DHCP) without the pinned certificate
 * changing, and a matching fingerprint already proves who we are talking to.
 *
 * Author: Bloodawn (KheivenD), 2026-11-25.
 */
object PinnedTls {

    /** 64 hex characters, any case, optional colons or spaces; null if invalid. */
    fun normalize(raw: String?): String? {
        val hex = raw.orEmpty().filter { it.isLetterOrDigit() }.lowercase()
        return if (hex.length == 64 && hex.all { it in '0'..'9' || it in 'a'..'f' }) hex else null
    }

    fun fingerprintOf(cert: X509Certificate): String =
        MessageDigest.getInstance("SHA-256").digest(cert.encoded)
            .joinToString("") { "%02x".format(it) }

    /** Trusts only a leaf certificate whose SHA-256 equals [expectedHex]. */
    class PinnedTrustManager(expectedHex: String) : X509TrustManager {
        private val expected = normalize(expectedHex)
            ?: throw IllegalArgumentException("fingerprint must be 64 hex characters")

        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            val leaf = chain?.firstOrNull()
                ?: throw CertificateException("server sent no certificate")
            if (fingerprintOf(leaf) != expected) {
                throw CertificateException(
                    "server certificate does not match the pinned fingerprint",
                )
            }
            leaf.checkValidity()
        }

        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            throw CertificateException("client certificates are not used")
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    /**
     * Pin [fingerprint] on this builder. A null or malformed fingerprint
     * leaves the builder untouched (normal system trust), so an https address
     * with a real certificate still works.
     */
    fun apply(builder: OkHttpClient.Builder, fingerprint: String?): OkHttpClient.Builder {
        val fp = normalize(fingerprint) ?: return builder
        val tm = PinnedTrustManager(fp)
        val ctx = SSLContext.getInstance("TLS").apply {
            init(null, arrayOf<TrustManager>(tm), SecureRandom())
        }
        return builder
            .sslSocketFactory(ctx.socketFactory, tm)
            .hostnameVerifier(HostnameVerifier { _, _ -> true })
    }
}

/** What the dashboard's Pair QR code carries: svcs://pair?u=<url>&t=<token>[&fp=<hex>]. */
data class PairingCode(val url: String, val token: String, val fingerprint: String?) {
    companion object {
        /** Null when [code] is not an SVCS pairing link, or its fingerprint is malformed. */
        fun parse(code: String): PairingCode? {
            val raw = code.trim()
            if (!raw.startsWith("svcs://pair?")) return null
            val q = raw.substringAfter('?').split('&').mapNotNull {
                val i = it.indexOf('=')
                if (i <= 0) null
                else it.substring(0, i) to java.net.URLDecoder.decode(it.substring(i + 1), "UTF-8")
            }.toMap()
            val u = q["u"]?.takeIf { it.isNotBlank() } ?: return null
            val t = q["t"]?.takeIf { it.isNotBlank() } ?: return null
            val fp = PinnedTls.normalize(q["fp"])
            if (q["fp"] != null && fp == null) return null
            return PairingCode(u, t, fp)
        }
    }
}
