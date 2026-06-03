# SVCS v2 — Blockers & Owner Actions

This file tracks items the autonomous build could not complete on its own —
hard gates (🚦) that need the owner, and anything that needs a decision,
credential, or environment the agent doesn't have. The agent does everything
possible up to each gate, records exactly what's needed here, and keeps going.

Author: Bloodawn (KheivenD), 2026-06-02 (autonomous v2 build).

---

## Open items

_(none yet — updated as the run reaches gated tasks)_

---

## Gates known in advance (from the master plan)

These are expected and will be filled in with concrete artifacts/instructions
as the run reaches them:

- **🚦 Code-signing certs (M5b.1 / 5b.3)** — Windows EV cert (~$300–600/yr) and
  Apple Developer cert ($99/yr). The signing *step* will be wired into the build;
  the owner must obtain the certs. Investigate SignPath.io's free OSS program for
  Windows first.
- **🚦 Publishing a public release / tagging a beta (TASK 5.4, 5b.*)** — the agent
  prepares the installer, checksums, release checklist, and draft notes; the
  **owner** tags and publishes the GitHub Release.
- **🚦 macOS .dmg notarization (5b.3)** — needs the Apple cert; deferred unless the
  owner provides it. Linux AppImage (5b.2) is done first (no cert needed).
- **🚦 Rust encoder spike (M6)** — explicitly out of scope for this run; needs the
  owner's go-ahead. Skipped entirely.
