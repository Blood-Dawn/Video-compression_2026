# RESEARCH: VMAF-targeted rate control (R5 TASK 5.1)

Date: 2026-07-16. Research spike written BEFORE coding, the way
docs/RESEARCH-PLATES.md preceded the plate reader. Sources are the ones scouted
during that research spike; the measurements below were taken locally on this
machine against real sample footage.

## The problem with a fixed CRF

SVCS currently encodes at a fixed CRF per mode/preset (mode0/1 CRF 18, mode3
CRF 38, ...). A fixed CRF spends a fixed amount of *effort*, not a fixed amount
of *perceived quality*: an easy static scene and a busy one at the same CRF land
at very different VMAF, so every clip is either over-spent (wasted bytes) or
under-spent (avoidable quality loss). Targeting a perceptual score instead makes
the file as small as it can be while still clearing a quality bar.

## Measured locally (this is why the feature is worth building)

Re-encoding a 3s cut of `data/samples/parking_input.mp4` (libx264, veryfast),
VMAF measured with the existing `utils.metrics.compute_vmaf` harness:

| CRF | VMAF | size |
|----|------|------|
| 18 | 95.60 | 62 KB |
| 24 | 91.04 | 22 KB |
| 30 | 81.53 | 10 KB |
| 36 | 65.27 | 6 KB |
| 42 | 37.79 | 4 KB |
| 48 | 15.71 | 3 KB |

Two things this establishes:

1. **CRF -> VMAF is monotonically decreasing** on real surveillance content
   (verified, no inversions). That is the assumption the search depends on, so
   it is asserted in the unit tests rather than taken on faith.
2. **The headroom is large.** Holding VMAF ~91 instead of ~95.6 costs 4.5 VMAF
   points nobody asked for and saves 2.8x the bytes. The useful target band
   (85 to 97) sits in a steep part of the curve, which is exactly where picking
   the right CRF pays.

## Method: interpolated CRF search over short samples (ab-av1's approach)

`ab-av1` searches CRF with svt-av1 + vmaf to satisfy a `--min-vmaf`, encoding
short samples rather than the whole clip. We do the same:

1. **Sample.** Take N short segments spread across the clip (default 4 x 3s,
   at evenly spaced interior points) rather than encoding the whole thing.
   Extract each with `-c:v copy` so the reference is the source's exact bits;
   fall back to a near-transparent CRF-10 re-encode if stream-copy fails on an
   odd container. The sample IS the reference for VMAF, so the score measures
   only the loss our encode adds.
2. **Probe.** Encode the samples at a candidate CRF with the same codec/preset
   the real encode will use, and measure VMAF against the samples.
3. **Interpolate.** Keep every (crf, vmaf) measurement. Once the target is
   bracketed, linearly interpolate between the two nearest points to pick the
   next candidate; bisect when there is no bracket yet. This converges in about
   3 to 5 probes instead of the ~6 a pure integer bisection needs.
4. **Choose.** Return the LARGEST CRF (smallest file) whose measured VMAF still
   clears the target. Target is a quality FLOOR, so the result lands just above
   it, which is what "smallest file at constant perceived quality" means.

### Parameters

- **Target VMAF:** default 93, clamped to [85, 97]. Below 85 the artifacts get
  visible on the steep part of the curve; above 97 the bitrate cost explodes for
  no perceived gain. This matches the useful range noted for ab-av1.
- **CRF range:** clamped to the codec's own scale (x264/x265 0-51, AV1 0-63) and
  additionally to a sane search window so a pathological probe cannot pick CRF 0.
- **Probe cap:** hard cap on probes so a weird clip cannot search forever.

### Sampling scheme: tuned against measurement, not guessed

Sample VMAF reads slightly LOW versus the full clip (the samples are ~1% of the
frames). That bias matters: it makes the search reject a CRF the full clip would
actually pass, costing file size. Measured on `parking_input.mp4` at CRF 22,
where the FULL-clip VMAF is 93.31:

| scheme | sample VMAF | bias | verdict on CRF 22 (target 93) |
|---|---|---|---|
| 3 x 2s | 92.91 | -0.40 | rejects it (search settles on CRF 21) |
| 4 x 3s | 93.03 | -0.28 | accepts it |
| 5 x 4s | 93.04 | -0.27 | accepts it, for 67% more sampling and no gain |

So the default is **4 x 3s**. It halves the bias and recovers a CRF step worth
about 20% of the file (CRF 21 = 938 KB vs CRF 22 = 750 KB on this clip), and
sampling harder buys nothing measurable. Note the residual bias is in the
CONSERVATIVE direction: samples under-read, so the search errs toward spending
more bits, never toward shipping under the quality floor.

### Caching

The search costs encode time, so the chosen CRF is cached keyed by
`source signature (path|size|mtime) + codec + preset + target`, mirroring
`utils.compressed_index.signature`. A re-run of the same clip at the same
settings is instant. Replacing the file at the same path changes the signature
and invalidates the entry, which is the same rule the compressed index uses.

### Fallback (never hang, never fail the encode)

If libvmaf is missing, ffmpeg is missing, sample extraction fails, or the search
cannot converge, the module returns the preset's fixed CRF with a
`fallback_reason` and the pipeline logs it. Target mode NEVER blocks or breaks an
encode; it degrades to exactly today's behaviour. This is the same
degrade-gracefully rule the ONNX plate reader follows.

## Scope decisions

- **Opt-in per preset.** Existing fixed-CRF modes are untouched; a preset opts
  into target mode with a target value. This keeps the default behaviour
  identical and the change reviewable.
- **Runs in the worker.** The search is encode work, so it runs in the existing
  pipeline worker thread, never on the UI/request thread.
- **Codec policy unchanged.** The search picks a CRF for whichever codec the
  mode already selects (H.264 for mode0/1, AV1 for mode2/3). No H.265, per the
  standing decision.
- **LiteVPNet (learned encoder control, arXiv 2510.12379) is NOT adopted.** It
  targets a quality metric with a learned model, which would mean shipping model
  weights and a torch-adjacent dep for a gain the sample search already
  captures. Recorded as considered-and-rejected; the sample search needs no
  model and no extra dependency.

## Honest bounds

- The search measures VMAF on SAMPLES, so the full-clip VMAF can differ from the
  target by more than the sample tolerance if the clip is wildly heterogeneous.
  Sampling across the duration (not just the head) mitigates this; the
  acceptance target of about +/-1 is on a representative clip, not a guarantee
  for every input.
- VMAF is a perceptual model, not ground truth, and it is measured against the
  SOURCE. If the source is already heavily compressed, a high VMAF means "we
  added little further loss", not "this looks great".
- Sample encodes add wall-clock time on the first run of a clip. That is the
  cost of the feature; the cache is what makes it acceptable in practice.
