# SVCS feature inventory (R4 Phase 3 baseline)

Date: 2026-07-04. Ground-truth inventory of what SVCS already does, produced by
a codebase sweep, so the Phase 3 competitor gap analysis proposes only genuinely
missing features. HAVE / PARTIAL / NONE with the implementing file.

## Ingest
- File upload HAVE (files_bp.api_upload)
- Webcam/index HAVE (utils/frame_source.py)
- RTSP ingest HAVE (frame_source + rtsp_bp)
- ONVIF discovery HAVE (utils/onvif_discovery.py, cameras_bp)
- Watch-folder HAVE (utils/watchfolder.py, profiles)
- HLS ingest/preview HAVE (hls_bp)

## Compression
- Modes 0-3 HAVE (pipeline/modes.py, presets.py)
- Codecs: H.264 HAVE, AV1 (svt/aom) HAVE, H.265 HAVE (R4 P2), NVENC h264/hevc/av1 HAVE (R4 P2), VP9 NONE
- 10 named surveillance presets HAVE (pipeline/presets.py)
- Dual-CRF fg/bg HAVE; encoder-level addroi ROI HAVE (R4 P2, opt-in)
- Long GOP / capped CRF / denoise HAVE (R4 P2)
- Content auto-detect (scene/time-of-day/color/sharpness) HAVE

## Detection / analytics
- YOLOv8n ONNX object detection HAVE (detection/onnx_backend.py)
- Class grouping person/vehicle/animal HAVE (object_filter.py)
- License-plate reader (easyocr) HAVE but SEPARATE ENV (opencv conflict; Phase 5)
- Motion (MOG2/KNN/GMG) HAVE
- Search-by-object metadata HAVE (queries_bp, files_bp)
- Plate-read SEARCH index PARTIAL (read + stored, no dedicated search UI)

## Library / review
- Gallery + filters + search + lazy thumbnails HAVE (library_bp, files_bp)
- In-dashboard playback (range requests) HAVE
- Timeline scrubber UI NONE
- Compressed-vs-original A/B viewer NONE (demo has 4-quadrant compare, not library)

## Storage / retention
- AES-256-GCM encryption HAVE (encryption_bp, utils/encryption.py)
- Retention policy / age purge NONE
- Disk quota / budget enforcement NONE
- Auto-delete old segments NONE
- Cloud path detect (OneDrive/GDrive/iCloud) HAVE; two-way sync NONE

## Multi-camera
- Per-camera config PARTIAL (camera_id is a label; settings are global)
- Camera management UI NONE
- Multi-stream orchestration PARTIAL (one input per run; multi via watch profiles)
- Camera groups NONE

## Automation
- Auto-compress daemon HAVE (autocompress_runner)
- Scheduling (cron/timer) NONE (polling only)
- Watch profiles HAVE
- Job history + completion summary HAVE (R4 P1)

## Access / deploy
- Basic-Auth dashboard for non-localhost HAVE (gui/auth.py)
- LAN bind HAVE
- HTTPS/TLS built-in NONE (reverse proxy needed)
- Multi-user / RBAC NONE
- Docker HAVE; Windows installer HAVE; winget manifests HAVE (publish gated)

## Export / integration
- Config import/export HAVE (presets_bp)
- REST API (70+ endpoints) HAVE
- SSE live log HAVE (sse_bp)
- RTSP server output HAVE (MediaMTX)
- Webhooks NONE; email/push NONE; MQTT NONE

## Metrics
- System metrics CPU/RAM/GPU/network HAVE (metrics_bp, cpu_sampler)
- Storage stats HAVE
- VMAF (R4 P2) / PSNR / SSIM HAVE (utils/metrics.py)
- Compression ratio + daily summary HAVE (queries_bp)

## Honest gap shortlist (candidates for Phase 3)
1. Retention / disk-budget / auto-purge (NONE) - table stakes for 24/7 NVRs
2. Scheduling beyond polling (NONE)
3. Timeline review UI (NONE)
4. Notifications / webhooks / MQTT (NONE)
5. Multi-user / RBAC + HTTPS (NONE)
6. Plate-read search index (PARTIAL)
7. Compressed-vs-original A/B viewer in library (NONE)
8. Per-camera config + camera groups (PARTIAL)
