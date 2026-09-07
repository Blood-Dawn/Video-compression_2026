# Universal multi-vendor format support (R4 Phase 6)

Date: 2026-07-04. Goal (user request): "as universal as possible so people can
use whatever surveillance video format they have from different companies, and
this software should still work."

## What changed
1. **One central format set** - `src/utils/video_formats.py`:
   - `STANDARD_VIDEO_EXTS` - containers OpenCV usually opens (mp4/avi/mkv/ts/...).
   - `PROPRIETARY_VIDEO_EXTS` - vendor / DVR / NVR containers + raw elementary
     streams (.dav, .264/.h264, .265/.hevc, .g64, .sdv, .av, .bu, .irf, .mxf,
     .dat, ...).
   - `ALL_INGEST_EXTS` = the union; `is_video_ext()` / `is_proprietary()`.
2. **FFmpeg decode fallback in FrameSource** - `src/utils/frame_source.py`:
   OpenCV's `VideoCapture` is tried first (fast, the common path, and it must
   actually yield a frame - a probe read guards builds that report `isOpened()`
   True yet fail on read). If OpenCV cannot decode the container, SVCS pipes the
   file through the **bundled FFmpeg** (`ffprobe` for geometry, then
   `-f rawvideo -pix_fmt bgr24 -` on stdout) and reads raw BGR frames. FFmpeg
   supports far more demuxers than OpenCV's build, so this is what makes vendor
   formats work. `SVCS_FORCE_FFMPEG_DECODE=1` forces the FFmpeg path.
3. **The ingest gates were widened** to the central set so a vendor file is not
   rejected before it reaches the decoder:
   - upload (`gui/state._ALLOWED_EXTENSIONS`),
   - watch-folder (`utils/watchfolder.SUPPORTED_EXTENSIONS`),
   - library listing (`gui/routes/library_bp.VIDEO_EXTS`),
   - the native file-browser picker filter.

## Verified
- Both decode paths read the sample clip with matching dimensions; the full
  compression pipeline runs end to end through the FFmpeg fallback (8 segments).
- The FFmpeg process is terminated cleanly on `release()`.
- All ingest gates accept vendor extensions; the OpenCV path is unchanged.

## Honest bounds ("universal" is not "magic")
- "Universal" means **anything the bundled FFmpeg can demux**. That covers the
  vast majority of real exports (H.264/H.265 in almost any container, raw
  elementary streams, MPEG-TS/PS, MXF, ASF/WMV, ...).
- It does NOT cover **encrypted or fully proprietary** vendor blobs (some
  Hikvision `.g64`, certain encrypted Dahua exports). FFmpeg cannot read those,
  so ingest fails with a clear error telling the operator to first export a
  standard file with the vendor's own player/tool. SVCS does not silently
  produce a broken output.
- Browser playback of a vendor ORIGINAL in the Library detail view is still
  limited to browser-playable containers; the compressed OUTPUT is always mp4
  and plays everywhere. Thumbnails use FFmpeg, so they work for vendor files.

## Not done (out of scope)
- Per-vendor decryption / DRM handling (needs vendor SDKs/licenses).
- Bundling additional external demuxer plugins beyond the shipped FFmpeg.
