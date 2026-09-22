package org.svcs.mobile.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Instrumented test for pairing persistence (Week 4 TASK 4.1/4.2).
 *
 * Diagnosis (4.1): an earlier `main` -> `mobile` merge silently deleted the
 * entire `app/src/main/` source tree for the Android module - including
 * this class's subject, [TokenStore] itself - because `main` had already
 * dropped the whole Android app in an earlier commit and `mobile` had not
 * touched most of those files since the branches' common ancestor, so git's
 * three-way merge applied the deletion with no conflict to flag. The module
 * did not even compile on `mobile` afterward. All 35 silently-deleted files
 * were restored from `mobile`'s pre-merge tip.
 *
 * The existing JVM unit test (ServerSettingsViewModelTest, under
 * app/src/test/) covers the ViewModel layer with a FAKE api, but its own
 * comments flag the save-path assertion as not fully deterministic: TokenStore
 * writes through DataStore's real internal dispatcher, which a
 * kotlinx-coroutines-test virtual clock cannot drive to completion, so that
 * one assertion can read stale state depending on scheduling. That is a test
 * environment limitation, not evidence the write itself is unreliable.
 *
 * This test proves the actual requirement in 4.2 - "a phone that pairs once
 * stays paired across restarts and app updates" - directly and
 * deterministically, on a real device/emulator with a real filesystem and
 * real dispatchers, with none of the virtual-time caveats above:
 *
 *   1. Write a server URL and a token through one [TokenStore] instance.
 *   2. Construct a BRAND NEW [TokenStore] instance against the same real
 *      [android.content.Context] - [TokenStore] keeps no in-memory cache, so
 *      a fresh instance re-reading from the on-disk DataStore file is the
 *      direct on-device equivalent of the app process being killed and
 *      relaunched (a restart or an update both end the process the same
 *      way; neither can leave anything sitting in memory).
 *   3. Confirm the new instance reads back the exact URL and, after a real
 *      Android Keystore round-trip, the exact token - not just "something",
 *      the SAME plaintext that was written, encrypted at rest the whole time.
 *
 * Run with: `./gradlew connectedDebugAndroidTest` against a device or
 * emulator (API 26+, since TokenStore's Keystore usage needs a real
 * hardware-or-software-backed keystore that Robolectric cannot fake).
 *
 * Author: Bloodawn (KheivenD), Week 4 (4.1/4.2).
 */
@RunWith(AndroidJUnit4::class)
class TokenStorePersistenceTest {

    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Before
    fun clearAnyPriorState() {
        // Hermetic: a previous run (or a real pairing on this test device)
        // must not leak into this test's assertions.
        //
        // Block body, not `= runBlocking { ... }`: an expression body here
        // takes on runBlocking's result type, which is TokenStore (the
        // receiver `apply` returns), not Unit -- and JUnit4 requires
        // @Before methods to be void. That mismatch is exactly what made
        // the first real run of this test fail before it ever reached a
        // test method: "Invalid test class ... clearAnyPriorState() should
        // be void." The block body below returns Unit regardless of what
        // runBlocking's own block evaluates to.
        runBlocking {
            TokenStore(context).apply {
                clearToken()
                setServerUrl("")
            }
        }
    }

    @Test
    fun serverUrlSurvivesAFreshTokenStoreInstance() = runBlocking {
        val firstInstance = TokenStore(context)
        firstInstance.setServerUrl("http://192.168.1.42:5000")

        // A new instance, not the one that wrote the value - this is the part
        // that actually distinguishes "persisted to disk" from "cached in the
        // object that happened to write it," which an in-memory-only bug
        // could pass by accident if the test reused firstInstance.
        val restartedInstance = TokenStore(context)
        assertEquals("http://192.168.1.42:5000", restartedInstance.serverUrl())
    }

    @Test
    fun tokenSurvivesAFreshTokenStoreInstanceThroughARealKeystoreRoundTrip() = runBlocking {
        val firstInstance = TokenStore(context)
        firstInstance.setToken("dev_abc123secrettoken")

        val restartedInstance = TokenStore(context)
        // Not just "non-null" - the actual plaintext, proving the Keystore
        // key that encrypted it on the first instance is the SAME key a
        // fresh instance finds and can decrypt with, exactly as it would be
        // after a real app restart (Keystore keys are per-app, not
        // per-object, so this is the realistic case, not a coincidence of
        // the test reusing state).
        assertEquals("dev_abc123secrettoken", restartedInstance.token())
    }

    @Test
    fun bothFieldsSurviveTogetherAcrossASimulatedRestartLikeARealPairing() = runBlocking {
        val paired = TokenStore(context)
        paired.setServerUrl("http://10.0.0.5:5000")
        paired.setToken("dev_pairing_token_xyz")

        // Two independent fresh instances, standing in for two different
        // moments after the process died - an OS-triggered kill overnight,
        // then an app UPDATE the next day. Neither should ever see a partial
        // pairing (a URL with no token, or vice versa), which is exactly the
        // failure mode a user reported as "re-pair under MORE... stayed
        // broken until they force-quit the app" (see the saveCount doc
        // comment on ServerSettingsState).
        val afterOvernightKill = TokenStore(context)
        assertEquals("http://10.0.0.5:5000", afterOvernightKill.serverUrl())
        assertEquals("dev_pairing_token_xyz", afterOvernightKill.token())

        val afterNextDayUpdate = TokenStore(context)
        assertEquals("http://10.0.0.5:5000", afterNextDayUpdate.serverUrl())
        assertEquals("dev_pairing_token_xyz", afterNextDayUpdate.token())
    }

    @Test
    fun clearingTokenActuallyForgetsIt() = runBlocking {
        val paired = TokenStore(context)
        paired.setToken("dev_to_be_cleared")
        paired.clearToken()

        // Unpairing has to be as real as pairing: a fresh instance after a
        // clear must see NO token, not a stale cached one.
        val afterClear = TokenStore(context)
        assertNull(afterClear.token())
    }
}
