package org.svcs.mobile.upload

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first

/** Separate from TokenStore's "svcs_settings" so clearing uploads can never
 *  touch the pairing. */
private val Context.uploadStore by preferencesDataStore(name = "svcs_uploads")

/**
 * [CheckpointStore] backed by DataStore, keyed by the local tracking id the
 * upload was enqueued with. Holds only the server's upload_id, the last offset
 * the server acked, and the chunk size: a pointer the next run uses to ask
 * the server where it really is (see [UploadEngine]).
 *
 * Author: Jorge Sanchez, 2026-09-27 (Fall 4.3).
 */
class DataStoreCheckpointStore(
    private val context: Context,
    trackingId: String,
) : CheckpointStore {

    private val idKey = stringPreferencesKey("${trackingId}_server_id")
    private val offsetKey = longPreferencesKey("${trackingId}_offset")
    private val chunkKey = intPreferencesKey("${trackingId}_chunk")

    override suspend fun load(): UploadCheckpoint? {
        val prefs = context.uploadStore.data.first()
        val id = prefs[idKey] ?: return null
        return UploadCheckpoint(
            serverUploadId = id,
            lastKnownOffset = prefs[offsetKey] ?: 0L,
            chunkSize = prefs[chunkKey] ?: UploadEngine.DEFAULT_CHUNK,
        )
    }

    override suspend fun save(checkpoint: UploadCheckpoint) {
        context.uploadStore.edit { prefs ->
            val id = checkpoint.serverUploadId
            if (id != null) prefs[idKey] = id else prefs.remove(idKey)
            prefs[offsetKey] = checkpoint.lastKnownOffset
            prefs[chunkKey] = checkpoint.chunkSize
        }
    }

    override suspend fun clear() {
        context.uploadStore.edit { prefs ->
            prefs.remove(idKey)
            prefs.remove(offsetKey)
            prefs.remove(chunkKey)
        }
    }

    companion object {
        /** Drop every checkpoint. Only safe when no upload is queued or running. */
        suspend fun clearAll(context: Context) {
            context.uploadStore.edit { it.clear() }
        }
    }
}
