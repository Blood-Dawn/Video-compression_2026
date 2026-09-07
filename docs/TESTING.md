# SVCS Testing

How to run the test suite, where the project stands today, and the environment
quirks worth knowing before a first run. For the detailed, dated log of how the
suite grew from its first green baseline to its current size, including every
bug that log of triage work turned up, see `docs/test-baseline.md`. For the
list of owner-gated and deferred items (things a build cannot finish on its
own, such as code signing or a live pentest), see `docs/BLOCKERS.md`.

## How to run the tests

```
pwsh scripts/run_tests.ps1        # Windows, the daily driver
scripts/run_tests.sh              # Linux and CI
```

Both scripts sync the environment against the documented optional extras
first, then run `pytest tests/` with the project's own configuration, tee the
output to a timestamped log under `logs/`, and print a summary. A full run
needs the `enhance`, `plates`, and `crash-reporting` extras; core dependencies,
including the `cryptography` package encryption depends on, come from the base
sync.

## Current baseline

As of the most recent summer changes summary (`docs/CHANGES-SUMMER-2026.md`,
written September 2026), the suite stands at **1,651 tests passing across 96
test files**, up from 274 tests in about 20 files in April 2026. The known
skips are hardware- or network-gated on purpose: real-webcam tests (enabled
with `SVCS_TEST_WEBCAM=1`) and an opt-in Docker build-and-serve test (enabled
with `SVCS_TEST_DOCKER=1`).

The mobile app is the one part of the system this does not cover well. It has
a single JVM unit test file as of this writing, which is why mobile changes
have so far needed a person holding a physical device to verify them; building
out mobile test coverage is the first item on the next round of mobile work
(see `docs/CHANGES-SUMMER-2026.md`).

## Environment quirks worth knowing before a first run

**OpenCV: install `opencv-contrib-python`, not plain `opencv-python`.** The
background subtraction module calls into `cv2.bgsegm`, a contrib-only module,
so a plain OpenCV install is missing a function the pipeline actually needs.
Separately, the plate-reader extra pulls in a package that depends on
`opencv-python-headless`; installing both `opencv-contrib-python` and a
headless OpenCV into the same environment can silently clobber the shared
`cv2` binaries, breaking even basic calls like creating a background
subtractor. The test runner scripts sync only the core, non-conflicting extras
by default for this reason; the plate-reader stack is validated separately, in
its own throwaway environment, following the recipe in the archived
`PLATES-VALIDATION.md` material now folded into `docs/RESEARCH.md`.

**Line endings are normalized.** A `.gitattributes` file pins most text files
to `LF` and leaves PowerShell and batch scripts as `CRLF`, since those tools
prefer it. This exists because an early Windows session, without that file in
place, produced a commit-sized diff that was 100% line-ending churn and no
real content; renormalize with `git add --renormalize .` if a checkout ever
drifts, and keep that as its own isolated commit rather than mixing it with a
functional change.

**Route and blueprint counts are guarded.** Adding a Flask route means
updating the blueprint-registration test and the route-resolution test in the
same commit as the route itself, or the guard tests fail on the count
mismatch by design.

**No em dashes or en dashes anywhere in code, UI text, or documentation.** A
dedicated test enforces this across the source tree. This document, like the
rest of `docs/`, follows the same rule.

## Known limitations

A living list of deferred and owner-gated items, things that could not be
finished inside an automated build session because they need a credential, a
piece of hardware, or a human decision, is kept in `docs/BLOCKERS.md` rather
than duplicated here. As of this writing that list includes an external
network penetration test, a fuzzing pass on the video-ingest path, live
camera-path testing against real RTSP hardware, and the Windows code-signing
certificate needed before a general-availability release.
