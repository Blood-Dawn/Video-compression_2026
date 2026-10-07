# Native UnifiedPush for SVCS Mobile: registration flow and design

Planner task 6.2, written 2026-10-07. This is the design that planner 7.b (phone client) and 7.c (server fan-out) build from. No code ships with it.

## Summary

SVCS can stop depending on the separate ntfy app for closed-app alerts. The phone registers with whatever UnifiedPush distributor the user has installed, gets back a push endpoint, and hands that endpoint to the SVCS server. The server then sends alerts straight to the endpoint.

Two facts from the research change the shape of the work, and both are easy to miss:

1. **Payloads must be encrypted.** Current UnifiedPush follows Web Push, so the server has to encrypt each message to the phone (RFC 8291) and should sign its requests with a VAPID key (RFC 8292). Today's `PUT /api/push/endpoint` stores only a URL. It has to start storing the phone's public key and auth secret as well, and the server needs a small Web Push sender. The ntfy path we ship now sends plain text and needs none of this.
2. **The standard advice conflicts with our network model.** UnifiedPush tells application servers to refuse endpoints that resolve to private addresses. SVCS deliberately allows them, because the common setup is a self-hosted ntfy distributor on the same LAN. That is a decision for the owner, and section 6 lays out a recommendation.

One claim could not be confirmed from documentation and needs a half-day spike before 7.c is sized: whether a self-hosted ntfy server accepts an encrypted, VAPID-signed Web Push request from a third-party application server and relays it intact. See section 9.

## 1. What exists today

The closed-app path in `docs/architecture/PUSH-NOTIFICATIONS.md` works like this. The operator runs an ntfy server and picks a topic. The SVCS server POSTs plain text to that topic URL through `src/utils/push_notify.py`, which has its own SSRF guard (private and LAN addresses allowed, metadata addresses refused, no redirects, DNS pinned for the send). The phone runs the separate ntfy app, subscribed to the same topic. One topic serves every phone.

Planner 6.9 and 6.10 already added the first half of per-device push:

* `PUT`, `GET` and `DELETE /api/push/endpoint` in `src/gui/routes/push_bp.py`. The route takes no device id. It acts on the device whose Bearer token authenticated the request, and a dashboard password session gets a 403.
* `device_tokens.set_push_endpoint` and `get_push_endpoint` store one URL per device token, validated by the shared `check_outbound_url` guard (http and https only, no embedded credentials, 2048 characters at most).
* Victor's review (`docs/security/PUSH-ENDPOINT-REVIEW-2026-10.md`) confirmed one device cannot read or write another's endpoint, and listed five notes for the fan-out. This design adopts all five.

What is missing is everything on the phone, the public key and auth secret on the server, the encryption, and the sender.

## 2. How UnifiedPush works

Four parties take part. The **application** is SVCS Mobile. The **distributor** is a separate app the user installs (ntfy, NextPush, Sunup and others); it keeps one connection open to a **push server** and wakes applications when something arrives. The **application server** is the SVCS desktop server. Applications talk to the distributor on the phone; the application server talks to the push server over HTTP.

On Android the application side uses the UnifiedPush connector library (`org.unifiedpush.android:connector`). The library wraps the broadcast protocol defined in the Android specification, version AND_3.1.0 at the time of writing, and handles key generation and message decryption for the app. The pieces SVCS needs:

* **Discovery.** `UnifiedPush.getDistributors(context)` lists installed distributors. `tryUseCurrentOrDefaultDistributor(activity, callback)` uses the saved one or opens the distributor's link activity through the `unifiedpush://link` deep link; `tryPickDistributor(activity, callback)` forces the picker. `saveDistributor` remembers the choice and `getAckDistributor` returns it only if that distributor has answered.
* **Registration.** `UnifiedPush.register(context, instance, messageForDistributor, vapid)` asks the saved distributor for an endpoint. Underneath, the library sends a `REGISTER` broadcast carrying a random connection token (a UUID, at most 100 bytes) that identifies this registration in every later callback. An `instance` string lets one app hold several registrations.
* **Callbacks.** The app declares a non-exported service that extends `PushService` and listens for `org.unifiedpush.android.connector.PUSH_EVENT`. It implements `onNewEndpoint(endpoint, instance)`, `onMessage(message, instance)`, `onRegistrationFailed(reason, instance)` and `onUnregistered(instance)`, and may override `onTempUnavailable(instance)`.
* **The endpoint.** A `PushEndpoint` carries the URL, a Web Push public key set (the P-256 public key and the auth secret the library generated for this registration), and a `temporary` flag that is true while a fallback distributor stands in for the primary one.
* **Failure reasons.** The spec names `INTERNAL_ERROR`, `NETWORK`, `ACTION_REQUIRED` and `VAPID_REQUIRED`.
* **Delivery.** The distributor forwards the raw encrypted POST body (1 to 4096 bytes, so roughly 3993 bytes of cleartext) to the library, which decrypts it and calls `onMessage`. The distributor must give the app a short foreground window (5 seconds in the spec) to react.
* **Removal.** `unregister(context, instance)` ends one registration and drops the distributor when the last instance goes. A distributor can also end a registration itself, for example after 30 days of inactivity or when its push server goes away, and it tells the app through `onUnregistered`.

Application servers are expected to follow Web Push: encrypt with `aes128gcm` (RFC 8291), authenticate with VAPID (RFC 8292), validate a new registration before trusting it so the server cannot be used to flood a third party, and reject endpoints that resolve to private ranges.

## 3. Registration flow for SVCS

The flow assumes the phone is already paired, so it holds a device token and a server URL (`TokenStore`).

**First time, user opt-in.** Under MORE, in the existing PHONE ALERTS area, add a "Native push" switch beside the ntfy remote control. Turning it on starts the sequence below. Nothing runs, and no distributor is contacted, while it is off.

1. **Find a distributor.** Call `getDistributors`. If the list is empty, show a short help card ("Install a UnifiedPush distributor such as ntfy") with a link, and leave the existing ntfy path untouched. If there is exactly one or a saved one, call `tryUseCurrentOrDefaultDistributor`. If there are several and none is saved, `tryPickDistributor` shows the picker.
2. **Ask the server for its VAPID public key.** A new authenticated `GET /api/push/vapid` returns the server's public key (87 base64url characters). Fetch it before registering so the request can include it. The spec makes VAPID optional for the app, but some push servers refuse to hand out endpoints without it, and they answer with `VAPID_REQUIRED`.
3. **Register.** `UnifiedPush.register(context, instance = "svcs", vapid = key)`. The call returns at once; the result arrives in the service.
4. **Receive the endpoint.** `onNewEndpoint(endpoint, "svcs")` fires. The service launches a short WorkManager job (not a coroutine tied to the service, which may be stopped a moment later) that sends `PUT /api/push/endpoint` with the URL, the public key, and the auth secret, authenticated with the device token. The service never logs the URL.
5. **Server challenge.** The server stores the endpoint as *unconfirmed* and sends one encrypted message through it containing a random confirmation value. When `onMessage` sees a message of type `confirm`, the phone posts that value back with `POST /api/push/endpoint/confirm`. Only confirmed endpoints receive alerts. This is the spec's "validate the registration" step, and it also proves the whole chain works before the user is told it does.
6. **Show state.** The MORE screen shows one of: not set up, waiting for confirmation, active (with the distributor's package name), or needs attention (with the reason).

**Steady state.**

* `onMessage` decodes the payload (a small JSON object, see section 5), builds the notification through the existing `JobNotifier`, and returns quickly. The foreground window is short, and no network call belongs on this path.
* `onNewEndpoint` can fire again at any time (the distributor rotated the endpoint). Repeat step 4. Treat an endpoint with `temporary = true` as usable but expect a replacement, and do not show an error.
* `onRegistrationFailed`: `NETWORK` retries with backoff through WorkManager; `VAPID_REQUIRED` retries once with the key (step 2) if the first attempt went without; `ACTION_REQUIRED` sends the user to the distributor app with an explanation, since only they can fix it; `INTERNAL_ERROR` is surfaced as needs attention.
* `onUnregistered`: send `DELETE /api/push/endpoint`, set the UI to off, and offer to register again.

**Events that must trigger a fresh registration.**

* A new pairing or re-pairing. The server clears a device's endpoint when its token is revoked, and a new token starts with none, so the app must call `register` again whenever `ServerSettingsState.saveCount` changes. This is the same signal the app shell already uses to rebuild its API client.
* The saved distributor is uninstalled (`getAckDistributor` returns null at app start). Show "needs attention" and offer the picker.
* The user turns the switch off: `unregister`, then `DELETE`, then clear the saved distributor.

## 4. Phone side layout

New code goes under `mobile/android/app/src/main/java/org/svcs/mobile/push/`, so it stays apart from the existing ntfy remote control.

* `SvcsPushService` extends `PushService` and holds only the four callbacks. Each one hands off immediately and keeps no state.
* `PushRegistrar` owns the sequence in section 3, so the UI and the service share one code path. It is constructed with the API client and `TokenStore`, which makes it testable without a distributor.
* `TokenStore` gains two small fields: the native push switch and the distributor package name. The endpoint itself should not be stored on the phone at all; it is returned by the library on demand and is a capability (whoever holds it can wake the phone).
* The manifest declares the service with `android:exported="false"` and the `PUSH_EVENT` filter. Package visibility for distributor discovery is handled by the library, but confirm that against the pinned version, since Android 11 and later restrict app queries.
* One new dependency: the connector. The version catalog's header requires Apache-2.0 or MIT licensing and no Google Play Services, so check the connector's license when pinning it, and do **not** add the embedded FCM distributor, which would route alerts through Google and defeat the point.

## 5. Server side changes

All of this belongs to planner 7.c and builds on 6.9.

**Storage.** Each device record gains `push_p256dh`, `push_auth`, and `push_confirmed`. Validate the shapes at registration: the public key is a 65 byte uncompressed P-256 point (87 base64url characters), the auth secret is 16 bytes (22 characters). `set_push_endpoint` takes the new fields and clears all of them together. Revoking a token already clears the endpoint; it must clear the keys too.

**VAPID key.** Generate one P-256 keypair on first use, store it next to `push_config.json` in the state directory with mode `0o600`, and serve only the public half through `GET /api/push/vapid`.

**Sender.** A small new module (suggested name: `webpush`, under `src/utils`) does three jobs: encrypt a payload for one device (RFC 8291, `aes128gcm`), sign a VAPID JWT (ES256, RFC 8292), and POST with `TTL` and `Urgency` headers. The project already depends on `cryptography` (`pyproject.toml` pins `>=48.0.1`), which provides everything needed, so no new dependency is required. The UnifiedPush guidance says to use an existing Web Push library rather than write the protocol by hand. A maintained library such as `pywebpush` is the safer route if the team would rather not own crypto code; the cost is a dependency and its transitive packages, which the F-Droid-style dependency policy in the repo should weigh. Either way, the first test must be the worked example in RFC 8291 appendix A, so the encryption is proven against a published vector.

**Fan-out.** Per event, for every confirmed endpoint: build the payload, encrypt, and send through `push_notify.validate_push_url` and `pin_resolution` with the no-redirect opener, so the address is re-checked at send time and a DNS change after registration cannot redirect an alert. This is the first of Victor's notes. Other rules carried over from his review: never log the endpoint (log the device id), keep payloads to the existing push rules (event kind, camera id, class label, no plate text, no paths), send on the existing bounded worker queue so a slow push server cannot stall an encode, and cap the writes a device can make to its own endpoint.

**Dead endpoints.** A `404` or `410` from the push server means the registration is gone. Clear that device's endpoint and keys, and let the phone's next launch re-register.

**Payload.** A compact JSON object under 1 KB: `{"v": 1, "type": "event" | "job" | "confirm", "title": ..., "body": ..., "camera": ...}`. The version field lets the phone ignore shapes it does not understand instead of crashing on them.

## 6. Decision needed: private-network endpoints

The UnifiedPush guidance for application servers says to reject endpoints that resolve to RFC 1918 or RFC 4193 addresses. The reasoning is sound for a public service: an attacker registers an internal address and makes the server probe the internal network.

SVCS is a self-hosted tool whose most common distributor setup is ntfy on the same LAN, and the existing guard (`check_outbound_url`) allows private addresses on purpose while refusing cloud-metadata and link-local targets. Refusing private addresses would make native push useless for the main use case.

Recommendation: keep allowing private addresses. Three things offset the risk. The endpoint can only be set by an authenticated paired device. The send is limited to an encrypted, fixed-shape POST with no attacker-controlled body, which gives an attacker almost nothing to read back. And the confirmation challenge in step 5 means a registration only becomes live if the thing at that address answers the way a real distributor does. Record the exception in the security notes, since it departs from the standard guidance.

## 7. Coexistence with the ntfy topic path

The topic path stays. It works today, needs no phone code, and some users will prefer it. The risk is double alerts: a phone with the ntfy app subscribed to the topic and native push turned on receives every event twice.

Proposed rule: when a device has a confirmed native endpoint, the UI says so and suggests unsubscribing that phone from the topic. The server keeps sending to the topic as long as one is configured, since other phones may rely on it. If duplicates prove common, a later change can add a per-device "skip the topic" flag. This is deliberately not built into 7.b.

## 8. Testing plan

* **Server, unit.** RFC 8291 appendix A vector for the encryption. VAPID JWT structure and signature verification with the server's public key. Endpoint registration validation (key lengths, mismatched fields). Isolation tests extended so device B still cannot read or change device A's keys. Fan-out re-validates at send time (a hostname that starts resolving to a metadata address after registration is refused). A `410` clears the device.
* **Phone, JVM.** `PushRegistrar` with a fake API and a fake connector wrapper, covering each failure reason and the re-pair trigger.
* **Phone, instrumented (6.1 pattern).** Call the service callbacks directly with a constructed `PushEndpoint`, and assert the PUT happens and that a `confirm` message produces the confirm POST. This needs no distributor.
* **End to end, manual once.** ntfy installed on the emulator or a phone as the distributor, a local ntfy server, and a real SVCS server. Trigger an event and watch the notification arrive with the app force-stopped. Record the result in the 7.b pull request. This is also the spike from section 9.

## 9. Open questions

1. **Does ntfy relay Web Push requests from a third-party application server?** The UnifiedPush documents describe the protocol, but nothing read for this task states that a self-hosted ntfy server accepts an RFC 8291 encrypted, VAPID-signed POST and delivers the body untouched to the ntfy app. The ntfy release notes mention UnifiedPush handling but do not settle it. A half-day spike (run ntfy locally, register from a scratch Android build, POST an encrypted message with a short Python script) answers it. If ntfy does not, the design still holds for other distributors, and the fallback is to document which distributors we test against.
2. **Exact connector API for the pinned version.** The class and field names above come from the published reference and the architecture page. Names such as the public key set's fields should be checked against the version pinned in `libs.versions.toml` before writing 7.b, because the library has changed shape between major versions.
3. **Payload size under real distributors.** The spec allows about 3993 bytes of cleartext. SVCS payloads are well under 1 KB, so this is a non-issue today, but a distributor may impose a smaller limit.
4. **Android 14 and 15 behavior.** Posting a notification from the push callback inside the foreground window should be fine, but background-start restrictions deserve a check on a real device with the app force-stopped, not only on an emulator.

## 10. Work breakdown

| Step | Planner | Size | Depends on |
|------|---------|------|------------|
| Spike: ntfy relays encrypted Web Push (section 9, item 1) | before 7.b | S | none |
| Server: key storage, VAPID endpoint, sender module, RFC 8291 tests | 7.c, part 1 | M | spike |
| Server: confirm endpoint, fan-out with send-time re-validation, dead endpoint handling | 7.c, part 2 | M | part 1 |
| Phone: `push/` package, service, registrar, MORE screen switch and state | 7.b | L | server part 1 |
| Phone: instrumented and JVM tests | 7.b | M | 7.b |
| Security note for the private-address exception, plus an update to `PUSH-NOTIFICATIONS.md` | 7.c | S | decision in section 6 |

Doing the server half first is the cheaper order: the endpoint, the key, and the sender can all be exercised with a script and curl before any Kotlin exists.

## Sources

* UnifiedPush Android specification (AND_3.1.0): https://unifiedpush.org/developers/spec/android/
* UnifiedPush developer introduction (roles, registration flow, application server requirements): https://unifiedpush.org/developers/intro/
* Connector library reference, `UnifiedPush` object: https://unifiedpush.org/kdoc/connector/org.unifiedpush.android.connector/-unified-push/
* Connector library reference, `PushService`: https://unifiedpush.org/kdoc/connector/org.unifiedpush.android.connector/-push-service/
* Connector library reference, `PushEndpoint`: https://unifiedpush.org/kdoc/connector/org.unifiedpush.android.connector.data/-push-endpoint/
* ntfy as a UnifiedPush distributor: https://unifiedpush.org/users/distributors/ntfy/
* ntfy release notes: https://docs.ntfy.sh/releases/
* Five years of UnifiedPush (state of the ecosystem): https://f-droid.org/2026/01/08/unifiedpush-5-years.html
* Repository: `docs/architecture/PUSH-NOTIFICATIONS.md`, `docs/security/PUSH-ENDPOINT-REVIEW-2026-10.md`, `src/gui/routes/push_bp.py`, `src/utils/push_notify.py`

Author: Bloodawn (KheivenD), 2026-10-07 (planner 6.2).
