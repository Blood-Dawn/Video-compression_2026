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
| % when force-stopped | | screenshot |
| First % after reopening | | screenshot |
| Upload finished on its own | | screenshot of notification |
| Size on server matches | | |
| SHA-256 matches | | |
| Single copy on server | | |

Tested by: ____________    Date: ____________
Device / emulator image: ____________

## Notes / anything odd
