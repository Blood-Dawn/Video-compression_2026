# Literature Review: Selective and ROI-Based Video Compression for Surveillance

**EGN 4950C Group 16 — prepared for final report**
**Date:** April 29, 2026

---

## Purpose

This review responds to sponsor feedback from the April 15 meeting. Cody Hayashi asked us to check whether there are existing research papers on intentional lossy compression that selectively discards data without relevant objects, rather than compressing everything uniformly. He noted that a straight storage-ratio comparison against H.264 is not apples-to-apples because our system makes a fundamentally different bet — that non-event frames carry no forensic value.

If prior work exists, we should cite it in the final report to situate our contribution. If no closely matching work exists, the absence is itself worth noting.

The conclusion: a body of relevant work exists, but our approach differs from it in one important way, which is a genuine finding.

---

## What the existing literature does

### 1. Dual-quality encoding (foreground high quality, background low quality)

The most common approach in the literature treats surveillance video as two streams with different importance. The foreground region — wherever motion or detected objects appear — gets encoded at a high bitrate. The background gets a lower bitrate or coarser quantization. The video is still continuous; nothing is dropped.

**Key paper:** Guo et al., "An Efficient Surveillance Video Coding Scheme for Static Camera Based Captured Video Data," IEEE ICCCAS 2019 (DOI: 10.1109/ICCCAS48645.2019.8711754). Uses background subtraction to identify the less important regions and applies differential quantization. The video file is always present for every frame.

**Key paper:** "Fast ROI-based HEVC coding for surveillance videos," IEEE ISCAS 2017 (DOI: 10.1109/ISCAS.2017.7954496). Generates an ROI mask automatically and steers the HEVC encoder to allocate more bits to regions with detected objects. Again — all frames are preserved; the data just has spatially non-uniform quality.

Our Mode 0 does something similar (CRF 18 for ROI regions, CRF 45 for background), but within a single FFmpeg pass rather than a custom HEVC parameter map.

### 2. Foreground/background parallel compression with residual encoding

**Key paper:** Fan et al., "A Foreground-Background Parallel Compression with Residual Encoding for Surveillance Video," arXiv:2001.06590 (2020). Encodes foreground and background independently, then uses an interpolation module to share background across adjacent frames. Reports 69.5% fewer bits than H.265 at equivalent PSNR (36 dB). The entire video is still reconstructable; no temporal data is thrown away.

This is the closest prior work to our Mode 2 conceptually — the background is extracted once and shared across frames. The difference is that their system reconstructs the full original frame, while ours intentionally does not: we black out background regions on the premise that a static camera watching a fixed scene doesn't need those pixels for forensic purposes.

### 3. ROI-based smart camera systems

**Key paper:** "Improving video communication in distributed smart camera systems through ROI-based video analysis and compression," IEEE ICDSC 2012 (DOI: 10.1109/ICDSC.2012.6470145). Reduces camera-to-server bandwidth by transmitting only the region-of-interest crop plus a compressed full-frame thumbnail. The novelty is bandwidth, not storage — the server only sees what the camera decides to send.

Our Mode 3 is architecturally similar: we store only the bounding-box crops and black out everything else. The difference is that we're doing this in post-processing on recorded video rather than at the network edge.

### 4. Selective resolution

**Key paper:** "Selective resolution for surveillance video compression," IEEE ISCAS 1996 (DOI: 10.1109/ISCAS.1996.582136). An early paper arguing that most of the image outside the ROI can be stored at reduced resolution without meaningful information loss. Predates modern deep-learning detection but establishes the core premise our modes rely on.

### 5. Background modeling for source compression

**Key paper:** "Surveillance Source Compression with Background Modeling for Video Big Data," IEEE BigData 2016 (DOI: 10.1109/BigData.2016.7723680). Builds background pictures using residual gradient and edge differences, then uses a background-based coding optimization algorithm at both picture and coding-unit levels. Reports improved compression over standard intra-frame coding for low-motion surveillance footage.

### 6. Impact of compression on background subtraction accuracy

**Key paper:** "Assessing the Impact of Video Compression on Background Subtraction" (ResearchGate, 2020). Tests MOG2 and other background subtractors across different compression levels. Finds that standard surveillance CRF values (30–35, ~1.5–2 Mbps) have measurable but acceptable impact on detection F-score. Below CRF 45, background subtraction accuracy degrades noticeably.

This is directly relevant to our design: our CRF 45 background encoding sits at the edge of the reliable range. The paper validates the choice but also flags it as a threshold we should test empirically.

### 7. Event-based / activity-driven encoding

**Key paper:** "Accelerated Event-Based Feature Detection and Compression for Surveillance Video Systems," arXiv:2312.08213 (2023). Uses an ADDER (Address, Decimation, Detection, and Reconstruction) representation that models video as sparse asynchronous intensity samples rather than frames. Reports 2.5:1 compression at equivalent visual quality. This is a fundamentally different paradigm — no frame-rate concept at all.

Our Mode 1 (skip frames with no motion) is a simpler, frame-rate-preserving version of the same intuition: don't store data when nothing is happening. Our approach is less aggressive but deployable with standard video players and no specialized decoders.

---

## Where our work sits relative to prior literature

The papers above fall into two groups.

**Group A: Compress everything, but unevenly.** The ROI gets high quality, the background gets low quality, but every frame is present and the video is fully reconstructable. Papers 1, 2, 3, 5 are all in this group.

**Group B: Change the representation entirely.** Event cameras, asynchronous sampling. Papers 7 belongs here. These require specialized hardware or decoders.

Our Modes 1, 2, and 3 are a third thing: **intentional temporal and spatial data elimination**. We do not just encode the background poorly — we either skip entire frames (Mode 1), freeze the background into a single reference frame (Mode 2), or black it out entirely (Mode 3). The video is intentionally not a complete record of what the camera saw. Riley's framing in the April 15 meeting was accurate: comparing our output size to raw H.264 is not apples-to-apples because we have made a different decision about what counts as worth storing.

This distinction is worth one paragraph in the final report. The claim is not that our approach is better than theirs, but that it occupies a different point in the design space: one that only makes sense when the operator has already decided that background pixels have no value, which is often true for fixed-position surveillance cameras on a DoD network watching a known field of view.

---

## Gaps and limitations to note in the report

1. **No ground-truth recovery test.** Prior work is evaluated on PSNR, which measures how well the original image can be reconstructed. Our system cannot be evaluated on PSNR for Modes 2–3 by design — we deleted data intentionally. An appropriate evaluation metric would be detection recall (does our compressed output still let a human or algorithm identify the same events as the uncompressed original?). We have not run this test yet.

2. **No comparison against HEVC ROI coding.** The "Fast ROI-based HEVC" paper uses H.265 with a properly tuned ROI map. We use H.264 with two-pass CRF. A fair comparison would encode the same test clip with both methods and compare the resulting file sizes at equivalent detection accuracy. This is a gap in our evaluation.

3. **CRF 45 background quality.** The compression-vs-detection paper finds that CRF 45 sits at the edge of reliable background subtractor performance. Our own pipeline uses MOG2 on the uncompressed live frame (before encoding), so this does not affect our detection. But if someone were to re-run background subtraction on our stored Mode 0 output, the CRF 45 background regions would lose some accuracy.

---

## Search terms used

- "selective video compression surveillance ROI-based static camera" — IEEE Xplore
- "event-driven video encoding background subtraction compression ratio surveillance" — arXiv
- "foreground background differential video compression surveillance background subtraction CRF" — IEEE Xplore
- arXiv:2001.06590, arXiv:2312.08213 — full abstracts fetched

---

## References

1. Guo et al. "An Efficient Surveillance Video Coding Scheme for Static Camera Based Captured Video Data." *IEEE ICCCAS*, 2019. https://ieeexplore.ieee.org/document/8711754/

2. "Fast ROI-based HEVC coding for surveillance videos." *IEEE ISCAS*, 2017. https://ieeexplore.ieee.org/document/7954496/

3. Fan et al. "A Foreground-Background Parallel Compression with Residual Encoding for Surveillance Video." *arXiv:2001.06590*, 2020. https://arxiv.org/abs/2001.06590

4. "Improving video communication in distributed smart camera systems through ROI-based video analysis and compression." *IEEE ICDSC*, 2012. https://ieeexplore.ieee.org/document/6470145

5. "Selective resolution for surveillance video compression." *IEEE ISCAS*, 1996. https://ieeexplore.ieee.org/document/582136/

6. "Surveillance Source Compression with Background Modeling for Video Big Data." *IEEE BigData*, 2016. https://ieeexplore.ieee.org/iel7/7636704/7723653/07723680.pdf

7. "Assessing the Impact of Video Compression on Background Subtraction." ResearchGate, 2020. https://www.researchgate.net/publication/339436981

8. "Accelerated Event-Based Feature Detection and Compression for Surveillance Video Systems." *arXiv:2312.08213*, 2023. https://arxiv.org/abs/2312.08213

9. "A new compression technique for surveillance videos." *IEEE*, 2016. https://ieeexplore.ieee.org/abstract/document/7544020

10. "Semantic Maintained Video Compression by Background Blurring in Surveillance Scenarios." *SpringerLink*, 2025. https://link.springer.com/chapter/10.1007/978-981-95-3398-5_38
