# SVCS - Manual security verification (run this yourself on the real build)

Run this AFTER Claude Code finishes the security-audit round and you have rebuilt the installer. Automated tests prove the code rejects attack inputs; this checklist proves the two highest-consequence failure modes are actually safe on the real, frozen app, where only a human can confirm them:

- **A. Network exposure** - "anyone on the same wifi can open my camera dashboard."
- **B. Delete-original** - "the app deleted the only copy of my footage."

Use THROWAWAY copies of videos for everything in section B. Record PASS/FAIL in the table at the bottom. Ship only if both Critical checks pass.

---

## A. Network exposure and auth

Background: the installed desktop app should bind to `127.0.0.1` (localhost only) - the launcher was fixed to do this when frozen. LAN exposure (`0.0.0.0`) is only for the server/Docker scenario, and that path must require a password. Verify both.

**A1 (Critical) - the desktop app is NOT reachable from another device.**
1. Launch SVCS normally. On the same PC, in the dashboard URL bar it should be `http://127.0.0.1:5000` (or similar localhost address), not your LAN IP.
2. Find your PC's LAN IP: open PowerShell and run `ipconfig` - note the IPv4 address (e.g. `192.168.1.50`).
3. From a DIFFERENT device on the same wifi (your phone, a second laptop), browse to `http://<that-IP>:5000`.
   - PASS: it does NOT load (connection refused / times out). The desktop app is localhost-only.
   - FAIL: the dashboard opens with no password. Stop and fix before sharing the build.

**A2 (Critical, only if you use server/LAN mode) - auth is enforced when bound to the network.**
If you ever run SVCS bound to `0.0.0.0` (server scenario, Docker, or "share with team"):
1. From another device, browse to `http://<PC-IP>:5000`.
   - PASS: you are prompted for a username/password (HTTP basic auth), and a WRONG password is rejected; only the correct credential gets in.
   - FAIL: the dashboard opens with no prompt, or any password works. Do not expose it.
2. Confirm the credential is not a blank/default (you set it, it is not "admin/admin" or empty).

**A3 - if you do not need LAN access, keep it localhost.** The safest default for a single-PC install is localhost-only (A1). Only turn on `0.0.0.0` deliberately, behind A2.

---

## B. Delete-original-after-compress (use throwaway copies)

The dangerous failure is deleting an original when the compress did NOT actually succeed. Test the failure path on purpose.

**B0 - default is keep.** With a fresh setup, the "Delete original after compress" toggle in the AUTO-COMPRESS tab should be OFF by default.

**B1 - keep mode leaves originals alone.**
1. Make a throwaway folder, copy 2-3 clips into it.
2. Leave delete OFF, run auto-compress (or "Compress existing now") on it.
   - PASS: compressed copies appear under the `compressed/` output, and the ORIGINALS are all still in the source folder.

**B2 (Critical) - failure must NOT delete the original.** This is the most important check.
1. Throwaway folder again. Put in it: one good clip, plus a deliberately BROKEN file - e.g. copy a .txt and rename it `fake.mp4`, and/or truncate a real clip (copy only the first few KB).
2. Turn the delete-after-compress toggle ON (read the warning it shows).
3. Run it.
   - PASS: the good clip compresses and (per your choice) its original may be removed AFTER a valid compressed file exists; the BROKEN file is NOT deleted (it could not be compressed), and is still sitting in the folder.
   - FAIL: the broken/unconvertible file got deleted even though no valid compressed output was produced. That is data loss - stop and fix.
4. Bonus: start compressing a large clip and kill the app (close the window / end task) mid-encode. Relaunch. The original of the interrupted file must still be there (no output existed, so nothing should have been deleted).

**B3 - it only deletes inside the watched folder.**
1. Confirm nothing under the `compressed/` output folder ever gets deleted (those are your results).
2. If you can, point auto-compress at a folder that contains a shortcut/symlink to a file OUTSIDE it; confirm only real files inside the watched folder are ever touched.

---

## C. Quick high-value spot-checks (5 minutes)

- **C1 Path confinement:** in Library or Setup, try to browse/enter `C:\Windows\System32` or a path with `..\..\` and confirm you cannot read system files through the app (it should reject or stay confined to allowed folders).
- **C2 XSS in filenames:** rename a throwaway clip to something like `test<script>alert(1)</script>.mp4`, then view the Library. PASS: the name shows as literal text; no popup, no broken page.
- **C3 No secrets in logs:** encrypt a file with a password, then open the SVCS log (the path is shown in the Help overlay / your app-data SVCS folder, `svcs.log`) and the console. PASS: your password and the file contents are NOT anywhere in the log.
- **C4 Malformed input does not crash it:** drop a 0-byte file named `x.mp4` and a random non-video renamed to `.mp4` into the upload/watch path. PASS: the app shows an error for them and keeps running (no hang, no server crash).
- **C5 Installer trust:** the unsigned installer triggers SmartScreen ("More info -> Run anyway") - expected until you sign it. Only run the `irm ... | iex` terminal installer from your own official repo URL over https, never a copy someone pasted you.

---

## Result log

| Check | Result (PASS/FAIL) | Notes |
|---|---|---|
| A1 desktop not reachable from another device | | |
| A2 auth enforced in server/LAN mode | | (n/a if you never use 0.0.0.0) |
| B0 delete toggle defaults OFF | | |
| B1 keep-mode leaves originals | | |
| B2 failure does NOT delete original | | CRITICAL |
| B3 only deletes inside watched folder | | |
| C1 path confinement | | |
| C2 no XSS via filename | | |
| C3 no secrets in logs | | |
| C4 malformed input handled | | |

**Ship rule:** do not hand the build to a teammate or sponsor unless A1 (or A2 if you expose it) and B2 both PASS. Those two are the difference between "a rough beta" and "it leaked a camera feed / ate someone's footage."
