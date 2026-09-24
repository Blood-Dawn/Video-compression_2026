package org.svcs.mobile.ui

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.svcs.mobile.data.TokenCipher
import org.svcs.mobile.data.TokenStore
import org.svcs.mobile.net.Capabilities
import org.svcs.mobile.net.FakeSvcsApi
import org.svcs.mobile.net.ProbeResult

/**
 * JVM tests for the pairing screen's ServerSettingsViewModel (ROADMAP 3.1).
 *
 * Runs under Robolectric only because the ViewModel is an AndroidViewModel
 * backed by TokenStore, which needs a real Context (DataStore). The pairing/probe logic itself never opens a socket: the
 * `apiFactory` constructor hook added for this task substitutes a
 * FakeSvcsApi for the real one.
 *
 * Until 2026-09-24 one to three of these 8 cases failed per run, varying
 * with timing: TokenStore reached for AndroidKeyStore (Robolectric has none),
 * init's settings load could land after a test typed a URL, and DataStore
 * state leaked between cases. The test now injects an in-memory TokenCipher,
 * waits for init and saves to finish, and resets the store before each case.
 * All 8 pass consistently (checked over 8 consecutive reruns).
 *
 * Author: Bloodawn (KheivenD), 2026-09-14 (Fall 3.1); deflaked 2026-09-24.
 */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
class ServerSettingsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        // DataStore is a real file under Robolectric and outlives a test case,
        // so a pairing saved by one test used to leak into the next.
        runBlocking {
            TokenStore(RuntimeEnvironment.getApplication(), InMemoryCipher).apply {
                clearToken()
                setServerUrl("")
                setAutoCompressUpload(true)
            }
        }
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    /**
     * Stand-in for the Keystore cipher, which Robolectric cannot provide
     * (every token write threw KeyStoreException, and 1 or 2 of these cases
     * failed per run depending on timing). It only has to round-trip; the
     * real AES-GCM path is covered on a device by TokenStorePersistenceTest.
     */
    private object InMemoryCipher : TokenCipher {
        override fun encrypt(plain: String) = "test:" + plain
        override fun decrypt(blob: String): String {
            require(blob.startsWith("test:")) { "not written by this cipher" }
            return blob.removePrefix("test:")
        }
    }

    /** Builds the ViewModel and waits for init's TokenStore read, which runs
     *  on DataStore's own thread. Without the wait that read could land after
     *  a test typed a URL and overwrite it. */
    private fun newViewModel(fake: FakeSvcsApi): ServerSettingsViewModel {
        val app = RuntimeEnvironment.getApplication()
        val vm = ServerSettingsViewModel(
            app,
            apiFactory = { _, _ -> fake },
            ioDispatcher = testDispatcher,
            tokenCipher = InMemoryCipher,
        )
        drainUntil { vm.state.value.settingsLoaded }
        return vm
    }

    /** Runs the test dispatcher until [done] (bounded by real time, since the
     *  DataStore work it waits on happens on another thread). */
    private fun drainUntil(done: () -> Boolean) {
        val deadline = System.nanoTime() + 5_000_000_000L
        while (!done() && System.nanoTime() < deadline) {
            testDispatcher.scheduler.runCurrent()
            Thread.sleep(5)
        }
        testDispatcher.scheduler.runCurrent()
    }

    @Test
    fun `successful probe reports connected and stores capabilities`() = runTest {
        val fake = FakeSvcsApi().apply {
            probeResult = ProbeResult.Ok(Capabilities(app = "SVCS", editionLabel = "Field Edition"))
        }
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()  // let init's TokenStore read settle

        vm.onServerUrlChanged("192.168.1.42:5000")
        vm.onTokenChanged("secret-token")
        vm.testConnection()
        testDispatcher.scheduler.runCurrent()

        val s = vm.state.value
        assertTrue(s.ok)
        assertEquals("Connected to Field Edition.", s.message)
        assertEquals("http://192.168.1.42:5000", s.serverUrl)
        assertEquals(1, fake.probeCount)
    }

    @Test
    fun `bad credential surfaces a re-create-token message`() = runTest {
        val fake = FakeSvcsApi().apply { probeResult = ProbeResult.BadCredential }
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        vm.onServerUrlChanged("192.168.1.42:5000")
        vm.onTokenChanged("wrong-token")
        vm.testConnection()
        testDispatcher.scheduler.runCurrent()

        val s = vm.state.value
        assertEquals(false, s.ok)
        assertTrue(s.message!!.contains("rejected that token"))
    }

    @Test
    fun `an unreachable server reports the detail`() = runTest {
        val fake = FakeSvcsApi().apply {
            probeResult = ProbeResult.Unreachable("connection refused")
        }
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        vm.onServerUrlChanged("192.168.1.42:5000")
        vm.testConnection()
        testDispatcher.scheduler.runCurrent()

        assertTrue(vm.state.value.message!!.contains("connection refused"))
        assertEquals(false, vm.state.value.ok)
    }

    @Test
    fun `a public address needs explicit consent before probing`() = runTest {
        val fake = FakeSvcsApi()
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        vm.onServerUrlChanged("8.8.8.8:5000")
        vm.testConnection()
        testDispatcher.scheduler.runCurrent()

        assertTrue(vm.state.value.needsPublicConsent)
        assertEquals(0, fake.probeCount)

        vm.confirmPublicAddress()
        testDispatcher.scheduler.runCurrent()
        assertEquals(1, fake.probeCount)
    }

    @Test
    fun `a private address never needs consent`() = runTest {
        val fake = FakeSvcsApi()
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        vm.onServerUrlChanged("192.168.1.42:5000")
        vm.testConnection()
        testDispatcher.scheduler.runCurrent()

        assertEquals(false, vm.state.value.needsPublicConsent)
        assertEquals(1, fake.probeCount)
    }

    // save() and savePushConfig() below go through TokenStore's real DataStore
    // write path (Robolectric provides a real, if synthetic, filesystem for it).
    // That write runs on DataStore's own internal dispatcher, not testDispatcher,
    // so a single runCurrent() raced it and these two tests failed now and then.
    // awaitSaved() keeps draining the test dispatcher (bounded, real time) until
    // the continuation after the write has run.

    private fun ServerSettingsViewModel.awaitSaved(count: Int = 1) =
        drainUntil { state.value.saveCount >= count }

    @Test
    fun `save persists then reloads push config through the paired api`() = runTest {
        val fake = FakeSvcsApi()
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        vm.onServerUrlChanged("192.168.1.42:5000")
        vm.onTokenChanged("secret-token")
        vm.save()
        vm.awaitSaved()

        assertEquals(1, vm.state.value.saveCount)
        assertTrue(vm.state.value.ok)
        assertTrue(vm.state.value.pushLoaded)
    }

    @Test
    fun `savePushConfig sends the edited fields through the paired api`() = runTest {
        val fake = FakeSvcsApi()
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        vm.onServerUrlChanged("192.168.1.42:5000")
        vm.onTokenChanged("secret-token")
        vm.save()
        vm.awaitSaved()

        vm.togglePushEnabled()
        vm.onPushTopicChanged("https://ntfy.sh/my-topic")
        vm.savePushConfig()
        testDispatcher.scheduler.runCurrent()

        assertEquals(1, fake.savePushConfigCalls.size)
        val call = fake.savePushConfigCalls.first()
        assertEquals(true, call.enabled)
        assertEquals("https://ntfy.sh/my-topic", call.topicUrl)
        assertTrue(vm.state.value.pushOk)
    }

    @Test
    fun `no saved pairing means push actions are inert`() = runTest {
        val fake = FakeSvcsApi()
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        // Never called save(), so serverUrl/token are still blank.
        vm.loadPushConfig()
        testDispatcher.scheduler.runCurrent()

        assertEquals(false, vm.state.value.pushLoaded)
        assertEquals(0, fake.savePushConfigCalls.size)
    }
}
