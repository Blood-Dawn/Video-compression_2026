# Detection Tuning Results

## Baseline (Default MOG2)
- history: 500
- varThreshold: 16
- detectShadows: True

## Observations (Baseline)
- Very sensitive to small pixel changes
- Produced false positives on static scenes
- Detected motion quickly, but with noise

---

## Tuned Parameters (Final)
- history: 500
- varThreshold: 50
- detectShadows: False

## Results (After Tuning)
- Static scene: 0 detections (0% false positives)
- Moving scene: consistent detection across frames
- Detection occurs within ~1–3 frames after motion begins

---

## Final Recommendation
Use tuned MOG2 parameters:
- varThreshold = 50
- detectShadows = False
