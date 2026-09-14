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
import org.svcs.mobile.net.FakeSvcsApi
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.LibraryItem
import org.svcs.mobile.net.LibraryPage
import org.svcs.mobile.net.SetupState
import org.svcs.mobile.net.StartCompressResult

/**
 * JVM tests for LibraryViewModel (ROADMAP 3.1).
 *
 * Covers paging/dedup, the OUTPUTS shortcut, and the compress action; the
 * phone-upload path (uploadFromPhone) needs a ContentResolver/Uri and is left
 * to an instrumented test, since faking Android's content resolution adds
 * little for a plain-JVM suite.
 *
 * Verification status: see the note at the top of HomeViewModelTest.kt.
 *
 * Author: Bloodawn (KheivenD), 2026-09-14 (Fall 3.1).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LibraryViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun item(path: String) = LibraryItem(name = path, path = path, size = 1024)

    @Test
    fun `loadFirstPageIfNeeded fetches page 1 and stores the resolved folder`() = runTest {
        val fake = FakeSvcsApi().apply {
            libraryPageResult = Fetched.Ok(
                LibraryPage(
                    folder = "cam_00", total = 2, page = 1,
                    videos = listOf(item("a.mp4"), item("b.mp4")),
                ),
            )
        }
        val vm = LibraryViewModel(fake, ioDispatcher = testDispatcher)

        vm.loadFirstPageIfNeeded()
        testDispatcher.scheduler.runCurrent()

        val s = vm.state.value
        assertEquals(2, s.items.size)
        assertEquals("cam_00", s.folderPath)
        assertTrue(s.exhausted)  // items.size (2) >= total (2)
        assertEquals(1, fake.libraryPageCalls.size)
    }

    @Test
    fun `loadNextPage de-duplicates items that reappear across pages`() = runTest {
        val fake = FakeSvcsApi()
        val vm = LibraryViewModel(fake, ioDispatcher = testDispatcher)

        fake.libraryPageResult = Fetched.Ok(
            LibraryPage(folder = "cam_00", total = 3, page = 1, videos = listOf(item("a.mp4"))),
        )
        vm.loadFirstPageIfNeeded()
        testDispatcher.scheduler.runCurrent()

        // Page 2 re-lists "a.mp4" (the listing shifted under us) plus one new clip.
        fake.libraryPageResult = Fetched.Ok(
            LibraryPage(folder = "cam_00", total = 3, page = 2, videos = listOf(item("a.mp4"), item("c.mp4"))),
        )
        vm.loadNextPage()
        testDispatcher.scheduler.runCurrent()

        val s = vm.state.value
        assertEquals(2, s.items.size)  // "a.mp4" not duplicated
        assertEquals(setOf("a.mp4", "c.mp4"), s.items.map { it.path }.toSet())
    }

    @Test
    fun `unauthorized library page surfaces a re-pair message`() = runTest {
        val fake = FakeSvcsApi().apply { libraryPageResult = Fetched.Unauthorized }
        val vm = LibraryViewModel(fake, ioDispatcher = testDispatcher)

        vm.loadFirstPageIfNeeded()
        testDispatcher.scheduler.runCurrent()

        assertEquals(
            "The server rejected this device's token. Re-pair under MORE.",
            vm.state.value.error,
        )
    }

    @Test
    fun `showOutputs jumps to the server's configured save folder`() = runTest {
        val fake = FakeSvcsApi().apply {
            setupStateResult = Fetched.Ok(SetupState(outputDir = "compressed_out"))
            libraryPageResult = Fetched.Ok(LibraryPage(folder = "compressed_out", total = 0))
        }
        val vm = LibraryViewModel(fake, ioDispatcher = testDispatcher)

        vm.showOutputs()
        testDispatcher.scheduler.runCurrent()

        assertEquals("compressed_out", vm.state.value.folderPath)
    }

    @Test
    fun `showOutputs reports when no save folder is configured`() = runTest {
        val fake = FakeSvcsApi().apply {
            setupStateResult = Fetched.Ok(SetupState(outputDir = "", defaultOutputDir = ""))
        }
        val vm = LibraryViewModel(fake, ioDispatcher = testDispatcher)

        vm.showOutputs()
        testDispatcher.scheduler.runCurrent()

        assertEquals(
            "The server has no save folder configured yet.",
            vm.state.value.error,
        )
    }

    @Test
    fun `compress sends the chosen mode and reports the busy outcome`() = runTest {
        val fake = FakeSvcsApi().apply { startCompressResult = StartCompressResult.Busy }
        val vm = LibraryViewModel(fake, ioDispatcher = testDispatcher)

        vm.compress(item("a.mp4"), mode = "mode2")
        testDispatcher.scheduler.runCurrent()

        assertEquals(1, fake.startCompressCalls.size)
        assertEquals("a.mp4" to "mode2", fake.startCompressCalls.first())
        assertTrue(vm.state.value.actionMessage!!.contains("already compressing"))
        assertEquals(false, vm.state.value.compressing)
    }

    @Test
    fun `setKind resets paging and refetches`() = runTest {
        val fake = FakeSvcsApi().apply {
            libraryPageResult = Fetched.Ok(LibraryPage(total = 1, videos = listOf(item("a.mp4"))))
        }
        val vm = LibraryViewModel(fake, ioDispatcher = testDispatcher)
        vm.loadFirstPageIfNeeded()
        testDispatcher.scheduler.runCurrent()

        fake.libraryPageResult = Fetched.Ok(LibraryPage(total = 1, videos = listOf(item("b.mp4"))))
        vm.setKind("compressed")
        testDispatcher.scheduler.runCurrent()

        val s = vm.state.value
        assertEquals("compressed", s.kind)
        assertEquals(listOf("b.mp4"), s.items.map { it.path })
        assertEquals(2, fake.libraryPageCalls.size)
        assertEquals("compressed", fake.libraryPageCalls.last().kind)
    }
}
