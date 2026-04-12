# Detection Tuning Results — Section 2.7

**Author:** Jorge Sanchez (@sanchez-jorge)
**Branch:** feature/detection-tuning
**Date:** 2026-04-12

## Methodology

Tested MOG2 and KNN background subtractors across three synthetic lighting conditions:
- **Daytime**: bright static background (brightness=120), high-contrast object entry
- **Night**: dark noisy background (brightness=25, noise_std=6), dim object entry
- **Mixed lighting**: background gradually shifts from bright to dim (simulates dusk)

Each condition trained the model on 60 background frames, then measured:
- **False Positive rate**: fraction of pixels flagged as foreground on a static scene (acceptance criteria: < 2%)
- **False Negative rate**: fraction of object pixels missed when a person-sized object enters frame

## Results

| Condition     | Method | varThr | hist | CLAHE | FP%    | FN%   | Pass? |
|---------------|--------|--------|------|-------|--------|-------|-------|
| daytime       | MOG2   | 16     | 500  | N     | 0.00%  | 0.07% | Y     |
| daytime       | MOG2   | 30     | 500  | N     | 0.00%  | 0.07% | Y     |
| daytime       | MOG2   | 16     | 200  | N     | 0.00%  | 0.07% | Y     |
| daytime       | MOG2   | 40     | 500  | N     | 0.00%  | 0.07% | Y     |
| daytime       | MOG2   | 16     | 500  | Y     | 0.00%  | 0.07% | Y     |
| daytime       | MOG2   | 30     | 500  | Y     | 0.00%  | 0.07% | Y     |
| daytime       | KNN    | -      | 500  | N     | 0.00%  | 0.07% | Y     |
| daytime       | KNN    | -      | 200  | N     | 0.00%  | 0.07% | Y     |
| daytime       | KNN    | -      | 500  | Y     | 0.00%  | 0.07% | Y     |
| daytime       | KNN    | -      | 500  | Y*    | 0.00%  | 0.07% | Y     |
| night         | MOG2   | 16     | 500  | N     | 0.00%  | 0.07% | Y     |
| night         | MOG2   | 30     | 500  | N     | 0.00%  | 0.07% | Y     |
| night         | MOG2   | 16     | 200  | N     | 0.00%  | 0.07% | Y     |
| night         | MOG2   | 40     | 500  | N     | 0.00%  | 0.07% | Y     |
| night         | MOG2   | 16     | 500  | Y     | 0.01%  | 0.12% | Y     |
| night         | MOG2   | 30     | 500  | Y     | 0.00%  | 0.12% | Y     |
| night         | KNN    | -      | 500  | N     | 0.00%  | 0.07% | Y     |
| night         | KNN    | -      | 200  | N     | 0.00%  | 0.07% | Y     |
| night         | KNN    | -      | 500  | Y     | 2.47%  | 0.07% | N     |
| night         | KNN    | -      | 500  | Y*    | 2.47%  | 0.07% | N     |
| mixed_lighting| MOG2   | 16     | 500  | N     | 0.00%  | 0.07% | Y     |
| mixed_lighting| MOG2   | 30     | 500  | N     | 0.00%  | 0.07% | Y     |
| mixed_lighting| MOG2   | 16     | 200  | N     | 0.00%  | 0.07% | Y     |
| mixed_lighting| MOG2   | 40     | 500  | N     | 0.00%  | 0.07% | Y     |
| mixed_lighting| MOG2   | 16     | 500  | Y     | 0.00%  | 0.07% | Y     |
| mixed_lighting| MOG2   | 30     | 500  | Y     | 0.00%  | 0.07% | Y     |
| mixed_lighting| KNN    | -      | 500  | N     | 50.45% | 0.00% | N     |
| mixed_lighting| KNN    | -      | 200  | N     | 50.57% | 0.00% | N     |
| mixed_lighting| KNN    | -      | 500  | Y     | 50.03% | 0.00% | N     |
| mixed_lighting| KNN    | -      | 500  | Y*    | 50.07% | 0.00% | N     |

*Y* = night_mode=True (CLAHE + raised varThreshold)

## Recommended Parameter Sets

### Daytime
- **MOG2**: `varThreshold=16, history=500, detectShadows=True, min_area=500`
- **KNN**: `history=500, detectShadows=True, min_area=500`

### Night
- **MOG2**: `varThreshold=30, history=500, detectShadows=True, min_area=500` (use night_mode=True)
- **KNN**: `history=500, detectShadows=True, min_area=500` (no CLAHE — increases FP on noisy bg)

### Mixed / Transitional Light