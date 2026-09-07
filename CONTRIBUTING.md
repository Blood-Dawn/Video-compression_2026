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
2. Create a branch off `dev` (or off `app` for product work)
3. Make your changes
4. Run the test suite locally: `pytest tests/`
5. Open a PR back to the upstream `dev` or `app` branch

PRs are reviewed within 7 days. Smaller PRs get merged faster.

## Coding conventions

- Python 3.11+
- Type hints on all new public functions
- Tests for new behavior (the bar is "if it broke, would I find out?")
- Black for formatting, ruff for linting
- No new dependencies without justification in the PR description

## Branch layout

| Branch | Purpose |
|---|---|
| `main` | Public, stable branch. Kept current with the full desktop feature set; excludes the in-progress mobile app. |
| `app` / `mobile` | Internal working branches, currently identical. Everything lands here first, including the in-progress Android app under `mobile/android/`. |

### One open-source edition

SVCS ships as a single open-source edition, under AGPL-3.0. There is no
paid tier (see `README.md`). Everything is free:
compression, the four modes, search, encryption, YOLO object filter,
Real-ESRGAN enhancement, and the AI plate reader.

Some features stay behind optional `pyproject.toml` extras only to keep the
default install small, not to gate them behind payment:

- `[plates]` - the AI plate reader (EasyOCR). Free; split out because
  EasyOCR is heavy. The dashboard hides the plate-reader controls when the
  backend isn't installed, so a base install shows no empty buttons.
  (Note: install `[plates]` in a *separate* environment - see the warning
  in `pyproject.toml`; easyocr's OpenCV conflicts with the core build.)
- `[enhance]` - Real-ESRGAN super-resolution.
- `[crash-reporting]` - opt-in Sentry (off by default).

If a commercial variant is ever built, it will be a separate fork in its
own repository, not a branch here.

## Tests

We have 274+ tests across unit, integration, and stress. Don't break
them. If you change behavior, update the affected tests in the same PR.

```
pytest tests/                # all tests
pytest tests/test_pipeline.py # one file
pytest -k encrypt            # match by keyword
```

## Questions

Open an issue tagged `question`, or email kdhaiti2024@fau.edu.
