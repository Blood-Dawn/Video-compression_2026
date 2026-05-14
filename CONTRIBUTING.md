# Contributing to SVCS

Thanks for considering a contribution. SVCS started as a senior capstone
project at Florida Atlantic University and is now an open-source video
compression toolkit aimed at self-hosted media libraries and surveillance.

## Code of conduct

Be civil. Disagreements about technical decisions are welcome, personal
attacks are not.

## Two licenses, one decision to make

SVCS is dual-licensed. Read both before contributing:

- `LICENSE` (AGPL-3.0): the open-source side. Free for personal, academic,
  and OSS use.
- `LICENSE-COMMERCIAL.md`: the commercial side for companies that don't
  want to ship their source code under AGPL.

If you contribute code that ends up in the main branch, your contribution
is dual-licensed under both. That means:

- Anyone using SVCS under AGPL can use your contribution for free.
- Anyone buying a commercial license also gets your contribution, and a
  share of the revenue flows back to all contributors per the schedule
  in `CLA.md`.

## CLA

Before your first substantial contribution is merged, you need to sign
the Contributor License Agreement in `CLA.md`. Trivial contributions
(typo fixes, doc tweaks) can be merged without a CLA.

To sign, open a PR adding your name and signature to the table at the
bottom of `CLA.md`. The current maintainer (Kheiven D'Haiti) will
confirm.

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
| `main` | Stable release line. Tagged versions only. |
| `dev` | Active development of the Python pipeline (v1 series). |
| `app` | Productization for the casual / open-source edition (installers, mobile, presets). |
| `premium` | Premium-only features for the commercial-tier edition. Branches off `app`. Plate reader, advanced presets, paid-only experiments. |
| `kdev` | Experimental Rust port (v2 series). Not stable. |

### `app` vs `premium`

The `app` branch builds the casual edition that ships under AGPL. It
includes everything an open-source user needs: compression, four modes,
search, encryption, YOLO object filter, Real-ESRGAN enhancement.

The `premium` branch builds the commercial-license edition. It contains
everything in `app` plus features that are paid-tier only: the AI plate
reader, future advanced scene-aware bitrate tuning, batch priority
queue, anything else we decide is worth charging for.

Premium features should be:

- Added on the `premium` branch only.
- Opt-in at install time (via an optional dependency extra in
  `pyproject.toml` where reasonable).
- Hidden in the UI when their backing dependencies aren't installed,
  so the casual edition doesn't show empty buttons.

Bug fixes on `app` need to be merged into `premium` regularly to keep
the two branches in sync. Use `git merge app` from `premium` after
every batch of `app` commits.

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
