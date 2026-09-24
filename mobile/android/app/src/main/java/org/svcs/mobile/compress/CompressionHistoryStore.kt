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
    // Fall roadmap Phase 2. smartCompressActivityDetected is null when
    // smartCompressUsed is false - there was no analysis pass to report.
    val smartCompressUsed: Boolean = false,
    val smartCompressActivityDetected: Boolean? = null,
    /** Regions encoded at higher quality via FEATURE_Roi; 0 when not used. */
    val roiRegions: Int = 0,
    /** The video encoder Media3 used, e.g. "c2.qti.hevc.encoder". */
    val encoderName: String? = null,
    /** Set when the encoder lowered the resolution or switched codec. */
    val encoderNote: String? = null,
    /** Video bitrate handed to the encoder, and what it actually averaged.
     *  SizeCalibration learns this phone's undershoot from the pair. */
    val requestedVideoBps: Int = 0,
    val actualVideoBps: Int = 0,
    /** The size limit for TARGET_SIZE jobs (0 otherwise), and the boost
     *  SizeCalibration applied to reach it (1.0 = none). */
    val targetBytes: Long = 0L,
    val calibrationFactor: Double = 1.0,
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
        put("smartCompressUsed", r.smartCompressUsed)
        put("smartCompressActivityDetected", r.smartCompressActivityDetected ?: JSONObject.NULL)
        put("roiRegions", r.roiRegions)
        put("encoderName", r.encoderName ?: JSONObject.NULL)
        put("encoderNote", r.encoderNote ?: JSONObject.NULL)
        put("requestedVideoBps", r.requestedVideoBps)
        put("actualVideoBps", r.actualVideoBps)
        put("targetBytes", r.targetBytes)
        put("calibrationFactor", r.calibrationFactor)
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
        smartCompressUsed = o.optBoolean("smartCompressUsed", false),
        smartCompressActivityDetected = if (o.isNull("smartCompressActivityDetected")) {
            null
        } else {
            o.optBoolean("smartCompressActivityDetected")
        },
        roiRegions = o.optInt("roiRegions", 0),
        encoderName = if (o.isNull("encoderName")) null else o.optString("encoderName"),
        encoderNote = if (o.isNull("encoderNote")) null else o.optString("encoderNote"),
        requestedVideoBps = o.optInt("requestedVideoBps", 0),
        actualVideoBps = o.optInt("actualVideoBps", 0),
        targetBytes = o.optLong("targetBytes", 0L),
        calibrationFactor = o.optDouble("calibrationFactor", 1.0),
    )
}
