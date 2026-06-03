# Autonomous-run prompt for Claude Code

Paste the block below into Claude Code (auto/full-access mode) to build SVCS v2 end-to-end.

---

You are executing the SVCS v2 build **autonomously**. First read `docs/CLAUDE-CODE-MASTER-PLAN.md` in full - it is the single source of truth (it points to `docs/REFACTOR-PLAN-gui-app.md`, `docs/EXECUTION-CLAUDE-CODE.md`, and `docs/PLAN-V2.md` for deeper detail). TASK 1.1 is already done and committed; start at TASK 1.2.

**Mission:** complete every non-gated task across all milestones (M1 TASK 1.2 → M5b), in dependency order, **without pausing for my approval between tasks**. Run continuously until all non-gated work is done.

**Per-task loop - repeat for every task, in order:**
1. Pick the next unchecked `[ ]` task whose dependencies are satisfied.
2. Implement it fully per its spec in the master plan (+ the referenced design docs). Add/extend the exact tests the task names.
3. Run `pwsh scripts/run_tests.ps1`. It MUST end **≥ 513 passed, 0 failed** (3 webcam skips are expected). If red, fix it before moving on. **Never commit a red suite. Never delete, weaken, or skip a test to fake green** - if a test is genuinely obsolete, rewrite it and add a comment explaining why it changed.
4. Tick the task `[ ]`→`[x]` in `docs/CLAUDE-CODE-MASTER-PLAN.md`.
5. Commit, then `git push origin app`. Commit format: `<type>(<scope>): <subject>`, a body explaining *why*, final line exactly `Bloodawn(KheivenD)`. No emojis. One reviewable commit per task (per sub-module for TASK 1.2, per feature area for TASK 1.5).
6. Move to the next task immediately. Do not stop to ask me.

**Obey all of these (they're in the plan; do not violate them):**
- Branch `app` only. No `premium` mirror. The human convention "human pushes" is suspended for this autonomous run - you commit and push.
- Honor every "Decisions already made" in the plan; do not re-open settled questions (open-source-only/AGPL, surveillance focus, mode3 = single object-only clip, foreground CRF 18/18/23/38, per-mode codec mode0/1=H.264 + mode2/3=AV1 + no H.265, ONNX over torch, modes-behind-presets, rule-based auto-detect, opt-in-only telemetry, no SaaS).
- M1 hard constraints: keep `from gui.app import app` working, re-export every `gui_module.*` private name, route rebound globals through the `_ForwardingModule` seam, one-way imports, SSE closure binds module-level names, atexit stays in `logging_setup.py`, update PyInstaller hiddenimports.
- M0 gotchas: use `.venv` (not `venv`); **never install the `[plates]` extra** (easyocr clobbers cv2); keep `opencv-contrib-python`; LF line endings (`git add --renormalize .` if CRLF drift appears); validate produced mp4s with **ffprobe, not OpenCV** (AV1 isn't always decodable).
- Keep CI (`.github/workflows/ci.yml`) green. You don't need to wait on CI after each push, but if a later run surfaces a regression, fix it forward.

**Gates (🚦) - do NOT halt the whole run on these.** When you reach a gated item:
- Do everything possible *up to* the gate (wire the signing step, prepare the release checklist + draft release notes, build the unsigned/Linux artifacts, etc.).
- Record it in `docs/BLOCKERS.md` (create the file) with exactly what you need from me and why.
- Skip the gated **action** and keep going with all other work. Specifically: don't buy/obtain certs; don't tag or publish a public release; don't notarize macOS; and **skip M6 (the Rust spike) entirely** - it requires my explicit go-ahead.

**Small ambiguities:** if a detail isn't covered by the plan, make the most reasonable choice consistent with `docs/PLAN-V2.md`, leave an authorship comment explaining it, and keep moving. Only defer to `docs/BLOCKERS.md` for true 🚦 gates or genuinely major product/architecture decisions - don't stall on small stuff.

**When every non-gated task through M5b is complete:**
1. Run `pwsh scripts/run_tests.ps1` once more and confirm green; confirm CI is green.
2. Write a final report: what shipped per milestone, final `app.py` line count + asserted route count, installer download size, total test count, and the full `docs/BLOCKERS.md` list (everything waiting on me - certs, publishing, the M6 go-ahead, any deferred decisions).
3. Then stop.

Start now with TASK 1.2. Work methodically; correctness over speed.

---
