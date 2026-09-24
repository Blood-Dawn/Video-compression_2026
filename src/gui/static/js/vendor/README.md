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
