# Fall 4.4: Upload survival test (force-stop mid-transfer)

Planner outcome: "Transfer resumes from the server-reported offset and
completes." Verifies 4.3 (UploadWorker, PR #22, branch
`jorge/4.3-upload-worker`) on a real Android runtime, which the JVM tests
cannot do: they cannot kill a process.

## Setup

- Server: SVCS desktop running on the same PC, dashboard at
  http://localhost:5000.
- Device: an Android phone, or an emulator (Pixel 7/8, system image API 35,
  see EMULATOR-GUIDE.md). An emulator pairs against `http://10.0.2.2:5000`;
  a phone pairs against the PC's LAN address.
- App: debug build of `jorge/4.3-upload-worker`, installed with Run in
  Android Studio. Debug package: `org.svcs.mobile.debug`.
- Test clip: any 50-100 MB video, big enough that the upload takes a while.
  To make one: `ffmpeg -f lavfi -i testsrc2=size=1920x1080:rate=30 -t 60
  -c:v libx264 -preset ultrafast -b:v 10M test_upload_4.4.mp4` (~75 MB).
  Record its size in bytes and SHA-256 before starting
  (`certutil -hashfile test_upload_4.4.mp4 SHA256` on Windows).
- Slow the network so the upload lasts long enough to interrupt. Emulator:
  Extended controls (the `...` button) > Cellular > Network type: EDGE, then
  Wi-Fi off in the emulator. Phone: any slow Wi-Fi, or just a bigger file.

## Steps

1. Pair the app with the server (MORE tab) and turn auto-compress OFF in
   MORE, so the result is just the uploaded file.
2. SERVER > LIBRARY > UPLOAD, pick the test clip.
3. Confirm the "Uploading <name>" notification appears with a percentage.
   Wait until it is between 20% and 60%. Note the percentage.
4. Kill the app: Settings > Apps > SVCS > Force stop
   (or `adb shell am force-stop org.svcs.mobile.debug`).
5. Confirm the notification is gone and the percentage no longer moves.
6. Reopen the app. Note the first percentage LIBRARY or the notification
   shows after reopening.
7. Wait for "Upload finished".
8. On the PC, find the uploaded file in the server's uploads folder and check
   its size and SHA-256 against the values recorded in Setup.

## Pass criteria

- After reopening, progress continues from about where it was killed, not 0%.
- The upload finishes on its own.
- The file on the server is byte-identical (same size and SHA-256).
- Only one copy of the file lands on the server (no duplicate from a
  restarted upload).

## Results

| Check | Result | Evidence |
|-------|--------|----------|
| % when force-stopped | 43% | notification: "Uploading 1000000041.mp4" / "43% sent" (dumpsys notification) |
| First % after reopening | not captured as a single frame; see notes | server log shows one begin and one finish for this upload, so it was the same session resuming, not a fresh one |
| Upload finished on its own | yes | notification: "Uploaded 1000000041.mp4. Auto-compress is off; compress it whenever you are ready." |
| Size on server matches | yes, 75187707 bytes both sides | `Get-FileHash`/`Get-Item` on the test clip and on `data/uploads/1000000041.mp4` |
| SHA-256 matches | yes, 4709e82503d95ddd9c90cab8735573cdd77b07ecef2834cd8b077caf4548e542 both sides | `Get-FileHash -Algorithm SHA256` on both files |
| Single copy on server | yes, one `1000000041.mp4`, no `_1`/`(1)` duplicate | directory listing of `data/uploads/` |

Tested by: Kheiven D'Haiti (run end to end by Claude, at Kheiven's request, on Kheiven's dev machine)
Date: 2026-09-27
Device / emulator image: Android Emulator, AVD `svcs_test`, system image android-35 (Android 15) google_apis x86_64, network throttled to 3000:3000 kbps via `adb emu network speed`

## Notes / anything odd

Ran this with the emulator, per the "Device" line in Setup above, since Jorge's
own attempt at this had trouble and asked in the group chat for someone to run
it. Automated end to end: paired the app with a locally minted device token,
picked a 75,187,707-byte synthetic clip from the Photo Picker, force-stopped
mid-transfer at 43%, reopened, and let it finish.

The strongest evidence this was a real resume and not a restart-from-zero is
the desktop's own log, not a screenshot: it shows exactly one
`Chunked upload begun: 1000000041.mp4` line and exactly one
`Chunked upload finished: 1000000041.mp4` line for the whole run. A
restart-from-zero after the force-stop would have logged a second `begun`
line with a new upload id for the same file name; it did not, so the resumed
run reattached to the same upload the first run had started, which is exactly
what UPLOAD-WORKER-DESIGN.md calls for.

One thing worth a look, not a failure: right after the notification said
"Uploaded," the finished file briefly showed up empty (0 bytes) at
`outputs/uploads/1000000041.mp4` before settling at its final, correct
location and size at `data/uploads/1000000041.mp4`. That reads as the
server relocating a just-finished upload into the folder it treats as
compressible input, which existed before this test and is unrelated to
4.3/4.4, but it is a distinct step from the chunk-upload path this test
covers and is not itself covered by anything in section 5.
