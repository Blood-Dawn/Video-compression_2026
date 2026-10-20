# Code style for SVCS

Short rules for code that reads like a careful person wrote it and stays cheap to run. They apply to `src/`, `tests/`, `scripts/` and the Android app. When a rule here fights readability in a specific spot, readability wins; say why in a comment.

Where these came from: a Reddit thread comparing an AI-heavy codebase with a hand-written one, a few dev.to write-ups on what makes generated code feel off, and OpenCV's own Python performance tutorial. Sources are at the bottom. Most of the "human code" points are practitioner opinion, not research, so treat them as a checklist, not law.

## Comments

* Comment the **why**: a non-obvious decision, a workaround, a constraint from hardware or a library, a bug that this line prevents. Delete comments that restate the next line (`# increment counter`, `# return the result`).
* No changelog in comments. "Before 0.8.0 this did X, then a user reported Y, so now Z" belongs in the commit message. Keep the last sentence (the reason Z is right) if it is not obvious from the code.
* Docstrings on public functions and anything with a contract worth stating. A three-line private helper does not need one. A docstring says what the function promises, not how each line works.
* Keep `Author:` lines. They are the course's record of who wrote what.
* `TODO` only for real, known follow-up work, with enough context to act on it. No placeholder TODOs.
* Dense math or tricky indexing gets more comment, not less. Plumbing gets less.

## Naming

* Short names in short scopes (`i`, `x`, `row`, `ts` inside a five-line loop). Longer, exact names for things that live long or cross module boundaries.
* One name per concept across a file. Do not cycle synonyms (`frame`, `img`, `picture`) for the same thing.
* Match what the codebase already calls it (`segment`, `camera_id`, `object_type`) before inventing a new word.

## Structure

* Write the direct version first. Add a class, helper or layer only when there is a second real caller or the function stops fitting on a screen.
* A helper used once that just renames another call should be inlined.
* Early returns over nested `if/else` pyramids.
* Use what is already here (the shared SSRF guard, `db.queries`, the encoder classes) and the standard library before writing a new utility.
* Prefer plain data (dicts, dataclasses, tuples) over objects that only hold data.
* Long functions are fine when they read top to bottom as one story. Split when the pieces have names that explain themselves.

## Errors

* Catch the exceptions that can actually happen, as narrowly as you can, where you can do something about them.
* No blanket `try/except Exception: pass`. If swallowing is right (best-effort cleanup, optional feature), log at debug level or say why in one comment.
* Do not re-check what the framework or type already guarantees. Validate at the boundary (HTTP input, files, user settings), then trust the value inside.
* Fail loud in scripts and tests.

## Time and space

* Measure before optimizing: `python -m cProfile -o out.prof ...` and `pstats`, or `tracemalloc` for memory. Put the before/after numbers in the commit.
* Per-frame code is the hot path. Nothing in it should allocate a full frame copy it does not need, re-open a file, re-compile a regex, re-build a lookup table, or query the database.
* Prefer OpenCV calls over NumPy equivalents and NumPy over Python loops on pixels. Use views (`frame[y0:y1, x0:x1]`) instead of copies unless the copy is the point.
* Membership tests on anything that grows go in a `set` or `dict`, not a list.
* Build strings and lists with `join` and comprehensions, not repeated `+=` in a loop.
* Stream large files and large query results; do not read everything into memory when an iterator works.
* Let SQLite do filtering, sorting and limits in the query instead of in Python. Check that filtered columns have an index.
* Cache only what is expensive and stable, and bound the cache (`functools.lru_cache(maxsize=...)`).

## Formatting

* `ruff check` must stay clean with the rules in `pyproject.toml`.
* Modern annotations (`list[str]`, `X | None`) in new or touched code.
* No emojis, em dashes or en dashes in code, comments, docs, or commit messages.

## Tests

* Test behavior a user or caller would notice, not that Python can assign a variable.
* One clear assertion story per test. Name the test after the behavior.
* A test that cannot fail is worse than no test.

## Sources

* Reddit discussion of an AI-heavy vs hand-written Python ML project (snapshot): https://reddit.sentinel-team.org/posts/1qjbipc/snapshots/2026-01-23T23%3A01%3A37.92847Z
* "Was this Python written by a human or an AI? 7 signs": https://dev.to/dev_tips/was-this-python-written-by-a-human-or-an-ai-7-signs-to-spot-llm-generated-code-3370
* "Why AI-generated code feels weird": https://dev.to/unknown_destroyer_f353870/why-ai-generated-code-feels-weird-1bd2
* "Simple over easy: architectural constraints that make AI-generated code maintainable": https://dev.to/forgecode/simple-over-easy-architectural-constraints-that-make-ai-generated-code-maintainable-4o77
* OpenCV, Performance Measurement and Improvement Techniques: https://docs.opencv.org/4.x/dc/d71/tutorial_py_optimization.html

Author: Bloodawn (KheivenD), 2026-10-13.
