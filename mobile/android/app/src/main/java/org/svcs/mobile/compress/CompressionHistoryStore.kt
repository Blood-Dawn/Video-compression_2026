package org.svcs.mobile.compress

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * One completed on-device compression job, for the Phase 1.5 local library.
 *
 * MediaStore already tracks the output file, its size, and its date; it has
 * no idea what the source size was, what preset produced this, which codec,
 * or whether the encoder fallback path fired. This is that missing half.
 */
data class CompressionRecord(
    val outputUri: String,
    val outputDisplayName: String,
    val originalName: String?,
    val originalSizeBytes: Long,
    val outputSizeBytes: Long,
    val durationMs: Long,
    val timestampMs: Long,
    val codecMime: String,
    val modeType: String, // "QUALITY" or "TARGET_SIZE"
    val presetLabel: String,
    val usedFallback: Boolean,
)

/**
 * A flat JSON-array history file rather than a Room database, on purpose.
 * At the scale one phone's compression history actually reaches (dozens to
 * low thousands of jobs), loading the whole list and filtering it with
 * plain Kotlin collection calls is simpler than a schema + migrations +
 * annotation processor for what is just a list of small records, and adds
 * zero new build-time moving parts to Phase 1's already-working build.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1.5).
 */
class CompressionHistoryStore(context: Context) {
    private val file = File(context.filesDir, "compression_history.json")

    @Synchronized
    fun append(record: CompressionRecord) {
        val all = readAll().toMutableList()
        all.add(0, record) // newest first
        writeAll(all)
    }

    @Synchronized
    fun readAll(): List<CompressionRecord> {
        if (!file.exists()) return emptyList()
        return try {
            val arr = JSONArray(file.readText())
            (0 until arr.length()).mapNotNull { i -> arr.optJSONObject(i)?.let(::toRecord) }
        } catch (_: Exception) {
            // A corrupt or half-written file shouldn't crash the library
            // screen - it just starts blank again.
            emptyList()
        }
    }

    @Synchronized
    fun delete(outputUri: String) {
        writeAll(readAll().filterNot { it.outputUri == outputUri })
    }

    private fun writeAll(records: List<CompressionRecord>) {
        val arr = JSONArray()
        records.forEach { arr.put(toJson(it)) }
        file.writeText(arr.toString())
    }

    private fun toJson(r: CompressionRecord): JSONObject = JSONObject().apply {
        put("outputUri", r.outputUri)
        put("outputDisplayName", r.outputDisplayName)
        put("originalName", r.originalName ?: JSONObject.NULL)
        put("originalSizeBytes", r.originalSizeBytes)
        put("outputSizeBytes", r.outputSizeBytes)
        put("durationMs", r.durationMs)
        put("timestampMs", r.timestampMs)
        put("codecMime", r.codecMime)
        put("modeType", r.modeType)
        put("presetLabel", r.presetLabel)
        put("usedFallback", r.usedFallback)
    }

    private fun toRecord(o: JSONObject): CompressionRecord = CompressionRecord(
        outputUri = o.getString("outputUri"),
        outputDisplayName = o.optString("outputDisplayName", "compressed_video.mp4"),
        originalName = if (o.isNull("originalName")) null else o.optString("originalName"),
        originalSizeBytes = o.optLong("originalSizeBytes", -1L),
        outputSizeBytes = o.optLong("outputSizeBytes", -1L),
        durationMs = o.optLong("durationMs", 0L),
        timestampMs = o.optLong("timestampMs", 0L),
        codecMime = o.optString("codecMime", ""),
        modeType = o.optString("modeType", "QUALITY"),
        presetLabel = o.optString("presetLabel", ""),
        usedFallback = o.optBoolean("usedFallback", false),
    )
}
