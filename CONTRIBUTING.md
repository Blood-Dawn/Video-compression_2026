# Contributing to SVCS

Thanks for considering a contribution. SVCS started as a senior capstone
project at Florida Atlantic University and is now an open-source video
compression toolkit aimed at self-hosted media libraries and surveillance.

## Code of conduct

Be civil. Disagreements about technical decisions are welcome, personal
attacks are not.

## License

SVCS is open source only, under AGPL-3.0 (see `LICENSE`). There is no
commercial edition and no CLA to sign. By opening a pull request, you
agree your contribution is licensed under the same AGPL-3.0 terms as the
rest of the project. If a commercial variant is ever built, it will live
in its own separate fork and repository, not here.

## How to contribute

### Reporting bugs

Open a GitHub issue with:

- What you ran (command, OS, Python version, FFmpeg version)
- What you expected
- What happened instead
- A minimal reproduction if possible

### Suggesting features

Open a GitHub issue tagged `enhancement`. Describe the use case and the
problem you're trying to solve. Avoid suggesting a specific solution
before there's agreement on the problem.

### Submitting code

1. Fork the repo
2. Create a branch off `mobile` (the active working branch)
3. Make your changes. Setup, run and test instructions for the desktop app
   and the Android app are in `DEV.md`.
4. Run the tests for what you touched: `uv run pytest` for Python,
   `./gradlew testDebugUnitTest` in `mobile/android` for Android. CI runs both.
5. Open a PR into `main`

PRs are reviewed within 7 days. Smaller PRs get merged faster.

## Coding conventions

- Python 3.11+, Kotlin 2.1 for the Android app
- Type hints on all new public Python functions
- Tests for new behavior (the bar is "if it broke, would I find out?")
- `uvx ruff check .` stays clean (pyflakes rules, configured in pyproject.toml)
- ASCII hyphens only: no em or en dashes anywhere (a test enforces it)
- Comments explain why, not what
- No new dependencies without justification in the PR description. Python
  dependencies go in pyproject.toml followed by `uv lock` and
  `python scripts/export_requirements.py`; never edit requirements.txt by hand

## Branch layout

| Branch | Purpose |
|---|---|
| `main` | Public, stable branch. PRs go here. |
| `mobile` | Active working branch for the desktop app and the Android app under `mobile/android/`. Work lands here first. |

The older `dev` and `app` branches no longer exist.

### One open-source edition

SVCS ships as a single open-source edition, under AGPL-3.0. There is no
paid tier (see `README.md`). Everything is free:
compression, the four modes, search, encryption, YOLO object filter,
Real-ESRGAN enhancement, and the AI plate reader.

Some features stay behind optional `pyproject.toml` extras only to keep the
default install small, not to gate them behind payment:

- The AI plate reader. Recommended: the ONNX reader installed with
  `scripts/install_plates.ps1` into the main environment. The legacy
  `[plates]` extra (EasyOCR) must only go into a *separate* environment,
  because its OpenCV replaces the core contrib build (see the warning in
  `pyproject.toml`). The dashboard hides the plate-reader controls when no
  backend is installed.
- `[enhance]` - Real-ESRGAN super-resolution.
- `[crash-reporting]` - opt-in Sentry (off by default).

If a commercial variant is ever built, it will be a separate fork in its
own repository, not a branch here.

## Tests

About 1,660 Python tests (unit, integration, stress, `tests/security/`) and 67
Android JVM tests. Don't break them; if you change behavior, update the
affected tests in the same PR, and never weaken or skip one just to get green.

```
uv run pytest                          # all Python tests
uv run pytest tests/test_pipeline.py   # one file
cd mobile/android && ./gradlew testDebugUnitTest   # Android
```

## Questions

Open an issue tagged `question`, or email kdhaiti2024@fau.edu.
