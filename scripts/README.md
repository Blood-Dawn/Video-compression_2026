# scripts/

Helper scripts for the desktop app and the repo. Run them from the repo root
(`uv run python scripts/<name>.py` for Python ones). The Android app has its
own tooling under `mobile/android/` (Gradle, `verify-toolchain.ps1`).

## Setup and everyday use

| Script | What it does |
|---|---|
| `setup_new_pc.ps1` | Windows dev setup: installs uv and FFmpeg if missing, `uv sync --frozen`, checks the core imports. |
| `check_deps.sh` | Linux/macOS readiness check: uv, FFmpeg, the locked environment, core imports. |
| `start.ps1` | Launch the dashboard from source with the `enhance` extra. |
| `demo.sh` | Run the pipeline CLI on a test clip with a live preview. |
| `run_tests.ps1`, `run_tests.sh` | The reference full test run: sync extras, run pytest, log to a file. |
| `install_plates.ps1` | Install the ONNX plate reader into the core environment with `--no-deps` (see the pyproject `[plates]` note). |

## Repo maintenance

| Script | What it does |
|---|---|
| `export_requirements.py` | Regenerate `requirements.txt` from `uv.lock` (`--check` to verify). |
| `check_doc_links.py` | List Markdown links and repo paths that no longer resolve. |
| `update_planner.py` | Keep the Fall 2026 planner CSV and Markdown in `docs/project-records/` in sync. |
| `winget_validate.ps1` | Validate the winget manifests; `-Recompute` rehashes a built installer. |

## Benchmarks, data and research

| Script | What it does |
|---|---|
| `run_benchmark.py` | Selective compression vs plain H.264 on one clip or category. |
| `run_full_test_matrix.py` | Many scenes, methods and warmups in one pass, compared against an older CSV. |
| `run_all_cdnet.py` | MOG2 and KNN over every CDnet 2014 scene (uses `demo_detection.py`). |
| `demo_detection.py` | Side-by-side original / mask / boxes images and a foreground coverage report. |
| `benchmark_enhancer.py` | CPU cost of the super-resolution enhancer per frame and per ROI. |
| `test_sr_honest.py` | Does super-resolution beat bicubic on real footage? PSNR/SSIM plus cost. |
| `convert_cdnet_to_mp4.ps1` | Turn CDnet image sequences in `data/dataset` into MP4s. |
| `pull_traffic_footage.py` | Record public traffic-camera HLS streams for offline tests. |
| `render_virat_overlays.py` | Draw VIRAT annotations as preview videos. |
| `fuzz_ingest_upload.py` | Adversarial and mutation fuzzing of the upload and ingest paths. |

## archive/

Finished one-off scripts kept for the record, not maintained:
`merge_team_prs.ps1` merged the Spring 2026 team PRs #8 to #10 into the old
`dev` branch.
