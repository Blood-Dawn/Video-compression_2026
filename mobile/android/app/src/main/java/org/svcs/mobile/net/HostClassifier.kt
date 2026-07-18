package org.svcs.mobile.net

import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress

/**
 * Classifies a server address as private (safe to reach over cleartext on a
 * network the user controls) or not.
 *
 * This is a deliberate mirror of `is_private_bind()` in `src/gui/auth.py`, and
 * the two must agree. The Python side is covered by
 * `tests/test_network_guidance.py`; keep both in step when editing either.
 *
 * Why the app enforces this at all: the SVCS server speaks plain HTTP with no
 * TLS, so HTTP Basic and Bearer credentials cross the wire in the clear on
 * every request, including every 2-second HLS segment. Android blocks cleartext
 * by default from API 28, and the network security config that re-permits it is
 * a BUILD-TIME compiled resource with no runtime API and no CIDR or wildcard
 * support, so "add the user's host at runtime" is not implementable. The
 * workable posture is therefore: permit cleartext narrowly in the manifest, and
 * refuse in code to send credentials anywhere that is not plausibly the user's
 * own network.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */
object HostClassifier {

    /** RFC 6598 CGNAT: 100.64.0.0/10. Tailscale hands out addresses here. */
    private const val CGNAT_PREFIX = 100
    private const val CGNAT_SECOND_LOW = 64
    private const val CGNAT_SECOND_HIGH = 127

    /**
     * True when [host] is loopback, RFC1918, link-local, RFC4193 unique-local,
     * or the RFC6598 CGNAT range.
     *
     * Returns false for anything it cannot classify, including hostnames it
     * will not resolve. Failing toward "warn the user" is far cheaper than
     * silently shipping credentials and surveillance footage to a public host.
     */
    fun isPrivate(host: String): Boolean {
        val h = host.trim().lowercase().removeSurrounding("[", "]")
        if (h.isEmpty()) return false
        if (h == "localhost") return true

        val addr = parseLiteral(h) ?: return false
        // 0.0.0.0 and :: bind every interface. Not an address a client dials,
        // but reject explicitly rather than letting isAnyLocalAddress slip by.
        if (addr.isAnyLocalAddress) return false
        if (addr.isLoopbackAddress) return true
        if (addr.isLinkLocalAddress || addr.isSiteLocalAddress) return true

        return when (addr) {
            is Inet4Address -> isCgnat(addr)
            // RFC4193 unique-local fc00::/7. isSiteLocalAddress covers the
            // deprecated fec0::/10 only, so check the modern range here.
            is Inet6Address -> (addr.address[0].toInt() and 0xFE) == 0xFC
            else -> false
        }
    }

    /** True when the address is one the app should refuse without an override. */
    fun requiresExplicitConsent(host: String): Boolean = !isPrivate(host)

    private fun isCgnat(addr: Inet4Address): Boolean {
        val b = addr.address
        val first = b[0].toInt() and 0xFF
        val second = b[1].toInt() and 0xFF
        return first == CGNAT_PREFIX && second in CGNAT_SECOND_LOW..CGNAT_SECOND_HIGH
    }

    /**
     * Parse a literal IP without ever performing a DNS lookup.
     *
     * [InetAddress.getByName] resolves hostnames, which would mean a blocking
     * network call on whatever thread this runs on, and would also let a
     * hostname that currently resolves to a LAN address pass the check and
     * later point somewhere else. Literals only.
     */
    private fun parseLiteral(host: String): InetAddress? {
        val looksNumeric = host.all { it.isDigit() || it == '.' } ||
            host.contains(':')
        if (!looksNumeric) return null
        return try {
            InetAddress.getByName(host)
        } catch (e: Exception) {
            null
        }
    }
}
