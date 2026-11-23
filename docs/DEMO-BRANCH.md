# Demo branch: demo/final-showcase

This is the one branch the Project Showcase (Wednesday 12/9/26) is built and demoed from. Every item on the final demo roadmap lands here. Do not start separate demo branches.

## Where it came from

- Base: `demo/all-changes` at 8e60d1f, which is `main` at ee3c53c plus the redesign (`design/ui-redesign`), Library Delete, the never grow output fix and the upload index fix.
- `demo/all-changes` is now frozen. New work goes on `demo/final-showcase`.
- `main` stays the release line. Merge this branch to `main` only after the code freeze, with the team's agreement, and tag v1.0 from there.

## Rules

1. No force pushes. Do not rewrite history on this branch.
2. Small commits, one roadmap task each, with tests. Run the Python tests before every push. On a machine with Python 3.11 or newer the full suite should be green apart from tests that need local video corpora.
3. Teammates' pull requests merge here in the order listed in the roadmap (task 12.6), one at a time, with the tests run after each.
4. Code freeze: end of day Friday 12/4/26. After that only fixes found in rehearsal.
5. Never edit the compression code for a demo feature. Numbers, Home page and Security cam changes sit around it.

## Roadmap and status

| Task | What | Dates | Status on this branch |
|---|---|---|---|
| 13.2 | Home page: all four modes, each with what it does and when to use it | 11/23 to 11/25 | Done |
| 13.3 | Accurate result numbers (Saved percent, MB before and after) | 11/23 to 11/25 | Done on the server and the Home page. See below |
| 13.4 | Segment length: whole video default, recommended, presets | 11/23 to 11/25 | Done |
| 13.1 | Security cam: phone records, desktop compresses | 11/25 to 12/1 | Desktop and Android both built. Verified on the emulator: 1 minute clips upload, compress and show real sizes (76 to 77 percent saved on the test clips). Real phone and 5 minute length still untested. See docs/SECURITY-CAM.md |
| 12.3 | Live camera testing: phone on the patio, then the EMEET SmartCam S600 | 11/28 to 12/1 | 13.1 Android is built, so this can start |
| 12.4 | Restore and purge for the trash folder | 11/30 to 12/2 | Built, tests pass |
| 12.6 | Review and merge open PRs (includes 8.9) | 11/30 to 12/2 | Merged into this branch: 36, 49, 50, 51, 52, 54, 55, 56, 57. Nothing pushed to main yet |
| 3.11 | Fresh install walkthrough (issue 48) | 12/1 to 12/2 | Open, needs a person on a clean machine (docs/testing/FRESH-INSTALL-WALKTHROUGH.md) |
| 12.5 | Screen reader pass, including the Security cam screens | 12/3 to 12/4 | Open, needs NVDA and TalkBack. The axe scan was not re-run after the Home layout change |
| 15.1 | Showcase: two rehearsals 12/7 and 12/8, show 12/9 | 12/7 to 12/9 | Open |

## What changed for 13.2, 13.3, 13.4

- `src/utils/result_numbers.py`: one algorithm for the numbers on screen. Real source and output file sizes, one megabyte unit (1,048,576 bytes, like Windows Explorer), bytes summed before the percent is computed, one rounding step so the printed figures add up, never 100 percent while a file exists, and a plain "No space saved" when the output is not smaller. It also plans segment length. Tested in `tests/test_result_numbers.py`.
- `src/gui/static/js/svcs_numbers.js`: the same algorithm for the page. Keep the two in step.
- `/api/savings` now returns a `result` block and a `last` block built by that algorithm. The Home page Last result card, the Measured line and the Metrics Space saved tile read those blocks.
- A job split into segments used to be measured against only its newest segment. The index now keeps the combined output size (`output_bytes`), so the saving is measured against everything the job wrote.
- `/api/segment-plan` returns the whole video length, the recommended length (half the video, rounded up to a multiple of 10 seconds) and the presets for a file, or minute presets for a live source.
- A named surveillance preset no longer sets the segment length. That is why the default used to be 60 seconds.
- The raw frame estimate that used to read as "99 percent smaller" is now labelled as an estimate everywhere it still appears.

Known gap for 13.3: the per segment tooltip and the Metrics table still cannot show a measured percent, because a segment does not store its source size. They are labelled as estimates. A real fix needs the source size saved with each segment.

## Running the tests

```
python -m pytest tests -q
```

Python 3.11 or newer is needed for the tests that import `tomllib`. `tests/test_pipeline_stress.py` is slow. Two scene change keyframe tests depend on the installed ffmpeg version.
