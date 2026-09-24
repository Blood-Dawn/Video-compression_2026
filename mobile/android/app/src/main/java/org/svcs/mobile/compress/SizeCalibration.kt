package org.svcs.mobile.compress

/**
 * Per-phone correction for size-limit jobs that land far under their limit.
 *
 * Hardware encoders treat the requested bitrate as a ceiling, and on calm
 * footage they stay well below it: the Sep 22 field test put 8 MB into a
 * 10 MB limit. That is safe but wastes a fifth of the quality the user was
 * entitled to. This learns how far THIS phone's encoder undershoots, from its
 * own finished jobs, and asks for proportionally more next time.
 *
 * It must never push a job over its limit, so it is conservative in three
 * ways: it waits for [MIN_SAMPLES] jobs, it sizes the boost from the job that
 * undershot the LEAST (so even that clip would land at [TARGET_FILL] of the
 * original, already-margined bitrate), and it is capped at [MAX_BOOST]. The
 * worker also re-encodes at the uncalibrated bitrate if a boosted job still
 * comes out over the limit.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (roadmap: size-target undershoot).
 */
object SizeCalibration {
    const val MIN_SAMPLES = 3
    const val MAX_BOOST = 1.25
    /** How much of the requested bitrate the least-undershooting past job
     *  would use after the boost. Below 1 on purpose. */
    const val TARGET_FILL = 0.97
    /** Only the most recent jobs count, so a changed encoder (OS update)
     *  or habits (different footage) take over quickly. */
    const val HISTORY = 10

    /**
     * Boost factor (>= 1.0) from actual/requested video bitrate ratios of past
     * jobs, newest first. 1.0 means "ask for exactly what the math says".
     */
    fun factor(ratios: List<Double>): Double {
        val recent = ratios.filter { it > 0.0 && it.isFinite() }.take(HISTORY)
        if (recent.size < MIN_SAMPLES) return 1.0
        val worst = recent.max()
        if (worst >= TARGET_FILL) return 1.0
        return (TARGET_FILL / worst).coerceIn(1.0, MAX_BOOST)
    }

    /**
     * The ratios that describe [codecMime]'s encoder, newest first: finished
     * size-limit jobs that did not take the decode-failure fallback and that
     * recorded both bitrates.
     */
    fun ratios(history: List<CompressionRecord>, codecMime: String): List<Double> =
        history
            .filter {
                it.modeType == "TARGET_SIZE" && it.codecMime == codecMime && !it.usedFallback &&
                    it.requestedVideoBps > 0 && it.actualVideoBps > 0
            }
            .sortedByDescending { it.timestampMs }
            .map { it.actualVideoBps.toDouble() / it.requestedVideoBps }

    /**
     * The actual average video bitrate of a finished job: what Media3
     * reports when it can, otherwise estimated from the file size minus the
     * audio budget.
     */
    fun actualVideoBps(reportedBps: Int, outputBytes: Long, durationMs: Long, audioBps: Int): Int = when {
        reportedBps > 0 -> reportedBps
        outputBytes > 0 && durationMs > 0 ->
            ((outputBytes * 8.0 / (durationMs / 1000.0)) - audioBps).toInt().coerceAtLeast(0)
        else -> 0
    }
}
