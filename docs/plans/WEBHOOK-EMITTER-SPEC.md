# Webhook Emitter Specification (`utils/event_webhook.py`)

**Planner task:** 3.9, "Read `push_notify.is_safe_push_url` and specify the webhook emitter"
**Owner:** Victor De Souza Teixeira
**Date:** October 2, 2026
**Implements:** D4 in `docs/plans/DESKTOP-ZONES-EVENTS-PLAN.md`
**Feeds:** 3.10 (test harness), 4.9 (implementation), 4.10 (config UI), 5.10 (URL rejection tests)

---

## 1. Purpose

When a behavior event is recorded (a line crossing, loitering), SVCS can
already push a short human-readable notification to a self-hosted ntfy topic
(`utils/push_notify.py`). The webhook emitter is the machine-readable sibling:
it POSTs the event itself, as JSON, to a URL the operator chooses, so another
system (a VMS, Home Assistant, Node-RED, a SIEM) can react to it.

The webhook is an outbound request the server makes on behalf of a
configuration value. That makes it a Server-Side Request Forgery (SSRF)
surface, and most of this spec is about keeping it from becoming one.

## 2. What I found reading `is_safe_push_url`

`push_notify.is_safe_push_url(url)` already solves almost exactly the problem
the webhook has. It:

| Check | Behavior |
|---|---|
| Scheme | Only `http` and `https`. `file:`, `ftp:`, `gopher:` and no scheme are refused. |
| Credentials in URL | `http://user:pass@host/...` refused. Secrets belong in a header. |
| Metadata hostnames | `metadata`, `metadata.google.internal`, `metadata.goog`, `instance-data`, `instance-data.ec2.internal` refused by name. |
| Resolution | Hostnames are resolved and **every** answer is checked, so a friendly name pointing at `169.254.169.254` is refused. |
| Refused addresses | Link-local (`169.254.0.0/16`, `fe80::/10`), multicast, unspecified, reserved, plus the named literals `100.100.100.100` (Alibaba) and `fd00:ec2::254` (AWS IMDS v6). IPv4-mapped IPv6 is unwrapped first. |
| Allowed addresses | Loopback, RFC1918 / unique-local, and public hosts. A self-hosted receiver legitimately lives on any of these. |
| Length | Over 2048 characters refused. |
| Path | A URL with no path (`http://host/`) is refused, because an ntfy URL with no topic is meaningless. |

Sending side (`_post`): the URL is re-validated at send time, redirects are
never followed (`_NoRedirect`), header values are stripped of control
characters, and the body is capped at 4 KB.

These are the right rules for a webhook too, with two differences:

1. **The "no path" rule does not fit.** `http://192.168.1.20:9000/` is a
   perfectly normal webhook receiver. The webhook must not require a path.
2. **The error messages say "topic URL".** Shown in a webhook form they
   would confuse the operator.

## 3. Decision: share the guard, do not copy it

Copying the guard into a second file would mean two lists of metadata
addresses that drift apart the first time someone adds one. Instead, 4.9
makes one small, behavior-preserving refactor in `push_notify.py`:

```python
def check_outbound_url(url, *, require_path: bool, label: str,
                       credential_field: str) -> "tuple[bool, str]":
    """The shared SSRF guard. `label` and `credential_field` are used in messages."""
    ...  # the current body of is_safe_push_url, parameterised for both

def is_safe_push_url(url) -> "tuple[bool, str]":
    return check_outbound_url(url, require_path=True, label="topic",
                              credential_field="token field")
```

`event_webhook.py` then defines:

```python
def is_safe_webhook_url(url) -> "tuple[bool, str]":
    return push_notify.check_outbound_url(url, require_path=False, label="webhook",
                                          credential_field="secret field")
```

Every message that names the feature has to come from these two parameters,
not only the ones that say "topic URL". Today that includes "credentials in
the URL are not allowed, use the token field" and "topic host does not
resolve". Left as is, a webhook URL with `user:pass@` in it would tell the
operator to fill in a push token the webhook form does not have.

**Acceptance for the refactor:** `tests/test_push_notify.py` passes
unchanged. Every existing push error message stays byte-for-byte the same,
because the parametrised tests match on fragments like `"no topic"`.

The `_NoRedirect` handler and `_header_safe` helper are reused the same way
(imported, not copied).

## 4. Configuration

Stored in its own state file, `webhook_config.json`, resolved through
`paths.state_file()` the same way `push_config.json` is, and written with
mode `0o600`. It does **not** go in `gui_state.json`, whose contract is
"paths, no secrets".

```json
{
  "enabled": false,
  "url": "",
  "secret": "",
  "saved_at": 1759420000.0
}
```

| Field | Default | Rule |
|---|---|---|
| `enabled` | `false` | Off by default. A stock install never opens this socket. |
| `url` | `""` | Validated with `is_safe_webhook_url` on save. Required only when turning `enabled` on, so an operator can switch it off without clearing the URL. |
| `secret` | `""` | Optional HMAC signing key (section 6). **Write-only**: never returned by any API. |

Functions mirror `push_notify` so the two modules read alike:
`config_path()`, `load_config()` (never raises, unreadable means off),
`public_config()` (replaces `secret` with `has_secret: bool`), and
`save_config(data) -> (ok, error, public_config)`. Omitting the `secret` key
keeps the stored one; sending `"secret": ""` clears it.

## 5. Payload

One POST per `append_events` call, not one per event, so an event burst is one
request instead of dozens.

```json
{
  "source": "svcs",
  "schema": 1,
  "sent_at": "2026-10-02T18:04:11Z",
  "camera_id": "cam_00",
  "events": [
    {"kind": "line_crossing", "camera_id": "cam_00", "t": 12.5,
     "wall_time": "2026-10-02T18:04:10+00:00", "track_id": 3,
     "label": "person", "geometry_id": "gate", "direction": "right"}
  ],
  "dropped": 0
}
```

Rules:

* **Field allowlist, not a copy.** Each event is rebuilt from only these keys:
  `kind`, `camera_id`, `t`, `wall_time`, `track_id`, `label`, `geometry_id`,
  `direction`, `dwell_s`. Anything else a future detector attaches (plate
  text, crops, file paths, stream URLs) is dropped before it leaves the
  machine.

  **Scope of this filter:** it protects outbound delivery only. It does
  **not** protect `events.jsonl`. `append_events` currently persists every
  key it is given (`rec = dict(ev)`), so the "no PII beyond the class label"
  rule in `event_log.py` holds today only because no current producer sends
  extra keys. Recommended follow-up, separate from 4.9: move this allowlist
  into `event_log.py` as a shared `EVENT_FIELDS` constant, apply it in
  `append_events` before writing, and have both `push_notify` and
  `event_webhook` import it, so disk and network share one definition. Until
  that lands it should be recorded in `docs/plans/BLOCKERS.md`.
* **At most 20 events per POST.** Extra events are counted in `dropped`
  rather than sent, and are still in `events.jsonl` on disk.
* **Body capped at 64 KB.** Twenty allowlisted events are far below this; the
  cap is a backstop, and an oversized body is dropped with a log line, never
  truncated into invalid JSON.
* `schema` lets a receiver handle a future format change.

## 6. Request shape and signing

```
POST <url>
Content-Type: application/json
User-Agent: SVCS-Webhook
X-SVCS-Delivery: <uuid4>
X-SVCS-Timestamp: <unix seconds>
X-SVCS-Signature: sha256=<hex>        (only when a secret is set)
```

The signature is `HMAC-SHA256(secret, timestamp + "." + body)`. Signing the
timestamp with the body lets a receiver reject replays (for example, anything
older than five minutes). This is the same scheme GitHub and Stripe use, so
receivers already know how to verify it. Use `hmac.compare_digest` in any
example verifier we document.

Why HMAC instead of a bearer token: a bearer token proves nothing about the
body, and anyone who captures one request can forge new ones. An HMAC
signature proves the body came from this SVCS install and was not altered,
which matters because these events can trigger actions downstream.

## 7. Delivery behavior

Copied in spirit from `push_notify`, tightened where D4 asks:

* **Fire and forget.** `emit_events()` builds the payload and puts it on a
  bounded queue (64 items) served by one daemon thread. It returns
  immediately. A full queue drops the delivery with a warning; it never
  blocks.
* **2 second timeout** (D4), versus push's 3 seconds.
* **No retries.** The event is already durable in `events.jsonl`; a receiver
  that was down can catch up from `/api/events/recent`. Retries would add
  state and a second way to fill the queue.
* **Redirects refused**, reported as `HTTP 3xx redirect refused`.
* **Re-validate the URL at send time**, not only at save time, so a DNS record
  that changed since saving is caught.
* Success is any 2xx. Everything else is one `log.warning` line with the
  status or error, and nothing else happens.
* `flush(timeout)` test helper, same contract as `push_notify.flush`.

## 8. Hook point

In `utils/event_log.append_events`, directly after the existing push call and
in its **own** `try/except`, so a failure in one notifier cannot skip the
other. The import sits **inside** that block: an `ImportError` or any
exception raised while `event_webhook` (or something it imports) loads must
be swallowed just like a delivery failure, or it would escape
`append_events` and reach the encode loop.

```python
try:
    try:
        from utils.event_webhook import emit_events as _emit
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.event_webhook import emit_events as _emit
    _emit(events, camera_id=camera_id)
except Exception:  # noqa: BLE001 - best effort, always
    pass
```

The existing push hook just above it has the same shape (its import is
outside the `try`). 4.9 should move that import inside its `try` as well, so
both notifiers follow the same rule.

When the webhook is disabled the cost is one config read, the same as push.

## 9. API routes (for 4.10)

A new `routes/webhook_bp.py`, registered like `push_bp`. It inherits the same
dashboard auth policy (SEC-010, Basic-Auth on a LAN bind) and the same-origin
CSRF guard (SEC-001, `gui/csrf.py`) that every other `/api/*` POST gets:

| Route | Behavior |
|---|---|
| `GET /api/webhook/config` | `public_config()`; the secret is never echoed. |
| `POST /api/webhook/config` | `save_config()`; 400 with the reason on a refused URL. |
| `POST /api/webhook/test` | Sends one synthetic event synchronously and returns `{"ok", "detail"}`. Accepts an unsaved `url` so an operator can prove it works first. A failed test is a 200 with `ok: false`, matching `/api/push/test`. |

**Test-route caution:** `/api/webhook/test` makes the server send a request to
a URL supplied in the request. That is only acceptable because (a) it goes
through the same guard, (b) the route sits behind the dashboard auth
policy and the CSRF guard, so a random web page cannot drive it, and (c) the response returns only a status line, never the
receiver's response body. The body must never be echoed, or the route becomes
a way to read internal pages.

## 10. Known limitation: DNS rebinding

The guard resolves the hostname, and then `urllib` resolves it **again** when
it connects. A hostile DNS server can answer with a safe address the first
time and `169.254.169.254` the second. `push_notify` has the same gap today.

Proposed fix, for 4.9 or a follow-up: resolve once, validate, then connect to
that exact IP while sending the original hostname in the `Host` header (and as
the TLS SNI name for `https`). If that turns out to be too invasive for 4.9,
it gets a severity-rated entry in `docs/plans/BLOCKERS.md` instead of being
left unwritten. Practical risk is low, because exploiting it needs both
dashboard access to set the URL and a DNS server the attacker controls, but
it should be on record.

## 11. Test plan (handed to 3.10 and 5.10)

Harness: a throwaway `http.server.HTTPServer` on `127.0.0.1:0`, the same
`_Recorder` pattern as `tests/test_push_notify.py`, with `config_path()`
monkeypatched to a temp directory so a developer's real webhook is never hit.

| # | Case | Expect |
|---|---|---|
| 1 | Fresh install | `enabled` is false; `emit_events` opens no socket |
| 2 | Enabled, one event | Receiver gets one POST, JSON parses, `schema == 1` |
| 3 | Event with extra keys (`plate_text`, `path`) | Those keys are absent from the body |
| 4 | 25 events in one call | 20 sent, `dropped == 5` |
| 5 | Secret set | Signature header verifies with the secret; tampered body fails |
| 6 | No secret | No signature header |
| 7 | Secret never echoed | `GET` config shows `has_secret: true`, no `secret` key |
| 8 | Receiver returns 302 | Not followed, logged as redirect refused |
| 9a | Receiver hangs, caller side | `emit_events` returns immediately (well under the timeout), proving the caller never waits on the socket |
| 9b | Receiver hangs, worker side | `flush(timeout=4)` returns `True`: the worker gave up after its 2 second socket timeout and drained. A worker with no timeout stays stuck and this fails |
| 10 | Receiver down | Warning logged, nothing raised |
| 11 | Queue full | Delivery dropped, `emit_events` returns immediately |
| 12 | Allowed URLs | loopback, `192.168.x.x`, `10.x`, `172.16.x`, `[::1]`, and a URL with no path |
| 13 | Refused URLs | `169.254.169.254`, `100.100.100.100`, `[fd00:ec2::254]`, `[::ffff:169.254.169.254]`, `metadata.google.internal`, `file:`, `ftp:`, `gopher:`, `user:pass@host`, empty |
| 14 | Hostname resolving to metadata | Refused (monkeypatched `getaddrinfo`) |
| 15 | Push refactor | `tests/test_push_notify.py` passes unchanged |
| 16 | Push and webhook both on | A webhook failure does not stop the push, and the reverse |

## 12. Out of scope

* Retries, delivery history, or a dead-letter queue.
* Job-completion webhooks (push covers those for humans; can be added later
  behind an `on_jobs` flag if a sponsor use case appears).
* Multiple webhook URLs.
* mTLS or custom CA bundles for the receiver.
