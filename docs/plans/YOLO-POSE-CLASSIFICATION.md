# YOLO pose confirmation and people/vehicle search (planner 6.11)

Status: implemented 2026-10-07. Owner: Kheiven D'Haiti.

## Why

Another presenting group used YOLO pose in their detection. The request was to add it here so classifying a detection as a person or a vehicle does not rest on motion alone, and so the metrics search can filter to only people or only vehicles.

## What already existed

Detection was never motion only. MOG2 finds moving regions, and `ObjectFilter` then runs YOLOv8-nano on each region crop and keeps it only if a target COCO class (person, vehicle, animal, and so on) is found. Segment labels such as `person`, `vehicle` and `person+vehicle` come from those class sets. That is bounding box classification: one class score per box, with no notion of body structure. A mannequin, a poster or a reflection can score as a person.

## What changed

1. Pose confirmation. `src/detection/pose_onnx_backend.py` adds `YoloPoseOnnxDetector`, which wraps `yolov8n-pose.onnx` (17 COCO keypoints per person). `ObjectFilter` takes `use_pose`, `pose_confidence` and `pose_min_keypoints`. When enabled, any region the box classifier calls "person" is also run through pose, and it counts as pose-verified only if enough keypoints are visible.
2. Pose is additive. A person box that pose does not confirm is still kept, and the segment label is unchanged, so recall cannot regress. Only the pose-verified subset narrows. Vehicle boxes are never pose-checked. If the pose model or runtime is missing, everything behaves exactly as before.
3. Storage. A new `segments.pose_verified_person_count` column (idempotent migration) is filled from a per-segment counter in `run_pipeline()` through `ROIEncoder.finish_segment()` and `insert_segment()`. New pipeline arguments: `use_pose_classification` (default off) and `pose_confidence`.
4. Search gap fixed. A "Person", "Vehicle" or "Animal" filter used to match `object_type` by strict equality, so any mixed segment (`person+vehicle`, `vehicle+animal`, `person+animal`) was hidden. Both `/api/segments` (the archive search panel) and `query_by_type()` now also match those combo labels. An explicit combo pick such as "Person + Vehicle" still matches exactly.
5. UI. The archive search has a "Pose-verified people only" checkbox (`pose_verified_only=1`) and shows a `[P]` badge next to the People count for segments with pose-verified people.

## Enabling it

Export the weights once (gitignored, like `yolov8n.onnx`):

    yolo export model=yolov8n-pose.pt format=onnx imgsz=640

Place `yolov8n-pose.onnx` in the repo root, then pass `use_pose_classification=True` to `run_pipeline()`. There is no GUI toggle for this yet.

## Known limits

`person_count` and `vehicle_count` still count distinct class names seen in a segment, not object instances, so `person_count` is 0 or 1 today. `pose_verified_person_count` follows the existing accumulator and counts pose-confirmed person regions across frames, so it is not directly comparable to `person_count` and is best used as a yes/no filter. Fixing instance counting is separate work.

## Tests

`tests/test_pose_onnx_backend.py`, `tests/test_object_filter_pose.py` (fake backends, no model needed), and additions to `tests/test_object_type_queries.py` for combo labels and the new column. Real-model tests skip when `yolov8n-pose.onnx` is absent.
