# SVCS Mobile 1.2.0-beta (versionCode 15) - release notes

**Released 2026-09-24 on `mobile`, tag `v1.2-beta`.**

**Known issue, fixed in 1.2.1-beta.** The compressor could ask the encoder
for more bitrate than the source video actually had, so a small file could
come out bigger than it went in instead of smaller. See
[release-notes-mobile-1.2.1-beta.md](release-notes-mobile-1.2.1-beta.md)
for the fix; anyone on 1.2.0-beta should update.

## What's new

- **Smart Compress, region mode.** On phones whose video encoder supports
  Android 15's region-of-interest feature, Smart Compress now keeps the
  bitrate you picked and spends more of it where it saw people, vehicles or
  animals, and less on the static rest. On every other phone it works as
  before: footage with nothing happening gets compressed harder. The MORE
  screen shows which mode your phone gets.
- **Size limits land closer to the limit.** Phones' hardware encoders
  usually undershoot, so a 10 MB Discord job used to come out around 8 MB.
  After a few size-limit jobs the app learns how far your phone
  undershoots and asks for a little more. If a boosted job would come out
  over the limit, it is encoded again at the old, safe bitrate.
- **Honest results.** If the phone quietly encoded at a lower resolution
  or switched H.265 to H.264, the result screen says so, and SAVED tags the
  job.
- **Screenshots work.** The app no longer blocks screenshots or screen
  recording, so you can capture results and bug reports.
- **One SERVER tab.** With a desktop server paired, HOME, LIBRARY, LIVE,
  EVENTS and METRICS now sit under SERVER instead of crowding the bottom
  bar.

## Verified before release (fill in on the phone)

- [ ] Installs over 1.1.0-beta; SAVED history is kept.
- [ ] MORE lists the phone's encoders.
- [ ] A Discord (10 MB) job, run three or more times on different clips,
      then a fourth: the fourth lands closer to 10 MB and never over.
- [ ] If MORE says region-of-interest is supported: a Smart Compress job
      on footage with a person reports "gave that part of the picture more
      of the bitrate", and the file size matches a plain job's.
- [ ] Paired with a server: SERVER shows the five sections; LIVE only when
      the server streams.

## What was verified in development

- 97 JVM unit tests pass (region planning, box decoding, calibration,
  fallback notices, tab rules, and everything from 1.1.0-beta), including
  the settings test that used to fail under Robolectric.
- Debug and release (R8) builds succeed. CI now builds and tests the app
  on every push.
- Not run on a phone or emulator during development (none was available).
  The checklist above is the device check.

## Known limits

- Region mode has not yet been seen working on a real `FEATURE_Roi` device.
  It can only move bits within the same bitrate, and any failure falls back
  to a normal encode, but its visual benefit is unmeasured.
- Region mode uses one plan for the whole clip, which fits fixed cameras
  best. Subjects that cross the whole frame get little from it.
