# Push Endpoint Registration - Security Review (October 2026)

**Planner task:** 6.10, "Security review of the new endpoint registration"
**Reviewer:** Victor De Souza Teixeira
**Code reviewed:** planner 6.9 (`/api/push/endpoint`, `device_tokens.push_endpoint`,
`auth.current_device_id`), PR #31
**Outcome required:** confirmation that one device cannot register or read
another device's endpoint.

---

## Answer

**Confirmed.** One device cannot register, read, or clear another device's
push endpoint. This is held by the design, not by a check that could be
forgotten: the route has **no input that names a device**. It acts only on
the device whose token authenticated the request.

23 attack tests in `tests/test_push_endpoint_isolation.py` back this up, each
written as device B going after device A's endpoint. All 23 were refused. To
show the tests have teeth, two realistic bugs were planted and then removed:

| Planted bug | Tests that caught it |
|-------------|----------------------|
| The route trusts a device `id` sent in the request body | 1 of 23 (the body-field test for `id`) |
| The store rewrite forgets to save endpoints | 14 of 23 |

## Why it holds

An endpoint can only change through `PUT` or `DELETE /api/push/endpoint`, and
both do the same three things:

1. **Identify the device from its credential only.** The auth guard verifies
   the Bearer token and records that token's id on `flask.g`
   (`auth.current_device_id()`). Nothing in the URL, query string, headers, or
   body is ever read as a device id.
2. **Refuse requests with no device identity.** A password (Basic) session is
   the operator, not a device, so it gets a 403 instead of the server picking a
   device for it.
3. **Write one record, under the store lock.** `set_push_endpoint(token_id, ...)`
   is a read-modify-write under the same lock as minting, revoking, and
   verifying, so concurrent writers serialize and cannot overwrite each other.

Reading works the same way: `GET` returns the caller's own endpoint only. The
operator's device list (password-only) shows `has_push_endpoint: true/false`,
never the URL.

## What was attacked

| # | Attack (device B against device A) | Result |
|---|------------------------------------|--------|
| 1 | `GET` the endpoint while A has one registered | B sees only its own (empty) endpoint |
| 2 | Name A in the query string: `?id=`, `?device_id=`, `?token_id=`, `?device=`, `?for=` | Ignored, A's URL never returned |
| 3 | List devices to discover A | 403, the list is password-only |
| 4 | Look for A's URL in every response B can reach | Never present |
| 5 | Name A in the body: `id`, `device_id`, `token_id`, `device`, `owner` | The write lands on **B's** record, A unchanged |
| 6 | Name A in the query string on a write | A unchanged |
| 7 | `DELETE` with A's id in the query string | A unchanged |
| 8 | Guess a per-device path, `/api/push/endpoint/<A's id>` | 404, no such route |
| 9 | Send a password request right after A's request, hoping A's identity carries over | 403, `flask.g` is per request |
| 10 | Forged Bearer values (bare prefix, well-formed but never issued, two tokens in one header) | 401 |
| 11 | A's token after revocation | 401, and revocation already cleared the endpoint |
| 12 | Authenticated requests rewriting the store (the `last_used_at` stamp) | Every device's endpoint survives |
| 13 | 2 x 40 interleaved writes from A and B on two threads | No errors, each device ends with its own endpoint |

## Residual risks and notes for week 8

None of these lets one device reach another's endpoint. They are what the
next stage, the server-side fan-out, has to get right.

* **A stolen token can still point its own alerts somewhere.** The thief can
  register an endpoint for the stolen device and receive that device's future
  alerts until it is revoked. That is inherent to any per-device credential.
  It is bounded by revocation (which clears the endpoint) and is visible to
  the operator through `has_push_endpoint` in the device list.
* **The fan-out must re-validate at send time.** The URL is checked when it is
  registered, but DNS can change afterward. Week 8 should send through the same
  guard and the same no-redirect opener the webhook uses, re-checking the URL
  on every send. The shared DNS-rebinding gap is already recorded in
  `docs/plans/BLOCKERS.md`.
* **Never log the endpoint.** A UnifiedPush endpoint is a capability: whoever
  has the URL can wake the phone. Log the device id, never the URL, and keep
  payloads to the push rules (event kind, camera id, class label; no plate
  text, no paths).
* **Writes are not rate limited.** An authenticated device can rewrite its own
  endpoint as often as it likes, and each write rewrites the token file. The
  file is small (at most 50 tokens, endpoint URLs capped at 2048 characters by
  the guard), so this is noted rather than filed.
* **Localhost with no auth configured.** No request carries a device identity
  there, so the route always answers 403. Phones only pair over a LAN bind,
  which requires auth, so this matches how the feature is used.

## Summary for the progress report

6.10 confirms that one device cannot register or read another device's push
endpoint. The route takes no device id as input and acts only on the token
that authenticated the request, so the property holds by construction. 23
adversarial tests cover it, and planting two realistic bugs showed the tests
catch them. Five notes are handed to the week 8 fan-out work, chief among them
re-validating each endpoint at send time and never logging endpoint URLs.
