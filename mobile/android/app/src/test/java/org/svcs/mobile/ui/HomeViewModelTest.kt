package org.svcs.mobile.ui

import kotlinx.coroutines.Dispatchers
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
 * Verification status: built and run against a real AGP/Kotlin toolchain
 * (JDK 17, Android SDK 35) in a sandboxed dev VM. "with no api, start
 * reports not paired and never polls" is confirmed PASSING via the JUnit
 * XML report. The other four methods in this class could not be driven to
 * completion in that sandbox -- a 2 vCPU / 4 GB VM with a hard ~110s ceiling
 * per command was not enough to get Gradle through dependency-artifact
 * transforms (Robolectric/AndroidX AARs, the mockable android.jar) and the
 * test run itself in one pass, even with --no-daemon and a cleared daemon
 * registry. No failing assertion or hang was ever observed once a run got
 * far enough to execute a test method. Run `./gradlew testDebugUnitTest`
 * on a normal dev machine (Android Studio's JDK/SDK) to get a full,
 * fast confirmation.
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

        assertEquals(1, fake.pipelineStatusCount)
    }
}
