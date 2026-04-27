# =============================================================================
#  merge_team_prs.ps1
#  Integrates PRs #8, #9, #10 into dev with KD fixes applied.
#  Run from inside the project root with venv active.
#
#  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#  .\merge_team_prs.ps1
#
#  After this script: push dev and close PRs #8, #9, #10 on GitHub with
#  comment: "Integrated into dev with fixes applied. See commit for details."
# =============================================================================

$ErrorActionPreference = 'Stop'

function Write-Step { param($msg) Write-Host "" ; Write-Host ">>> $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }

Write-Host ''
Write-Host '=============================================' -ForegroundColor Magenta
Write-Host '  Merge Team PRs #8 #9 #10 into dev        ' -ForegroundColor Magenta
Write-Host '=============================================' -ForegroundColor Magenta

# Confirm we are in the right place
if (-not (Test-Path 'requirements.txt')) {
    Write-Host '[FAIL] Run this from inside the project root.' -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Sync dev with origin
# ---------------------------------------------------------------------------
Write-Step 'Syncing dev with origin...'
git checkout dev
git pull origin dev
Write-OK 'dev is up to date'

# ---------------------------------------------------------------------------
# PR #8 — Victor: Enhancement Benchmarking
# ---------------------------------------------------------------------------
Write-Step 'Merging PR #8 (victort29/feature/enhancement-milestone2)...'
git fetch origin feature/enhancement-milestone2

git merge --squash origin/feature/enhancement-milestone2
Write-OK 'Squash merge staged'

# Apply KD fix: replace benchmark_enhancer.py with corrected version
Write-Warn 'Applying fix: save_csv fieldnames bug in benchmark_enhancer.py'
Copy-Item '_fix_benchmark_enhancer.py' 'scripts\benchmark_enhancer.py' -Force
git add 'scripts\benchmark_enhancer.py'

git commit -m 'feat(benchmark): add enhancer CPU benchmark script and notebook [PR #8]

Integrated from victort29/feature/enhancement-milestone2.

What this adds:
  - scripts/benchmark_enhancer.py: CLI tool to measure Enhancer CPU
    inference time across 240p/480p/720p at various ROI sizes
  - notebooks/milestone2_enhancer_benchmark.ipynb: visualises timing
    data with a 30fps budget reference line

Fixes applied during integration (KD):
  - save_csv() now collects fieldnames across ALL result dicts so
    upscale_frame rows (no roi_size key) and upscale_roi rows (has
    roi_size key) can be written to a single CSV without ValueError
  - roi_size field set to empty string in frame results for schema
    uniformity -- no silent data loss, no DictWriter crash
  - Path(...).mkdir(parents=True, exist_ok=True) already present in
    save_csv; notebook should add same guard for figure output dir

PR targeted main instead of dev -- merged directly to dev per project
branch strategy (ROADMAP.md Section: Branch and PR Strategy).

Closes #8'

Write-OK 'PR #8 committed'

# ---------------------------------------------------------------------------
# PR #9 — Jorge: Algorithm Comparison and Stress Test
# ---------------------------------------------------------------------------
Write-Step 'Merging PR #9 (sanchez-jorge/feature/benchmarking-milestone2)...'
git fetch origin feature/benchmarking-milestone2

git merge --squash origin/feature/benchmarking-milestone2
Write-OK 'Squash merge staged'

# Apply KD fix: replace test_pipeline_stress.py with corrected version
Write-Warn 'Applying fix: duration env var + peak memory check + sys.path removal'
Copy-Item '_fix_test_pipeline_stress.py' 'tests\test_pipeline_stress.py' -Force
git add 'tests\test_pipeline_stress.py'

git commit -m 'feat(test+docs): algorithm comparison and pipeline stress test [PR #9]

Integrated from sanchez-jorge/feature/benchmarking-milestone2.

What this adds:
  - tests/test_pipeline_stress.py: 1-hour pipeline stress test and
    storage extrapolation validator (marked @pytest.mark.slow)
  - docs/algorithm_comparison.md: MOG2 vs KNN analysis; recommends
    MOG2 as production default
  - docs/stress_test_results.md: findings and 60-day/100-camera
    storage extrapolation
  - notebooks/algorithm_comparison.ipynb: side-by-side visualisation

Fixes applied during integration (KD):
  - Removed sys.path.insert -- conftest.py adds src/ for all tests
  - SIMULATED_DURATION_S now reads STRESS_DURATION_S env var (default
    3600) so CI can run a short smoke: STRESS_DURATION_S=120 pytest
  - Memory growth check now uses tracemalloc peak, not just final vs
    initial snapshot, so transient spikes are caught

PR targeted main instead of dev -- merged directly to dev per project
branch strategy.

Closes #9'

Write-OK 'PR #9 committed'

# ---------------------------------------------------------------------------
# PR #10 — Jorge: Detection Tuning
# ---------------------------------------------------------------------------
Write-Step 'Merging PR #10 (sanchez-jorge/feature/detection-tuning)...'
git fetch origin feature/detection-tuning

git merge --squash origin/feature/detection-tuning
Write-OK 'Squash merge staged'

# Apply KD fix: replace tuning_experiment.py with corrected version
Write-Warn 'Applying fix: separate CLAHE and Night columns in output table'
Copy-Item '_fix_tuning_experiment.py' 'src\background_subtraction\tuning_experiment.py' -Force
git add 'src\background_subtraction\tuning_experiment.py'

git commit -m 'feat(tuning): MOG2/KNN parameter calibration across lighting conditions [PR #10]

Integrated from sanchez-jorge/feature/detection-tuning.

What this adds:
  - src/background_subtraction/tuning_experiment.py: standalone script
    that evaluates MOG2 and KNN across daytime/night/mixed-lighting
    using synthetic frames; reports FP/FN rates per config
  - docs/detection_tuning_results.md: recommended param sets;
    MOG2 varThreshold=16 daytime, =30 night

Key findings:
  - MOG2 stays under 2% FP rate across all conditions
  - KNN exceeds 50% FP rate under mixed/transitional lighting

Fixes applied during integration (KD):
  - Output table now has separate CLAHE and Night columns instead of
    one combined column that conflated use_clahe and night_mode flags
  - noisy frame generator uses np.random.default_rng(42) for
    reproducibility (author partially fixed; completed here)

PR targeted main instead of dev -- merged directly to dev per project
branch strategy.

Closes #10'

Write-OK 'PR #10 committed'

# ---------------------------------------------------------------------------
# Clean up temp fix files
# ---------------------------------------------------------------------------
Write-Step 'Cleaning up temp fix files...'
Remove-Item '_fix_benchmark_enhancer.py'
Remove-Item '_fix_test_pipeline_stress.py'
Remove-Item '_fix_tuning_experiment.py'
git add -u
git commit -m 'chore: remove temporary KD fix files used during PR integration'
Write-OK 'Cleanup done'

# ---------------------------------------------------------------------------
# Done -- user must push
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '=============================================' -ForegroundColor Magenta
Write-Host '  All PRs integrated into dev!' -ForegroundColor Green
Write-Host '=============================================' -ForegroundColor Magenta
Write-Host ''
Write-Host 'Now push dev to origin:' -ForegroundColor White
Write-Host '  git push origin dev' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Then on GitHub, close PRs #8, #9, #10 with this comment:' -ForegroundColor White
Write-Host '  Integrated into dev with fixes applied. See merge commit for details.' -ForegroundColor Gray
Write-Host ''
