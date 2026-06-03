/*
 * src/gui/static/js/strings.js
 *
 * SVCS dashboard — user-facing string catalog (i18n groundwork, TASK 1.5).
 *
 * This is the single seam through which the dashboard's user-facing copy will
 * flow so the UI can be localized later WITHOUT touching feature logic. It is
 * deliberately NOT translated yet (decision: "extract strings now, translate
 * nothing"). It loads before every feature module, so `STRINGS` is a global
 * available to pipeline.js, files.js, demo.js, hls.js, metrics.js,
 * encryption.js, presets/pipeline, etc.
 *
 * Usage pattern (migrate literals incrementally, verifying each panel):
 *     // before:  pushNotif('Pipeline started', ...)
 *     // after:   pushNotif(STRINGS.pipeline.started, ...)
 * For interpolated copy, keep a function:
 *     STRINGS.status.segments(3)  ->  "3 segments"
 *
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — i18n catalog).
 */
"use strict";

const STRINGS = {
  app: {
    title: "SVCS Dashboard",
    tagline: "Selective Video Compression System",
  },

  // Pipeline control (start/stop, status banners)
  pipeline: {
    start: "Start",
    stop: "Stop",
    started: "Pipeline started",
    stopped: "Pipeline stopped",
    alreadyRunning: "Pipeline already running",
    notRunning: "Pipeline is not running",
    starting: "Starting…",
    stopping: "Stopping…",
    idle: "Idle",
    running: "Running",
  },

  // Live status / hero strip
  status: {
    frames: (n) => `${n} frame${n === 1 ? "" : "s"}`,
    segments: (n) => `${n} segment${n === 1 ? "" : "s"}`,
    fps: (n) => `${n} fps`,
    elapsed: "elapsed",
    eta: "ETA",
    complete: "Complete.",
  },

  // File browser / library / segments
  files: {
    scanning: "Scanning…",
    noVideos: "No videos found",
    uploading: "Uploading…",
    uploadFailed: "Upload failed",
    cleared: "Cleared",
    nothingToClear: "Nothing to clear",
    openFolder: "Open folder",
    browse: "Browse…",
  },

  // Demo / four-quadrant comparison
  demo: {
    start: "Run demo",
    starting: "Starting demo…",
    locatingManifest: "Locating manifest…",
    complete: "Demo complete",
    failed: "Demo run failed",
  },

  // HLS live player
  hls: {
    start: "Go live",
    stop: "Stop stream",
    connecting: "Connecting…",
    live: "LIVE",
    alreadyRunning: "HLS stream already running",
    notRunning: "HLS stream is not running",
  },

  // RTSP local server
  rtsp: {
    downloading: "Downloading server…",
    starting: "Starting server…",
    stopping: "Stopping…",
    running: "Server running",
    stopped: "Server stopped",
    urlCopied: "RTSP URL copied",
  },

  // Metrics / hardware
  metrics: {
    cpu: "CPU",
    ram: "RAM",
    battery: "Battery",
    gpu: "GPU",
    network: "Network",
    noGpu: "No GPU detected",
  },

  // Encryption / keygen
  encryption: {
    keyGenerated: "Key generated",
    encrypting: "Encrypting…",
    decrypting: "Decrypting…",
    encrypted: "Encrypted",
    decrypted: "Decrypted",
    unavailable: "Encryption unavailable (cryptography not installed)",
    passwordOrKeyRequired: "Either a password or a key file is required",
  },

  // Presets (surveillance-first; named presets land in M3)
  presets: {
    advanced: "Advanced",
    sensitivity: ["Very Low", "Low", "Balanced", "High", "Very High"],
  },

  // Plate reader (optional)
  plates: {
    analysing: "analysing…",
    none: "No plate candidates above the confidence threshold.",
  },

  // Generic
  common: {
    ok: "OK",
    cancel: "Cancel",
    close: "Close",
    error: "Error",
    loading: "Loading…",
    copied: "Copied",
  },
};

// Expose globally for the classic (non-module) feature scripts.
window.STRINGS = STRINGS;
