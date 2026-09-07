# SVCS Testing

How to run the test suite, where the project stands today, and the environment
quirks worth knowing before a first run. For the detailed, dated log of how the
suite grew from its first green baseline to its current size, including every
bug that log of triage work turned up, see `docs/testing/test-baseline.md`. For the
list of owner-gated and deferred items (things a build cannot finish on its
own, such as code signing or a live pentest), see `docs/plans/BLOCKERS.md`.

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
its own throwaway environment, following the reproducible recipe in
`testing/PLATES-VALIDATION.md`.

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
piece of hardware, or a human decision, is kept in `docs/plans/BLOCKERS.md` rather
than duplicated here. As of this writing that list includes an external
network penetration test, a fuzzing pass on the video-ingest path, live
camera-path testing against real RTSP hardware, and the Windows code-signing
certificate needed before a general-availability release.

## Validation evidence

The dated records below are the evidence behind the current baseline. They are
kept as source records, while this section is the index for what each one
proves.

| Record | Coverage | Current interpretation |
|---|---|---|
| `testing/test-baseline.md` | Provisioning, triage, and green-suite checkpoints from M0 through the current rounds | Historical explanations for failures and environment fixes; use the commands above for a fresh run |
| `testing/FEATURE-AUDIT.md` | Route and feature behavior, including upload, library, auto-compress, and live-path checks | CI-safe checks are automated; real RTSP and MediaMTX checks remain owner-gated |
| `testing/PLATES-VALIDATION.md` | Throwaway-environment proof that the ONNX plate-reader packages can coexist with contrib OpenCV when installed with `--no-deps` | Do not install the plate extra through a normal resolver path without rechecking the documented pins |
| `research/stress_test_results.md` | Pipeline memory, storage, throughput, and long-running behavior | Stress results are workload-specific evidence, not a universal performance guarantee |

## Focused validation gates

For a code change, run the narrowest relevant check first, then the full suite
before release. Encoder changes need data-integrity, output-decodability, and
mode behavior tests. Route changes need the blueprint and route-resolution
guards. Security changes need the matching regression tests under
`tests/security/`. Desktop changes that affect a frozen build also need the
PyInstaller smoke path; mobile changes need an Android build and a physical or
emulated device check because the JVM test coverage remains thin.
