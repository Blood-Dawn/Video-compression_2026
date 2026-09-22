package org.svcs.mobile.net

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Mirrors tests/test_network_guidance.py on the Python side.
 *
 * NOTE: this test has NEVER BEEN RUN. There is no JDK, Android SDK, or Gradle
 * in the environment where this module was written, so it has not been compiled
 * either. Treat it as a specification of intended behavior until someone runs
 * `./gradlew test` and reports back. See mobile/android/README.md.
 *
 * The two cases most worth keeping are the CGNAT and TEST-NET ones: both got
 * the equivalent Python implementation wrong on the first attempt.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */
class HostClassifierTest {

    @Test
    fun `loopback is private`() {
        assertTrue(HostClassifier.isPrivate("127.0.0.1"))
        assertTrue(HostClassifier.isPrivate("localhost"))
        assertTrue(HostClassifier.isPrivate("::1"))
    }

    @Test
    fun `rfc1918 ranges are private`() {
        assertTrue(HostClassifier.isPrivate("192.168.1.42"))
        assertTrue(HostClassifier.isPrivate("10.0.0.5"))
        assertTrue(HostClassifier.isPrivate("172.16.3.9"))
    }

    @Test
    fun `link local is private`() {
        assertTrue(HostClassifier.isPrivate("169.254.1.1"))
    }

    @Test
    fun `rfc4193 unique local is private`() {
        assertTrue(HostClassifier.isPrivate("fd00::1"))
    }

    @Test
    fun `tailscale cgnat range is private`() {
        // The one that matters most: Tailscale is the VPN this project
        // recommends, and warning about it would train users to ignore the
        // warning. Java's isSiteLocalAddress does NOT cover 100.64.0.0/10.
        assertTrue(HostClassifier.isPrivate("100.64.0.1"))
        assertTrue(HostClassifier.isPrivate("100.115.92.4"))
        assertTrue(HostClassifier.isPrivate("100.127.255.254"))
    }

    @Test
    fun `addresses just outside cgnat are not private`() {
        assertFalse(HostClassifier.isPrivate("100.63.255.255"))
        assertFalse(HostClassifier.isPrivate("100.128.0.1"))
    }

    @Test
    fun `public addresses are not private`() {
        assertFalse(HostClassifier.isPrivate("8.8.8.8"))
        assertFalse(HostClassifier.isPrivate("1.1.1.1"))
    }

    @Test
    fun `unspecified address is not private`() {
        // 0.0.0.0 is the server's default BIND, not a client target, but it
        // must not be mistaken for "local" just because it is not routable.
        assertFalse(HostClassifier.isPrivate("0.0.0.0"))
    }

    @Test
    fun `hostnames are not classified without dns`() {
        // Resolving would be a blocking network call, and a name that resolves
        // to a LAN address today can point elsewhere tomorrow.
        assertFalse(HostClassifier.isPrivate("my-nas.example.com"))
        assertFalse(HostClassifier.isPrivate("svcs.local"))
    }

    @Test
    fun `blank input is not private`() {
        assertFalse(HostClassifier.isPrivate(""))
        assertFalse(HostClassifier.isPrivate("   "))
    }

    @Test
    fun `consent is required exactly when not private`() {
        assertFalse(HostClassifier.requiresExplicitConsent("192.168.1.1"))
        assertTrue(HostClassifier.requiresExplicitConsent("8.8.8.8"))
    }
}
