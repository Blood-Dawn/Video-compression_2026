package org.svcs.mobile.ui

import android.app.Application
import android.content.ContentResolver
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.ExistingWorkPolicy
import androidx.work.WorkInfo
import androidx.work.WorkManager
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.svcs.mobile.compress.CompressionMode
import org.svcs.mobile.compress.CompressionWorker
import org.svcs.mobile.compress.QualityPreset
import org.svcs.mobile.compress.QualityPresets
import org.svcs.mobile.compress.SizePreset
import org.svcs.mobile.compress.SizePresets
import org.svcs.mobile.compress.VideoCodecChoice
import org.svcs.mobile.compress.AUDIO_RESERVE_BPS
import org.svcs.mobile.compress.bitrateForTargetSize

enum class JobPhase { IDLE, RUNNING, DONE, FAILED }

data class CompressState(
    val pickedUri: Uri? = null,
    val pickedName: String? = null,
    val pickedSizeBytes: Long = -1,
    val durationMs: Long = 0,
    val mode: CompressionMode = CompressionMode.Quality(QualityPresets.MEDIUM),
    val customSizeText: String = "",
    val codec: VideoCodecChoice = VideoCodecChoice.H265,
    // Fall roadmap Phase 2, opt-in: off by default since it costs a real
    // (bounded) detection pass before the encode even starts.
    val smartCompress: Boolean = false,
    val smartCompressActivityDetected: Boolean? = null,
    /** False when the picked source has no audio track at all. */
    val sourceHasAudio: Boolean = true,
    val removeAudio: Boolean = false,
    /** True while Smart Compress is sampling frames, before encoding. */
    val analyzing: Boolean = false,
    val phase: JobPhase = JobPhase.IDLE,
    val progressPercent: Int = 0,
    val outputUri: Uri? = null,
    val outputBytes: Long = -1,
    val usedFallback: Boolean = false,
    val error: String? = null,
)

/**
 * Standalone (server-free) compressor - Fall roadmap Phase 1.
 *
 * Deliberately an [AndroidViewModel]: unlike every other screen's ViewModel
 * in this app, this one needs a ContentResolver and WorkManager, which need
 * a real Context - there's no server API client to inject instead.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1).
 */
class CompressViewModel(application: Application) : AndroidViewModel(application) {

    private val _state = MutableStateFlow(CompressState())
    val state: StateFlow<CompressState> = _state.asStateFlow()

    private var activeWorkId: UUID? = null

    fun onVideoPicked(uri: Uri) {
        val resolver = getApplication<Application>().contentResolver
        try {
            resolver.takePersistableUriPermission(
                uri, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION,
            )
        } catch (_: SecurityException) {
            // Some providers (e.g. a share-sheet one-shot Uri) don't support a
            // persistable grant. The read still works for this session; it
            // just wouldn't survive a process restart mid-pick, which is fine.
        }
        viewModelScope.launch {
            val (name, size, probe) = withContext(Dispatchers.IO) {
                Triple(displayNameOf(resolver, uri), sizeOf(resolver, uri), probe(uri))
            }
            _state.update {
                it.copy(
                    pickedUri = uri,
                    pickedName = name,
                    pickedSizeBytes = size,
                    durationMs = probe.durationMs,
                    sourceHasAudio = probe.hasAudio,
                    phase = JobPhase.IDLE,
                    outputUri = null,
                    error = null,
                )
            }
        }
    }

    fun setQualityPreset(preset: QualityPreset) {
        _state.update { it.copy(mode = CompressionMode.Quality(preset)) }
    }

    fun setSizePreset(preset: SizePreset) {
        _state.update { it.copy(mode = CompressionMode.TargetSize(preset), customSizeText = "") }
    }

    /**
     * Any target size the presets don't cover - a platform we didn't list,
     * or a limit someone was just told directly ("keep it under 8MB").
     * Keeps the raw text around too so the field doesn't clear itself
     * while the user is still typing a decimal.
     */
    fun setCustomSizeText(text: String) {
        val mb = text.toDoubleOrNull()
        _state.update {
            it.copy(
                customSizeText = text,
                mode = if (mb != null && mb > 0) {
                    CompressionMode.TargetSize(SizePresets.custom(mb))
                } else {
                    it.mode
                },
            )
        }
    }

    fun setCodec(codec: VideoCodecChoice) {
        _state.update { it.copy(codec = codec) }
    }

    fun setSmartCompress(enabled: Boolean) {
        _state.update { it.copy(smartCompress = enabled) }
    }

    fun setRemoveAudio(enabled: Boolean) {
        _state.update { it.copy(removeAudio = enabled) }
    }

    fun startCompress() {
        val s = _state.value
        val uri = s.pickedUri ?: return
        val (bitrateBps, shortSidePx) = when (val mode = s.mode) {
            is CompressionMode.Quality -> mode.preset.targetBitrateBps to mode.preset.maxShortSidePx
            // No audio in the output means no audio budget: those bits go
            // to the picture instead of an AAC track that won't exist.
            is CompressionMode.TargetSize -> bitrateForTargetSize(
                mode.preset,
                s.durationMs,
                audioBps = if (s.sourceHasAudio && !s.removeAudio) AUDIO_RESERVE_BPS else 0,
            ) to mode.preset.maxShortSidePx
        }
        val outputName = "SVCS_${s.pickedName?.substringBeforeLast('.') ?: "compressed"}_" +
            "${System.currentTimeMillis()}.mp4"

        val (modeType, presetLabel) = when (val mode = s.mode) {
            is CompressionMode.Quality -> "QUALITY" to mode.preset.label
            is CompressionMode.TargetSize -> "TARGET_SIZE" to mode.preset.label
        }
        val request = CompressionWorker.buildRequest(
            inputUri = uri,
            outputDisplayName = outputName,
            targetBitrateBps = bitrateBps,
            maxShortSidePx = shortSidePx,
            codec = s.codec,
            originalName = s.pickedName,
            durationMs = s.durationMs,
            modeType = modeType,
            presetLabel = presetLabel,
            smartCompress = s.smartCompress,
            removeAudio = s.removeAudio,
        )
        activeWorkId = request.id
        _state.update {
            it.copy(
                phase = JobPhase.RUNNING,
                progressPercent = 0,
                error = null,
                analyzing = it.smartCompress,
                smartCompressActivityDetected = null,
            )
        }

        val workManager = WorkManager.getInstance(getApplication())
        workManager.enqueueUniqueWork(
            CompressionWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request,
        )
        workManager.getWorkInfoByIdFlow(request.id)
            .onEach { info -> if (info != null) applyWorkInfo(info) }
            .launchIn(viewModelScope)
    }

    fun cancel() {
        activeWorkId?.let { WorkManager.getInstance(getApplication()).cancelWorkById(it) }
    }

    fun reset() {
        _state.update {
            CompressState(pickedUri = null)
        }
    }

    private fun applyWorkInfo(info: WorkInfo) {
        when (info.state) {
            WorkInfo.State.RUNNING -> {
                val pct = info.progress.getInt(CompressionWorker.KEY_PROGRESS_PERCENT, -1)
                val stage = info.progress.getString(CompressionWorker.KEY_STAGE)
                _state.update {
                    it.copy(
                        phase = JobPhase.RUNNING,
                        progressPercent = if (pct >= 0) pct else it.progressPercent,
                        analyzing = when (stage) {
                            CompressionWorker.STAGE_ANALYZING -> true
                            CompressionWorker.STAGE_ENCODING -> false
                            else -> it.analyzing
                        },
                    )
                }
            }
            WorkInfo.State.SUCCEEDED -> {
                val data = info.outputData
                val outUri = data.getString(CompressionWorker.KEY_OUTPUT_URI)?.let(Uri::parse)
                val smartUsed = data.getBoolean(CompressionWorker.KEY_SMART_COMPRESS_USED, false)
                _state.update {
                    it.copy(
                        phase = JobPhase.DONE,
                        progressPercent = 100,
                        analyzing = false,
                        outputUri = outUri,
                        outputBytes = data.getLong(CompressionWorker.KEY_OUTPUT_BYTES, -1),
                        usedFallback = data.getBoolean(CompressionWorker.KEY_USED_FALLBACK, false),
                        smartCompressActivityDetected = if (smartUsed) {
                            data.getBoolean(CompressionWorker.KEY_SMART_COMPRESS_ACTIVITY, true)
                        } else {
                            null
                        },
                    )
                }
            }
            WorkInfo.State.FAILED -> {
                val msg = info.outputData.getString(CompressionWorker.KEY_ERROR)
                    ?: "Compression failed."
                _state.update { it.copy(phase = JobPhase.FAILED, error = msg, analyzing = false) }
            }
            WorkInfo.State.CANCELLED -> {
                _state.update { it.copy(phase = JobPhase.IDLE, progressPercent = 0, analyzing = false) }
            }
            else -> Unit
        }
    }

    private fun displayNameOf(resolver: ContentResolver, uri: Uri): String? {
        return resolver.query(uri, null, null, null, null)?.use { cursor ->
            val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && cursor.moveToFirst()) cursor.getString(idx) else null
        }
    }

    private fun sizeOf(resolver: ContentResolver, uri: Uri): Long {
        return resolver.query(uri, null, null, null, null)?.use { cursor ->
            val idx = cursor.getColumnIndex(OpenableColumns.SIZE)
            if (idx >= 0 && cursor.moveToFirst()) cursor.getLong(idx) else -1L
        } ?: -1L
    }

    private data class SourceProbe(val durationMs: Long, val hasAudio: Boolean)

    private fun probe(uri: Uri): SourceProbe {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(getApplication(), uri)
            SourceProbe(
                durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                    ?.toLongOrNull() ?: 0L,
                // Returns "yes" when an audio track exists, null otherwise.
                hasAudio = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO) != null,
            )
        } catch (_: Exception) {
            // Unreadable counts as "has audio": over-reserving 128 kbps is a
            // small miss, under-reserving can overshoot a size limit.
            SourceProbe(durationMs = 0L, hasAudio = true)
        } finally {
            retriever.release()
        }
    }
}
