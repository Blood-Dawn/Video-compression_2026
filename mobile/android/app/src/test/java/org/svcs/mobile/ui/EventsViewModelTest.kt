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
 * Verification status: see the note at the top of HomeViewModelTest.kt.
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

        assertEquals(1, fake.saveZonesCalls.size)
        val (cam, cfg) = fake.saveZonesCalls.first()
        assertEquals("cam_01", cam)
        assertEquals(1, cfg.lines.size)
    }
}
