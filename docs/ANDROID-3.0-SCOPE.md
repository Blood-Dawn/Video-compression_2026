# Android 3.0 dev scope

Written 2026-11-24 alongside the 3.0 dev build of the dashboard. This lists what the Android app gets from that work, what is done, and what is deliberately left out.

## In this pass

| Item | What it does | Status |
| --- | --- | --- |
| Encrypted clips on the phone | New ENCRYPTED chip in the server Library lists .enc clips. Tap one, enter the password or pick a 32 byte key file, and the phone downloads the ciphertext, decrypts it locally and opens it in a video player. | Built. Decryptor unit tested against files written by the desktop encryptor. Not yet run on a device. |
| Server routes for .enc | `GET /api/library/encrypted` and `GET /api/library/enc_file`, confined to the allowed media folders, raw bytes only. | Built and tested on the desktop side. |
| Storage cap notification | When auto-compress stops at its cap, the server records a job of kind `cap` and the phone shows "SVCS storage cap reached" with the server's message. | Built. Shown only while the app process is alive, same limit as job notifications today. |

## Rules the encrypted clip feature follows

- The password and key file never leave the phone. The server only sees a download request for a ciphertext file.
- The decrypted copy lives in the app cache, is handed to a player once through a FileProvider, and is wiped the next time the dialog opens or closes.
- A clip over 200 MB is refused. Android holds the whole ciphertext in memory until the authentication tag is checked.
- A wrong password or a changed file produces no output file.

## Left out on purpose

- Recent Jobs with per-file Play and Encrypt on the phone. The server now returns output files per job, but the phone Home screen has no jobs list yet.
- Encrypting a clip from the phone.
- Closed-app delivery of notifications. That still needs a push transport (ntfy or UnifiedPush) and is tracked in the standalone compressor roadmap.
- Profile import and export. The dashboard owns profiles.

## Open verification

- Run the debug build on a device or emulator and open a real clip end to end.
- TalkBack pass on the new dialog.
- Pairing and security test against the desktop server (see the security test notes).
