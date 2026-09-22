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
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.svcs.mobile.net.FakeSvcsApi
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.MeasuredSavings
import org.svcs.mobile.net.PipelineStatus
import org.svcs.mobile.net.RecordedTotals
import org.svcs.mobile.net.Savings

/**
 * JVM tests for HomeViewModel (ROADMAP 3.1: "Make SvcsApi fakeable").
 *
 * HomeViewModel takes its SvcsApiClient by plain constructor injection and
 * has no Context/Application dependency, so this runs as an ordinary JUnit
 * test with a StandardTestDispatcher standing in for Dispatchers.Main --
 * no Robolectric, no real network.
 *
 * `vm.viewModelScope.cancel()` after the last scheduler-drain call in the
 * four methods below that call `start()` with a real fake api is
 * load-bearing, not cleanup theater: `start()`'s `while (isActive) { ...;
 * delay(POLL_MS) }` loop never finishes on its own, so its next `delay` is
 * always a pending task on the shared `testDispatcher` scheduler. `runTest
 * {}` tries to drain that scheduler to idle when the test body returns,
 * which never terminates while that task is still pending -- confirmed by
 * an actual hang (a `Test worker` thread stuck inside `advanceUntilIdleOr`,
 * tens of millions of iterations deep) the first time this file's full
 * suite was ever run end-to-end on a real machine. "with no api, start
 * reports not paired and never polls" never hit this: `start()` returns
 * before launching anything when `api` is null, so there's no loop to
 * clean up there. Cancelling the scope before each of the other four tests
 * returns removes the pending task so `runTest` can finish normally.
 *
 * Verification status: confirmed passing (all five methods) on a real
 * AGP/Kotlin toolchain (JDK 21, Android SDK 35) once the cancel calls above
 * were added. See the matching note in EventsViewModelTest.kt for the same
 * defect pattern in that class's `init`-driven polling loop.
 *
 * Author: Bloodawn (KheivenD), 2026-09-14 (Fall 3.1).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class HomeViewModelTest {

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
    fun `with no api, start reports not paired and never polls`() = runTest {
        val fake = FakeSvcsApi()
        val vm = HomeViewModel(null, ioDispatcher = testDispatcher)

        vm.start()
        testDispatcher.scheduler.advanceUntilIdle()

        val s = vm.state.value
        assertEquals("Not paired with a server yet.", s.error)
        assertEquals(false, s.running)
        assertEquals(0, fake.pipelineStatusCount)
    }

    @Test
    fun `start polls status and savings and updates state`() = runTest {
        val fake = FakeSvcsApi().apply {
            pipelineStatusResult = Fetched.Ok(
                PipelineStatus(
                    running = true, frameCount = 120, segmentCount = 4, progressPct = 42.0,
                ),
            )
            savingsResult = Fetched.Ok(
                Savings(
                    measured = MeasuredSavings(
                        files = 3, sourceBytes = 900, outputBytes = 300,
                        savedBytes = 600, ratio = 3.0,
                    ),
                    recorded = RecordedTotals(segments = 4, outputBytes = 300),
                ),
            )
        }
        val vm = HomeViewModel(fake, ioDispatcher = testDispatcher)

        vm.start()
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the poll loop before runTest drains the scheduler

        val s = vm.state.value
        assertEquals(true, s.running)
        assertEquals(120L, s.frameCount)
        assertEquals(4L, s.segmentCount)
        assertEquals(42.0, s.progressPct)
        assertEquals(3, s.measuredFiles)
        assertEquals(600L, s.savedBytes)
        assertEquals(3.0, s.ratio)
        assertEquals(4, s.recordedSegments)
        assertNull(s.error)
        assertEquals(1, fake.pipelineStatusCount)
        assertEquals(1, fake.savingsCount)
    }

    @Test
    fun `unauthorized status surfaces a re-pair message`() = runTest {
        val fake = FakeSvcsApi().apply { pipelineStatusResult = Fetched.Unauthorized }
        val vm = HomeViewModel(fake, ioDispatcher = testDispatcher)

        vm.start()
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the poll loop before runTest drains the scheduler

        assertEquals(
            "The server rejected this device's token. Re-pair under MORE.",
            vm.state.value.error,
        )
    }

    @Test
    fun `a failed status reports the detail`() = runTest {
        val fake = FakeSvcsApi().apply {
            pipelineStatusResult = Fetched.Failed("connection refused")
        }
        val vm = HomeViewModel(fake, ioDispatcher = testDispatcher)

        vm.start()
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the poll loop before runTest drains the scheduler

        assertEquals(
            "Could not reach the server. connection refused",
            vm.state.value.error,
        )
    }

    @Test
    fun `start is idempotent, a second call does not poll again`() = runTest {
        val fake = FakeSvcsApi()
        val vm = HomeViewModel(fake, ioDispatcher = testDispatcher)

        vm.start()
        testDispatcher.scheduler.runCurrent()
        vm.start()
        testDispatcher.scheduler.runCurrent()
        vm.viewModelScope.cancel()  // stop the poll loop before runTest drains the scheduler

        assertEquals(1, fake.pipelineStatusCount)
    }
}
