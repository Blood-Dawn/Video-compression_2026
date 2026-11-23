# Cancelled Re-pair Review (November 2026)

**Planner task:** 7.4, "Pentest follow ups", the part on how a cancelled re-pair behaves
**Reviewer:** Victor De Souza Teixeira
**Code reviewed:** `ServerSettingsViewModel.kt`, `ServerSettingsScreen.kt`,
`PairingFlowInstrumentedTest.kt`, `device_tokens.mint_token`
**Method:** reading the code. Nothing here was run on a device or emulator, because the
Android build is not available in the review environment. Every claim marked
"to confirm" needs one check on a phone.

---

## Answer

**A cancelled re-pair leaves the saved pairing untouched.** The server URL and token are
written to storage in exactly one place, `save()`. Typing a new URL or token and pressing
TEST only changes the on-screen draft, so backing out never replaces the working pairing.
`aRejectedTokenShowsAnErrorAndSavesNothing` already covers the rejected-token case.

The review found three smaller problems around that, none reachable without the operator
typing a draft:

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| PR-01 | Push actions use the unsaved draft, not the saved pairing | Low | Open, fix proposed |
| PR-02 | The draft is not reverted on cancel, and `ok` stays true after editing | Low | Open, to confirm on device |
| PR-03 | An abandoned re-pair leaves an unused active device token on the server | Low | Open, operator action |

## PR-01 - Push actions use the unsaved draft

`pairedApi()` says it builds a client "on the SAVED pairing", but it reads
`_state.value.serverUrl` and `_state.value.token`, which are the draft fields. So after a
cancelled re-pair (new URL or token typed, never saved):

* `savePushConfig()` and `testPush()` send the push topic and the push token to the draft
  server, with the draft device token.
* They skip the public-address consent step that `testConnection()` enforces, so a typed
  non-private address receives the request without the warning.
* The `LaunchedEffect(state.serverUrl, state.token)` that calls `loadPushConfig()` re-runs
  on every change to either field while `pushLoaded` is false, so a half-typed token can be
  sent to a half-typed address as the user types.

**Fix proposed.** Keep the saved pairing in separate fields (`savedUrl`, `savedToken`, set by
the load in `init` and by `save()`), build `pairedApi()` from those, and key the
`LaunchedEffect` on them. Add a JVM test: type a draft, call `savePushConfig()`, assert the
fake client was built with the saved credentials.

## PR-02 - The draft survives a cancel, and `ok` is not reset on edit

* `onServerUrlChanged` and `onTokenChanged` do not reset `ok`. After one successful TEST, a
  new token typed over it still shows the green "ok" state until the next TEST finishes.
  SAVE is enabled whenever `!busy`, so a user can save an untested token. This is a design
  choice, but the stale green state is misleading.
* There is no revert path. If the view model outlives the screen (to confirm: how
  `viewModel()` is scoped in the nav graph), returning to the screen shows the draft next
  to the saved pairing that the rest of the app is actually using.

**Fix proposed.** Reset `ok` and `capabilities` in both change handlers, and add a
"discard changes" action that reloads from `TokenStore`.

## PR-03 - An abandoned re-pair leaves an unused token

Re-pairing means creating a new device token on the dashboard. If the user then cancels,
that token stays valid. `mint_token` only sets an expiry when `ttl_days` is given, so with
no expiry it is valid until the operator revokes it. Impact is low (nobody holds the
secret except the person who copied it), but unused tokens widen the "lost phone" surface.

**Action.** Operator revokes unused tokens in the dashboard device list. A later improvement
is a default expiry for new tokens or a "never used" badge in that list.

## What was not covered

* No on-device or emulator run (to confirm items above).
* Server side behavior of the revoked-then-re-paired flow beyond what
  `rePairingReplacesTheOldCredentialsAndBumpsSaveCount` already asserts.
