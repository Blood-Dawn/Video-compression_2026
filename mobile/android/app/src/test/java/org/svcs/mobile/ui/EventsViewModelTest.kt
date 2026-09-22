package org.svcs.mobile.ui

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
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
import org.svcs.mobile.net.EventItem
import org.svcs.mobile.net.EventsRecent
import org.svcs.mobile.net.FakeSvcsApi
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.ZoneLine
import org.svcs.mobile.net.ZonesConfig
import org.svcs.mobile.net.ZonesConfigResponse

/**
 * JVM tests for EventsViewModel (ROADMAP 3.1).
 *
 * The refresh loop starts in `init`, so the fake's canned response has to be
 * in place before construction; `runCurrent()` then lets that first poll
 * execute without advancing into the next 10s cycle.
 *
 * `vm.viewModelScope.cancel()` after the last `runCurrent()` in every test
 * below is load-bearing, not cleanup theater: the init loop's `delay(10_000)`
 * is a real pending task on the shared `testDispatcher` scheduler for as
 * long as it's alive, and `runTest {}` tries to drain that scheduler to
 * idle when the test body returns. Since this loop never finishes on its
 * own, that drain never terminates -- confirmed by an actual hang (a
 * `Test worker` thread stuck inside `advanceUntilIdleOr`, tens of millions
 * of iterations deep, never returning) the first time this file's full
 * suite was ever run end-to-end. Cancelling the scope before the test
 * returns removes the pending task so `runTest` can finish normally.
 *
 * Verification status: confirmed passing (all methods) once the cancel
 * above was added; see the matching note in HomeViewModelTest.kt for the
 * same defect in that class's `start()`-driven polling loop.
 *
 * Author: Bloodawn (KheivenD), 2026-09-14 (Fall 3.1).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class EventsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `init refreshes events once immediately`() = runTest {
        val fake = FakeSvcsApi().apply {
            eventsRecentResult = Fetched.Ok(
                EventsRecent(
                    events = listOf(
                        EventItem(kind = "loitering", cameraId = "cam_00", label = "person",
                            geometryId = "zone1", wallTime = "2026-09-14T10:00:00"),
                    ),
                ),
            )
        }
        val vm = EventsViewModel(fake, ioDispatcher = testDispatcher)
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the init loop before runTest drains the scheduler

        val s = vm.state.value
        assertEquals(1, s.events.size)
        assertEquals("zone1", s.events.first().geometryId)
        assertEquals(1, fake.eventsRecentCount)
    }

    @Test
    fun `unauthorized events surfaces a re-pair message`() = runTest {
        val fake = FakeSvcsApi().apply { eventsRecentResult = Fetched.Unauthorized }
        val vm = EventsViewModel(fake, ioDispatcher = testDispatcher)
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the init loop before runTest drains the scheduler

        assertEquals(
            "The server rejected this device's token. Re-pair under MORE.",
            vm.state.value.error,
        )
    }

    @Test
    fun `with no api, refresh does nothing`() {
        val vm = EventsViewModel(null, ioDispatcher = testDispatcher)
        // init's loop returns immediately (api is null), so this just checks
        // the manual refresh() path is equally inert; state must stay default.
        vm.refresh()
        assertEquals(0, vm.state.value.events.size)
    }

    @Test
    fun `addGeometry ignores a near-zero-size zone rectangle`() {
        val vm = EventsViewModel(null, ioDispatcher = testDispatcher)
        vm.setDrawMode("zone")
        vm.addGeometry(0.1f, 0.1f, 0.105f, 0.6f)  // width ~0.005, below the 0.02 floor
        assertEquals(0, vm.state.value.editorExcludes.size)

        vm.addGeometry(0.1f, 0.1f, 0.4f, 0.6f)
        assertEquals(1, vm.state.value.editorExcludes.size)
    }

    @Test
    fun `addGeometry always accepts a line regardless of size`() {
        val vm = EventsViewModel(null, ioDispatcher = testDispatcher)
        vm.setDrawMode("line")
        vm.addGeometry(0.1f, 0.1f, 0.101f, 0.101f)
        assertEquals(1, vm.state.value.editorLines.size)
    }

    @Test
    fun `loadZones populates the editor from the server`() = runTest {
        val fake = FakeSvcsApi().apply {
            getZonesResult = Fetched.Ok(
                ZonesConfigResponse(
                    cameraId = "cam_00",
                    config = ZonesConfig(lines = listOf(ZoneLine(id = "line1", line = listOf(0.0, 0.0, 1.0, 1.0)))),
                ),
            )
        }
        val vm = EventsViewModel(fake, ioDispatcher = testDispatcher)
        testDispatcher.scheduler.runCurrent()  // drain the init refresh first

        vm.onCameraChanged("cam_00")
        vm.loadZones()
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the init loop before runTest drains the scheduler

        assertEquals(1, vm.state.value.editorLines.size)
        assertTrue(vm.state.value.editorMessage!!.contains("Loaded"))
    }

    @Test
    fun `saveZones sends the current editor geometry`() = runTest {
        val fake = FakeSvcsApi()
        val vm = EventsViewModel(fake, ioDispatcher = testDispatcher)
        testDispatcher.scheduler.runCurrent()

        vm.onCameraChanged("cam_01")
        vm.setDrawMode("line")
        vm.addGeometry(0.0f, 0.0f, 1.0f, 1.0f)
        vm.saveZones()
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the init loop before runTest drains the scheduler

        assertEquals(1, fake.saveZonesCalls.size)
        val (cam, cfg) = fake.saveZonesCalls.first()
        assertEquals("cam_01", cam)
        assertEquals(1, cfg.lines.size)
    }
}
