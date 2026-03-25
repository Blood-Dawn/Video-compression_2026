# Design Note: Object Memory and Reference-Based Recognition
**Status:** Proposed
**Date:** 2026-03-24
**Proposed by:** Bloodawn (KheivenD)
**Assigned to:** Victor De Souza Teixeira (lead), Riley Roberts (performance/indexing)

---

## Problem

The current pipeline detects foreground objects and compresses around them, but it treats every detection as a new unknown event. This has two downstream problems:

1. **Redundant storage** - A base entry camera sees the same 50 authorized vehicles every day. Every pass creates a new high-quality clip of an already-known plate. These clips waste storage that could hold genuinely novel events.

2. **Hallucination risk in enhancement** - When AI upscaling is applied to a license plate it has never seen before, it is reconstructing detail from learned statistics, not from ground truth. The result can look plausible but be wrong. This is a known forensic liability.

---

## Proposed Solution: Object Memory Registry

Build an object registry module that answers one question before storing a clip: **"Have I seen this object before, and does the context match?"**

The logic is a three-branch decision tree:

```
New detection arrives
    |
    +-- Seen before? --> No  --> Store HIGH-QUALITY snapshot + clip, add to registry
    |
    +-- Seen before? --> Yes, same context (same camera, same entry point)
    |                       --> Log the sighting only (timestamp, camera, confidence)
    |                       --> Do NOT store a new clip -- saves the storage
    |
    +-- Seen before? --> Yes, DIFFERENT context (different gate, unexpected location)
                            --> ALERT -- flag as anomaly, store full clip with priority tag
```

"Seen before" means: a feature vector (perceptual hash of the ROI crop) matches an existing entry in the registry above a similarity threshold.

---

## Storage Model

When an object is first seen:
- A single high-quality screenshot of the ROI crop is saved to `outputs/known_objects/<object_id>.jpg`
- A short clip of the first sighting is saved to `outputs/known_objects/<object_id>_first_sighting.mp4`
- A row is inserted into a new `object_registry` SQLite table

On subsequent sightings of a known object:
- Only a row is inserted into `object_sightings` (timestamp, camera, confidence) -- no new video file
- Net result: a 30-second clip at 30fps becomes a single JPEG + a row in a table

### Estimated Storage Reduction

A vehicle that passes a gate 3 times per day for 30 days:
- Current pipeline: 90 compressed clips
- With object memory: 1 reference JPEG + 1 first-sighting clip + 90 sighting rows
- Reduction: roughly 89 clip files eliminated per vehicle per month

---

## Schema (proposed addition to metadata.db)

```sql
-- One row per unique known object (vehicle, person badge, etc.)
CREATE TABLE IF NOT EXISTS object_registry (
    object_id       TEXT PRIMARY KEY,   -- UUID or perceptual hash
    label           TEXT,               -- "vehicle", "person", "unknown"
    first_seen      TEXT,               -- ISO timestamp
    first_camera    TEXT,               -- camera_id where first detected
    reference_path  TEXT,               -- path to the reference screenshot
    clip_path       TEXT,               -- path to first-sighting clip
    notes           TEXT                -- manual annotations
);

-- One row every time a known object is spotted again
CREATE TABLE IF NOT EXISTS object_sightings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id       TEXT REFERENCES object_registry(object_id),
    timestamp       TEXT NOT NULL,
    camera_id       TEXT,
    confidence      REAL,               -- similarity score vs. reference
    flagged         INTEGER DEFAULT 0,  -- 1 if context anomaly detected
    clip_path       TEXT                -- populated only if flagged=1
);
```

---

## Hallucination Mitigation

For objects that ARE in the registry, do NOT apply AI super-resolution. Instead:
- Return the stored high-quality reference snapshot
- Composite the reference over the enhanced frame for the review UI

This means a license plate is never upscaled by a neural network that could hallucinate digits. It is shown exactly as it was captured during its first clean sighting.

For objects NOT in the registry (first sighting, low confidence match):
- Apply super-resolution with a visible watermark: `[AI-ENHANCED - NOT FORENSIC ORIGINAL]`
- Log which frames were enhanced and with which model

---

## Feature Matching Approach (implementation guidance for Victor + Riley)

The cheapest viable approach on CPU-only hardware:

1. Crop the ROI bounding box from the frame
2. Compute a perceptual hash (pHash via `imagehash` library) of the crop
3. Compare Hamming distance against all registry entries
4. Threshold: Hamming distance <= 10 is a match (empirically tuned, adjust during M2)

For higher accuracy on license plates specifically (Riley's performance scope):
- Use ORB (Oriented FAST and Rotated BRIEF) feature descriptors via OpenCV
- ORB is royalty-free, CPU-only, runs in < 5ms per frame
- Store 500 keypoint descriptors per registered object
- Match with BFMatcher + ratio test

The pHash approach handles the common case fast. The ORB approach is the fallback for ambiguous matches.

---

## Milestone Assignment

| Task | Owner | Target Milestone |
|---|---|---|
| Schema migration (add tables above) | Victor | Milestone 2 |
| pHash feature extraction + registry lookup | Victor | Milestone 2 |
| ORB descriptor matching for plates | Riley | Milestone 2 (stretch) |
| Reference screenshot writer | Victor | Milestone 2 |
| Anomaly flagging + alert logic | Victor | Milestone 2 |
| Pipeline integration (hook detection into registry) | Bloodawn (KheivenD) | Milestone 2 |
| Benchmark: storage savings with vs. without registry | Bloodawn (KheivenD) | Milestone 3 |

---

## Open Questions

- What is the retention policy for registered objects? (Navy policy TBD - ask Cody)
- Are faces in scope for the registry or only plates/vehicles? (Privacy implications)
- What similarity threshold triggers an anomaly alert vs. a low-confidence miss?

---

*This note should be reviewed with sponsor Cody Hayashi before implementation begins in Milestone 2.*
