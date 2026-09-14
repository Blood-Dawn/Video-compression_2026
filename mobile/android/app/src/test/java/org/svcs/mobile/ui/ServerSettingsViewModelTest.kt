package org.svcs.mobile.ui

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
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
import org.svcs.mobile.net.Capabilities
import org.svcs.mobile.net.FakeSvcsApi
import org.svcs.mobile.net.ProbeResult

/**
 * JVM tests for the pairing screen's ServerSettingsViewModel (ROADMAP 3.1).
 *
 * Runs under Robolectric only because the ViewModel is an AndroidViewModel
 * backed by TokenStore, which needs a real Context (DataStore + Android
 * Keystore). The pairing/probe logic itself never opens a socket: the
 * `apiFactory` constructor hook added for this task substitutes a
 * FakeSvcsApi for the real one.
 *
 * Verification status: see the note at the top of HomeViewModelTest.kt.
 * (This class runs under Robolectric, which needs the same toolchain and
 * hit the same sandbox ceiling -- none of its 8 methods got a confirmed
 * pass/fail here.)
 *
 * Author: Bloodawn (KheivenD), 2026-09-14 (Fall 3.1).
 */
@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
class ServerSettingsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun newViewModel(fake: FakeSvcsApi): ServerSettingsViewModel {
        val app = RuntimeEnvironment.getApplication()
        return ServerSettingsViewModel(
            app,
            apiFactory = { _, _ -> fake },
            ioDispatcher = testDispatcher,
        )
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
    // That path runs on DataStore's own internal dispatcher, not testDispatcher,
    // so unlike every other test in this class it is not fully virtual-time
    // deterministic -- it relies on that write finishing fast enough in practice,
    // same caveat as the "not yet run" note at the top of this file.

    @Test
    fun `save persists then reloads push config through the paired api`() = runTest {
        val fake = FakeSvcsApi()
        val vm = newViewModel(fake)
        testDispatcher.scheduler.runCurrent()

        vm.onServerUrlChanged("192.168.1.42:5000")
        vm.onTokenChanged("secret-token")
        vm.save()
        testDispatcher.scheduler.runCurrent()

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
        testDispatcher.scheduler.runCurrent()

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
