package org.svcs.mobile.ui.server.settings

import android.app.Application
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.svcs.mobile.data.TokenStore
import org.svcs.mobile.net.FakeSvcsApi
import org.svcs.mobile.net.ProbeResult

/**
 * Instrumented tests for the pairing and settings flows (planner 6.1).
 *
 * TokenStorePersistenceTest already proves the storage layer on its own: a
 * fresh TokenStore reads back what another instance wrote, through a real
 * Android Keystore. This class goes one level up and drives the REAL
 * [ServerSettingsViewModel], the object the MORE tab actually uses, against
 * that same real storage, with only the network faked. That is the part the
 * JVM test (ServerSettingsViewModelTest) cannot cover, because there the
 * cipher is an in-memory stand-in and DataStore's dispatcher cannot be driven
 * by a virtual clock.
 *
 * "App restart" is modelled the way the OS ends a process: every in-memory
 * object is dropped and a brand new ViewModel is built against the same
 * Context. A ViewModel keeps its state in a MutableStateFlow and nothing
 * else, so anything the new instance reports must have come off disk.
 *
 * The probe, the push calls and every other server call go to [FakeSvcsApi],
 * so these tests need no server, no network and no pairing code. They do need
 * a device or emulator, because of the Keystore.
 *
 * Run with: `gradlew connectedDebugAndroidTest` (API 29+, matching minSdk).
 * Record which device or emulator API level it passed on in the commit or PR.
 *
 * Author: Bloodawn (KheivenD), 2026-10-07 (planner 6.1).
 */
@RunWith(AndroidJUnit4::class)
class PairingFlowInstrumentedTest {

    private val app: Application =
        InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as Application

    private lateinit var api: FakeSvcsApi

    @Before
    fun startFromAnUnpairedPhone() {
        api = FakeSvcsApi()
        // Hermetic: a previous run, or a real pairing on this test device,
        // must not leak into any assertion below. Block body on purpose (see
        // the note in TokenStorePersistenceTest about JUnit4 @Before and
        // non-Unit expression bodies).
        runBlocking {
            TokenStore(app).apply {
                clearToken()
                setServerUrl("")
                setAutoCompressUpload(true)
            }
        }
    }

    /** A ViewModel on the real TokenStore and Keystore, with the network faked. */
    private fun newViewModel(): ServerSettingsViewModel =
        ServerSettingsViewModel(app, apiFactory = { _, _ -> api })

    private fun <T> await(block: suspend () -> T): T =
        runBlocking { withTimeout(15_000) { block() } }

    private fun ServerSettingsViewModel.awaitLoaded(): ServerSettingsState =
        await { state.first { it.settingsLoaded } }

    @Test
    fun aFreshInstallLoadsAsUnpaired() {
        val vm = newViewModel()
        val s = vm.awaitLoaded()
        assertEquals("", s.serverUrl)
        assertEquals("", s.token)
        assertFalse(s.ok)
    }

    @Test
    fun pairingOnceSurvivesAProcessRestart() {
        val first = newViewModel()
        first.awaitLoaded()

        // The user types a bare IP and a token, presses TEST, then SAVE.
        first.onServerUrlChanged("192.168.1.42")
        first.onTokenChanged("dev_instrumented_token_1")
        first.testConnection()
        val tested = await { first.state.first { it.ok } }
        // The bare IP was normalized to a full URL with the default port.
        assertEquals("http://192.168.1.42:5000", tested.serverUrl)
        assertEquals(1, api.probeCount)

        first.save()
        val saved = await { first.state.first { it.saveCount == 1 } }
        assertEquals("Saved.", saved.message)

        // Restart: a new ViewModel, nothing carried over in memory.
        val afterRestart = newViewModel().awaitLoaded()
        assertEquals("http://192.168.1.42:5000", afterRestart.serverUrl)
        assertEquals("dev_instrumented_token_1", afterRestart.token)
    }

    @Test
    fun rePairingReplacesTheOldCredentialsAndBumpsSaveCount() {
        val vm = newViewModel()
        vm.awaitLoaded()

        vm.onServerUrlChanged("http://10.0.0.5:5000")
        vm.onTokenChanged("dev_old_token")
        vm.save()
        await { vm.state.first { it.saveCount == 1 } }

        // The server revoked the token; the user pairs again under MORE.
        vm.onTokenChanged("dev_new_token")
        vm.save()
        val second = await { vm.state.first { it.saveCount == 2 } }
        // saveCount is what the app shell watches to rebuild its API client.
        assertEquals(2, second.saveCount)

        val afterRestart = newViewModel().awaitLoaded()
        assertEquals("http://10.0.0.5:5000", afterRestart.serverUrl)
        assertEquals("dev_new_token", afterRestart.token)
    }

    @Test
    fun aRejectedTokenShowsAnErrorAndSavesNothing() {
        api.probeResult = ProbeResult.BadCredential
        val vm = newViewModel()
        vm.awaitLoaded()

        vm.onServerUrlChanged("192.168.1.42")
        vm.onTokenChanged("dev_wrong_token")
        vm.testConnection()
        val s = await { vm.state.first { !it.busy && it.message != null } }

        assertFalse(s.ok)
        assertTrue(s.message!!.contains("rejected"))
        // The user never pressed SAVE, so a restart must come back unpaired.
        val afterRestart = newViewModel().awaitLoaded()
        assertEquals("", afterRestart.serverUrl)
        assertEquals("", afterRestart.token)
    }

    @Test
    fun anUnreachableServerReportsItAndDoesNotPair() {
        api.probeResult = ProbeResult.Unreachable("timeout")
        val vm = newViewModel()
        vm.awaitLoaded()

        vm.onServerUrlChanged("192.168.1.99")
        vm.onTokenChanged("dev_any")
        vm.testConnection()
        val s = await { vm.state.first { !it.busy && it.message != null } }

        assertFalse(s.ok)
        assertTrue(s.message!!.contains("Could not reach"))
        assertNotNull(s.message)
    }

    @Test
    fun aPublicAddressNeedsConsentBeforeAnyRequestIsSent() {
        val vm = newViewModel()
        vm.awaitLoaded()

        vm.onServerUrlChanged("8.8.8.8")
        vm.onTokenChanged("dev_any")
        vm.testConnection()
        val gated = await { vm.state.first { it.needsPublicConsent } }

        assertTrue(gated.needsPublicConsent)
        // The gate must stop the request, not just warn about it.
        assertEquals(0, api.probeCount)

        vm.confirmPublicAddress()
        await { vm.state.first { it.ok } }
        assertEquals(1, api.probeCount)
    }

    @Test
    fun theAutoCompressToggleSurvivesARestart() {
        val vm = newViewModel()
        assertTrue(vm.awaitLoaded().autoCompressUpload)

        vm.toggleAutoCompress()
        await { vm.state.first { !it.autoCompressUpload } }

        val afterRestart = newViewModel().awaitLoaded()
        assertFalse(afterRestart.autoCompressUpload)
    }

    @Test
    fun theSecondPairingDoesNotLeakAStaleServerUrl() {
        val vm = newViewModel()
        vm.awaitLoaded()

        vm.onServerUrlChanged("http://192.168.1.10:5000")
        vm.onTokenChanged("dev_first")
        vm.save()
        await { vm.state.first { it.saveCount == 1 } }

        // Pair against a different server entirely.
        vm.onServerUrlChanged("http://192.168.1.20:5000")
        vm.onTokenChanged("dev_second")
        vm.save()
        await { vm.state.first { it.saveCount == 2 } }

        val afterRestart = newViewModel().awaitLoaded()
        assertEquals("http://192.168.1.20:5000", afterRestart.serverUrl)
        assertEquals("dev_second", afterRestart.token)
    }
}
