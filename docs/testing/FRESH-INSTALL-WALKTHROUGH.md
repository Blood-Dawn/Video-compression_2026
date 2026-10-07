# Fresh-Install Walkthrough (planner 3.11)

**Goal:** Install SVCS the way a stranger would, get through first-run Setup,
and compress one video, **without opening the source code or asking a
teammate**. Write down every moment you were confused, stuck, or annoyed.
Then file the worst three.

**Who:** Everyone on the team does this separately. Your notes are only useful
if they are YOUR first impressions, so do not compare notes until you are done.

**Time:** About 30 to 45 minutes.

---

## How to use this file

1. Copy this file to `docs/testing/walkthroughs/<date>-<your-first-name>.md`
   (for example `2026-10-05-victor.md`).
2. Fill it in **while** you go, not afterward. Friction is easy to forget
   once you have worked around it.
3. Commit your copy and open a PR titled `docs(testing): 3.11 walkthrough (<name>)`.

## Rules

* **No source code.** Do not open the repo in an editor, do not read `.py` or
  `.js` files, do not run `git`. Use only what a user gets: the README on
  GitHub, the Releases page, the installer, and the app itself.
* **Use a machine or account that has never had SVCS on it.** A fresh Windows
  user account works if you do not have a spare PC. If you already had SVCS
  installed, uninstall it first and delete its app-data folder, and note that
  you did.
* **Do not ask teammates for help.** If you get stuck, write down where, then
  try to get unstuck the way a user would (search, re-read the page). If you
  truly cannot continue, that is your number one finding.
* **Time each section.** Rough minutes are fine.

---

## 0. Setup

| Question | Answer |
|----------|--------|
| Date | |
| Windows version (Settings > System > About) | |
| Fresh machine or fresh user account? | |
| Had SVCS installed before? If yes, how did you clean it up? | |
| Video file you will compress (name, length, size in MB) | |

Tip: pick a 30 to 60 second clip from a phone or a webcam pointed at a mostly
still room. A clip with some movement and a lot of stillness shows off what
SVCS does.

---

## 1. Find and download (start the timer)

Start at the GitHub repo page, as if a friend just sent you the link.

- [ ] Could you tell what SVCS is within 30 seconds of reading the README?
- [ ] Could you find how to download it without scrolling around?
- [ ] Did you use the PowerShell `irm ... | iex` command or the `.exe` from Releases? Why that one?
- [ ] Did you follow the "verify the checksum" advice? Was it clear how?
- [ ] Click the "Full options" install link in the README. Did it work?

**Minutes for this section:**

**Friction notes:**

---

## 2. Install

- [ ] Did Windows SmartScreen or your antivirus warn you? What exactly did it say?
- [ ] Did you know it was safe to click "More info > Run anyway"? Where did you learn that?
- [ ] Were any installer screens or options confusing? (Write down the exact wording.)
- [ ] Did the installer finish without errors?
- [ ] Could you find SVCS in the Start menu afterward?

**Minutes for this section:**

**Friction notes:**

---

## 3. First launch and first-run Setup

- [ ] Did the dashboard open in your browser by itself? If not, how did you find it?
- [ ] Did a terminal/console window appear? Did you know whether to close it?
- [ ] Was it obvious that you were on a Setup screen and what it wanted from you?
- [ ] Choosing the output (destination) folder: was it clear what that folder is for?
- [ ] Was there anything you had to type that you did not understand?
- [ ] Usage-stats / privacy prompt: did you understand what you were agreeing to?
- [ ] After Setup, did you know what to do next?

**Minutes for this section:**

**Friction notes:**

---

## 4. Compress one video

- [ ] How did you get your video into the app (upload, file path, library)? Was the way to do it obvious?
- [ ] Preset / "what is the camera watching" choice: did you understand the options?
- [ ] Did you press Start with confidence, or guess?
- [ ] While it ran: could you tell it was working and roughly how long it would take?
- [ ] When it finished: did the app tell you clearly that it was done?
- [ ] Could you find the compressed output file on disk?
- [ ] Did the output play in a normal video player?
- [ ] Did the app show how much space you saved? Did the number make sense?

**Original size (MB):**
**Compressed size (MB):**
**Minutes for this section:**

**Friction notes:**

---

## 5. Close and reopen

- [ ] Close SVCS. Was it clear how to fully quit it?
- [ ] Reopen it. Did it remember your Setup choices, or ask again?

**Friction notes:**

---

## 6. Full friction log

Every confusing, slow, or broken moment, in order. Small ones count. One row
per moment.

| # | Section | What happened (exact wording on screen if any) | What you expected instead | How bad? (1 = annoying, 2 = slowed me down, 3 = blocked me) |
|---|---------|-----------------------------------------------|---------------------------|-------------|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

**Total time, download to compressed file:** minutes

---

## 7. Worst three (file these)

Pick the three rows above that would make a real user give up first. For
each, open a GitHub issue titled `[3.11] <short description>` and paste the
link here.

| Rank | Friction # | One-line summary | Issue link |
|------|-----------|------------------|------------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

---

## 8. Sign-off

- [ ] I did not open source code or ask a teammate during this walkthrough.
- [ ] My worst three are filed as issues.

Name:
