package org.svcs.mobile.data

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.io.IOException

/**
 * JVM tests that TokenStore.token() fails closed: any read or decrypt failure
 * returns null (treated as "not paired") instead of throwing.
 *
 * The real Keystore cipher is covered on a device by TokenStorePersistenceTest.
 * Here the DataStore read is replaced through the `readBlob` seam so a read
 * error can be forced without a corrupt file.
 */
@RunWith(RobolectricTestRunner::class)
class TokenStoreFailClosedTest {

    private object InMemoryCipher : TokenCipher {
        override fun encrypt(plain: String) = "test:" + plain
        override fun decrypt(blob: String): String {
            require(blob.startsWith("test:")) { "not written by this cipher" }
            return blob.removePrefix("test:")
        }
    }

    private object ThrowingCipher : TokenCipher {
        override fun encrypt(plain: String) = plain
        override fun decrypt(blob: String): String = throw IllegalStateException("key gone")
    }

    private val context get() = RuntimeEnvironment.getApplication()

    @Test
    fun aFailingDataStoreReadYieldsNull() = runBlocking {
        val store = TokenStore(context, InMemoryCipher, readBlob = { throw IOException("disk") })
        assertNull(store.token())
    }

    @Test
    fun aFailingDecryptYieldsNull() = runBlocking {
        val store = TokenStore(context, ThrowingCipher, readBlob = { "blob" })
        assertNull(store.token())
    }

    @Test
    fun aMissingBlobYieldsNull() = runBlocking {
        val store = TokenStore(context, InMemoryCipher, readBlob = { null })
        assertNull(store.token())
    }

    @Test
    fun aReadableBlobStillDecrypts() = runBlocking {
        val store = TokenStore(context, InMemoryCipher, readBlob = { "test:dev_abc" })
        assertEquals("dev_abc", store.token())
    }
}
