# Vendored: uPlot

Source: https://github.com/leeoniya/uPlot
Version: 1.6.31
License: MIT (see https://github.com/leeoniya/uPlot/blob/master/LICENSE.txt)
Files: uPlot.iife.min.js (this folder), uPlot.min.css (../../css/uPlot.min.css)

Vendored instead of loaded from a CDN so the METRICS tab's live CPU/RAM
history chart still works in the offline Field build (docs/build/BUILDS.md
- Field never reaches the network). See docs/research/RESEARCH-DESKTOP-
DEEPDIVE-2026-09.md Part B for why this library was chosen.

To upgrade: download the new uPlot.iife.min.js and uPlot.min.css from a
tagged release and replace both files; nothing else in this repo references
uPlot's internals beyond the public new uPlot(opts, data, target) API used
in metrics.js.

# Vendored: hls.js

Source: https://github.com/video-dev/hls.js (npm package hls.js)
Version: 1.7.4
License: Apache-2.0 (hls.LICENSE.txt in this folder)
File: hls.min.js, taken unmodified from package/dist/hls.min.js of the npm
tarball, except that the trailing sourceMappingURL comment was removed because
the map is not shipped. The tarball matched the registry integrity value
sha512-3GlxGdPvT2YHvQYOt+yOzT/DEior/qJVNIylHA77kgeoBTdQQqi70GwefNEUmHQeNGyjC8U62+bruqW/Tpm+tg==

Replaced a CDN script tag that used hls.js@latest with no pin or integrity
check. Used by static/js/hls.js (the global Hls constructor).

To upgrade: download the new tarball, verify it against the registry
integrity value, and replace hls.min.js and the version above.
