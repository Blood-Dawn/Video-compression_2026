# Security cam

A paired phone records short clips and uploads them. The desktop compresses what arrives.

The phone does not stream video, and Bluetooth is not used. Bluetooth is far too slow for camera video. The phone and the desktop are already paired over the network, and Security cam uses that same paired link for each finished clip.

## Flow

1. On the desktop, open the Security cam tab. Pick the clip length and the compression mode, then turn receiving ON. That starts auto compress on the upload folder.
2. On the phone, open Security cam. It checks the link to the desktop, camera permission and charging, reads the clip length from the desktop, and starts recording.
3. Every clip length, the phone closes the clip, queues it for upload and starts the next one.
4. The upload is the existing chunked, resumable upload. A dropped connection resumes from the last byte the server has. The server verifies size, SHA-256 and that the file decodes, then moves it into the upload folder.
5. The auto compress watcher sees the new file, compresses it, and records the source and output sizes. The Security cam tab lists the clip with its real numbers.

## Desktop (built)

- `src/gui/routes/security_cam_bp.py`
  - `GET /api/security-cam`: settings, whether the desktop is receiving, paired phones, recent clips with real sizes. A paired phone may read it.
  - `POST /api/security-cam` with `enabled`, `segment_seconds`, `mode`: dashboard password only, so a phone cannot switch recording on. Clip lengths are 60, 300, 600, 900 or 1800 seconds. Modes are mode0 to mode3. Starting while auto compress watches another folder returns 409 with a plain message.
- `src/gui/static/js/security_cam.js` and the Security cam tab in `index.html`.
- `tests/test_security_cam.py`.

## Android (built, emulator verified 2026-11-23)

Nothing in the app records video today. The manifest says it asks for no camera permission, so that note changes too.

Finding that shapes the design: `WorkManagerServerUploads.start` is single flight. It refuses a second upload while one is running (`ExistingWorkPolicy.KEEP`) and it clears `pending_uploads` and the checkpoint store before each new upload. Calling it once per clip would drop or delete clips whenever one upload runs longer than the clip length. Security cam needs its own queue.

Planned pieces, all new files except the manifest and one navigation entry:

- `securitycam/SecurityCamService.kt`: a foreground service of type `camera`. Records with CameraX `Recorder` and `VideoCapture`, rotates the file every clip length, and writes finished clips to its own folder `filesDir/security_cam/`, never to `pending_uploads`.
- `securitycam/ClipQueue.kt`: keeps finished clips in order. It hands one clip at a time to `UploadWorker` with its own unique work name (for example `security_cam_upload`), so it never touches the picker's staging folder or checkpoints. It deletes a clip only after the server accepted it. If the phone runs low on space it stops recording and says so.
- `securitycam/SecurityCamViewModel.kt` and `ui/securitycam/SecurityCamScreen.kt`: the checklist (link, camera, power), clip length read from `GET /api/security-cam`, Start and Stop, and while recording the time left in the clip, clips sent, waiting and failed.
- `AndroidManifest.xml`: `CAMERA`, `FOREGROUND_SERVICE_CAMERA`, the service entry, and the camera feature marked not required.
- Navigation: a Security cam entry under More.
- Dependencies: CameraX `camera-core`, `camera-camera2`, `camera-lifecycle`, `camera-video`.

Open questions to settle before building:

- `UploadWorker.buildRequest` needs a staged copy and a SHA-256. The service can compute the hash while it copies the closed clip, as `WorkManagerServerUploads` does now.
- Android 14 and later restrict starting a camera foreground service from the background. Start only from the visible screen.
- Battery: recommend plugging the phone in, and show a warning when it is not charging.

## Testing plan

Patio test: phone on a stand, plugged in, pointed at the road and the parking lot. Use Mode 0 first (steady traffic keeps moving, and the research notes favor Mode 0 for continuous motion), then Mode 1 in a quieter hour. Record at least 3 clips 5 minutes apart. Walk the phone out of Wi-Fi range for a minute and confirm the clip still arrives.

SmartCam S600 test: use it as the live source in Auto compress with 5 minute segments and watch 3 clips arrive.

Pass means each clip shows its Saved percent, and the same figure appears on the Security cam tab, the Library and the phone.

## Privacy

A camera that faces a public road records people. Keep the footage on your own machines and use it only for the course demo.

Android status, 2026-11-23: built as the CAM tab under SERVER. Files: securitycam/SecurityCamService.kt (CameraX, camera foreground service), ClipQueue.kt (own folder and unique work name), SecurityCamBus.kt, ui/server/cam/ (screen and view model), net/SecurityCamModels.kt. Cam clips go through UploadWorker with the quiet flag, which skips the per clip notification and skips the phone's Auto-compress toggle, because the desktop watcher compresses them (without that, each clip was compressed twice and one result was bad). Tested on the svcs_test emulator against this branch: pairing, camera permission, 1 minute clips, upload, compress, sizes on both screens. A short gap of under a second between clips is expected. Not yet tested: a physical phone, the 5 minute length over a long run, screen off recording, and low space behavior.

