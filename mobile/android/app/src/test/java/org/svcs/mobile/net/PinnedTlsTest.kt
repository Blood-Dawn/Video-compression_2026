package org.svcs.mobile.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test
import java.io.ByteArrayInputStream
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate

/**
 * The phone trusts exactly one certificate for an https server: the one whose
 * SHA-256 fingerprint was pinned at pairing. Also covers the pairing link the
 * dashboard's QR code carries.
 *
 * The certificate below is a throwaway made by the desktop's tls_cert module
 * for this test; its private key was not kept.
 *
 * Author: Bloodawn (KheivenD), 2026-11-25.
 */
class PinnedTlsTest {

    private val pem = """
            -----BEGIN CERTIFICATE-----
            MIIBYzCCAQqgAwIBAgIULpixzNLu9ypv/O6ziHzxfe3d7KEwCgYIKoZIzj0EAwIw
            FjEUMBIGA1UEAwwLU1ZDUyBzZXJ2ZXIwHhcNMjYxMTI0MjIxODA4WhcNMzYxMTIy
            MjIxODA4WjAWMRQwEgYDVQQDDAtTVkNTIHNlcnZlcjBZMBMGByqGSM49AgEGCCqG
            SM49AwEHA0IABNyT3+cw1DL607KB0SkM/GgTjbM/6dSwX3R+LqHRIVyJmtjaggl0
            OAAC/Mm565uvUuz9ea/z1ddAOaEUI4BmaMCjNjA0MCQGA1UdEQQdMBuCCWxvY2Fs
            aG9zdIICdm2HBH8AAAGHBMAAAgIwDAYDVR0TAQH/BAIwADAKBggqhkjOPQQDAgNH
            ADBEAiBUX4SZWedoXJI+gNPf0sExrHHmHeJ6qwuSzKEQa+0rLQIgTeowccZg+MLb
            zT+VwIDun5AZUYg16pqpPXLhtQ0OOWQ=
            -----END CERTIFICATE-----
    """.trimIndent()

    private val fingerprint = "7498104ad913eef445de029213193f0242fea7231d40a89e1d6698ec98aa4a2d"

    private fun cert(): X509Certificate =
        CertificateFactory.getInstance("X.509")
            .generateCertificate(ByteArrayInputStream(pem.toByteArray())) as X509Certificate

    @Test
    fun fingerprintMatchesTheDesktopsAlgorithm() {
        assertEquals(fingerprint, PinnedTls.fingerprintOf(cert()))
    }

    @Test
    fun normalizeAcceptsColonsAndUpperCase() {
        val spaced = fingerprint.uppercase().chunked(2).joinToString(":")
        assertEquals(fingerprint, PinnedTls.normalize(spaced))
    }

    @Test
    fun normalizeRejectsWrongLengthOrNonHex() {
        assertNull(PinnedTls.normalize(null))
        assertNull(PinnedTls.normalize(""))
        assertNull(PinnedTls.normalize(fingerprint.dropLast(1)))
        assertNull(PinnedTls.normalize("z".repeat(64)))
    }

    @Test
    fun matchingCertificateIsTrusted() {
        PinnedTls.PinnedTrustManager(fingerprint)
            .checkServerTrusted(arrayOf(cert()), "ECDHE_ECDSA")
    }

    @Test
    fun anyOtherCertificateIsRefused() {
        val other = "0".repeat(64)
        assertThrows(CertificateException::class.java) {
            PinnedTls.PinnedTrustManager(other)
                .checkServerTrusted(arrayOf(cert()), "ECDHE_ECDSA")
        }
    }

    @Test
    fun emptyChainIsRefused() {
        assertThrows(CertificateException::class.java) {
            PinnedTls.PinnedTrustManager(fingerprint)
                .checkServerTrusted(emptyArray(), "ECDHE_ECDSA")
        }
    }

    @Test
    fun pairingLinkWithFingerprintParses() {
        val link = "svcs://pair?u=https%3A%2F%2F192.168.1.5%3A5443&t=svcs_abc&fp=$fingerprint"
        val p = PairingCode.parse(link)
        assertNotNull(p)
        assertEquals("https://192.168.1.5:5443", p!!.url)
        assertEquals("svcs_abc", p.token)
        assertEquals(fingerprint, p.fingerprint)
    }

    @Test
    fun pairingLinkWithoutFingerprintParses() {
        val p = PairingCode.parse("svcs://pair?u=http%3A%2F%2F10.0.0.2%3A5000&t=tok")
        assertNotNull(p)
        assertNull(p!!.fingerprint)
    }

    @Test
    fun badPairingLinksAreRejected() {
        assertNull(PairingCode.parse("http://example.com"))
        assertNull(PairingCode.parse("svcs://pair?u=http%3A%2F%2Fx"))          // no token
        assertNull(PairingCode.parse("svcs://pair?t=tok"))                      // no address
        assertNull(PairingCode.parse("svcs://pair?u=http%3A%2F%2Fx&t=t&fp=abc")) // bad fingerprint
    }
}
