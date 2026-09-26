# SVCS Web security review

Same format and standard as `docs/SECURITY.md`: only what was actually
tested and reproduced is reported here, not what "should" work. This
covers the new surface introduced by `web/` (docs/plans/WEB-DASHBOARD-PLAN.md)
— Supabase Auth, Postgres RLS, the ingest-job Edge Function — as a
standalone document rather than folding it into `docs/SECURITY.md`,
since it is a genuinely separate client with its own trust boundary
(a multi-user cloud service, not the single-operator local-first desktop
app the rest of that document is about).

Review performed 2026-09-26, on branch `claude/svcs-web-dashboard`,
against the draft scaffold from `draft/web-dashboard` (commit `9107b13`).
Method: adversarial testing against a real local Postgres instance
(`web/supabase/tests/rls/`), not a read of the policy text — see that
directory's README for exactly what was and was not exercised this way.

---

## Threat model

SVCS Web is a multi-tenant cloud dashboard: many signed-up users, each
with a role (admin / operator / guest), sharing one Supabase project.
What it holds, and why that matters:

- Job metadata (filenames, sizes, timing, status) for every connected
  desktop install, across every user of the dashboard — not just one
  operator's own machine, unlike the desktop app.
- A per-user webhook secret (`ingest_tokens.secret`) that is the ONLY
  thing standing between "this job belongs to user A" and "this job
  belongs to whoever guessed or leaked A's secret."
- Postgres RLS is the entire enforcement boundary for "who sees whose
  data" — there is no application-code check backing it up, by design
  (the anon key is safe to ship to the browser only because RLS, not
  client code, decides what a query can return).

Realistic attackers:

- Another signed-up user of the same dashboard, trying to read or write
  data belonging to a different user.
- A guest account (deliberately the least-trusted role) trying to see
  anything at all.
- A client that knows the `ingest-job` Edge Function's URL but not any
  real webhook secret, hammering it or trying to forge a signature.
- Someone with read access to the Postgres database (a leaked
  service-role key, a misconfigured backup) reading stored secrets.

Highest-consequence failure modes, in order:

1. **Cross-user data exposure.** One user reading another user's job
   history would defeat the entire reason this is a multi-user system
   rather than everyone sharing one account.
2. **Privilege escalation.** A user granting themselves `admin`.
3. **Ingest forgery / abuse.** Attributing a fabricated job to a real
   user's account, or an unrate-limited endpoint being used to brute-force
   a webhook secret.

---

## Findings and fixes

| ID           | Category                                          | Severity | Where it lives                                                                             | Risk                                                                                                                                                                                                                                                                                                                                                                                                                                         | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | Status |
| ------------ | ------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| SVCS-WEB-001 | Availability / correctness (RLS policy recursion) | High     | `profiles: admin reads all`, `jobs: admin reads all` (`supabase/schema.sql`)               | The draft's admin policies used a self-referencing `EXISTS (SELECT 1 FROM profiles ...)` subquery inside a policy ON `profiles` itself. Postgres detects this and raises `infinite recursion detected in policy for relation "profiles"` rather than hanging — reproduced directly by `web/supabase/tests/rls/run.sh` against the unmodified draft. Admin access was not merely insecure, it did not work at all                             | Replaced with `public.current_role()`, a `SECURITY DEFINER` helper that reads `profiles` without re-triggering `profiles`' own RLS (it runs as the table owner, which is exempt from its own policies absent `FORCE ROW LEVEL SECURITY`)                                                                                                                                                                                                                                                                                                      | fixed  |
| SVCS-WEB-002 | Privilege escalation                              | Critical | `profiles: update own display_name` policy (`supabase/schema.sql`)                         | The policy's `USING`/`WITH CHECK` clause (`auth.uid() = id`) restricts which ROW a user may touch, not which COLUMN. Combined with the broad table-level `UPDATE` grant Supabase's own project defaults give `authenticated`, a plain `UPDATE profiles SET role = 'admin' WHERE id = auth.uid()` passed the policy outright. Reproduced directly against a local Postgres seeded with the same default grants a fresh Supabase project ships | Column-level `GRANT`/`REVOKE`: `authenticated` can now only ever `UPDATE (display_name)` on `profiles`. The only remaining path to changing a role is `admin_set_role()`, a `SECURITY DEFINER` function that itself re-checks the CALLER is an admin before touching any row                                                                                                                                                                                                                                                                  | fixed  |
| SVCS-WEB-003 | Sensitive-data exposure                           | Medium   | `ingest_tokens: read own` policy (`supabase/schema.sql`)                                   | The docs and Settings page UI copy claimed a generated ingest secret is "shown once and never re-fetched." That was only a frontend convention — the row's own owner could re-`SELECT` the `secret` column at any time through this policy, since RLS restricts rows, not columns (same class of gap as SVCS-WEB-002)                                                                                                                        | Column-level `GRANT`: `authenticated` can select `id, user_id, label, created_at, last_used_at` on `ingest_tokens` but never `secret`, for anyone, including the row's own owner                                                                                                                                                                                                                                                                                                                                                              | fixed  |
| SVCS-WEB-004 | Access control (missing scope enforcement)        | Medium   | `jobs: read own`, `ingest_tokens: read/insert/delete own` policies (`supabase/schema.sql`) | The draft's "own row" policies did not check role at all, so a `guest` — the intentionally least-privileged role — could read their own `jobs`/`ingest_tokens` rows exactly like an `operator` could, contradicting the documented intent ("guests see nothing") and the plan's explicit ask to verify this                                                                                                                                  | Added `public.current_role() <> 'guest'` to every one of these policies. A guest now reads and creates nothing, confirmed by dedicated adversarial checks                                                                                                                                                                                                                                                                                                                                                                                     | fixed  |
| SVCS-WEB-005 | Missing rate limiting                             | Medium   | `ingest-job` Edge Function (`supabase/functions/ingest-job/index.ts`)                      | No rate limiting existed at all — flagged as a known gap in `docs/plans/WEB-DASHBOARD-PLAN.md` section 3 item 7. A client that knew the endpoint but not a real secret could send unlimited signature-guessing attempts with no cost                                                                                                                                                                                                         | Adapted `src/gui/auth.py`'s lockout scheme exactly (10 failures per 300s sliding window per client IP trips a 300s lockout), backed by a new `ingest_rate_limits` table since an Edge Function has no shared in-process memory across invocations. Decision logic is pure and unit-tested (`logic.test.ts`); keyed off the `X-Forwarded-For` entry the Supabase edge network itself appends, trusted here for the opposite reason `auth.py` explicitly does not trust that header — see `logic.ts`'s own comment for why the two cases differ | fixed  |
| SVCS-WEB-006 | Access control (missing table grant)              | Low      | `ingest_rate_limits` table (`supabase/schema.sql`)                                         | New table added for SVCS-WEB-005; failed-signature bookkeeping keyed by IP is not user data anyone has a legitimate reason to read through the browser client                                                                                                                                                                                                                                                                                | `REVOKE ALL` from `anon`/`authenticated` explicitly, on top of RLS defaulting to deny with no permissive policy — belt-and-suspenders rather than relying on "no policy happens to allow it" alone                                                                                                                                                                                                                                                                                                                                            | fixed  |
| SVCS-WEB-007 | Known vulnerable dependency                       | Moderate | `react-router-dom@6.26.2` (`web/package.json`)                                             | `npm audit` flagged the installed 6.x line for an open-redirect / arbitrary-constructor-injection CVE pair (GHSA-wrjc-x8rr-h8h6, GHSA-337j-9hxr-rhxg), fixed only in 7.18.4+. Low practical exploitability in this app specifically (the one redirect-target-from-state pattern in `Login.jsx` reads from router state this app itself sets, not a URL parameter), but the fix was a clean drop-in                                           | Upgraded to `react-router-dom@^7.18.4`; verified `npm run build` and the full test suite still pass against the same `Routes`/`Route`/`Navigate`/`useLocation`/`useNavigate`/`Link` usage the draft already had                                                                                                                                                                                                                                                                                                                               | fixed  |

**Count: 7 SVCS-WEB findings, all fixed.**

## Verified defenses (attacked, found holding)

Confirmed by the adversarial suite in `web/supabase/tests/rls/01_adversarial.sql`,
not assumed from reading the policy:

- An operator cannot see another operator's `jobs` row, including when
  naming the other user's `user_id` directly in a `WHERE` clause.
- `anon` (not signed in at all) sees nothing in `profiles`, `jobs`, or
  `ingest_tokens`.
- No policy grants `anon`/`authenticated` an `INSERT`/`UPDATE`/`DELETE`
  on `jobs` at all — every write comes from the Edge Function's
  service-role key, which bypasses RLS by design (Postgres `BYPASSRLS`).
- `admin_set_role()` refuses a non-admin caller (including a caller
  trying to promote themselves) and rejects an invalid role string.
- The `ingest-job` Edge Function's HMAC verification (`hmacSha256Hex`,
  `timingSafeEqual`, `matchTokenAgainstBody`) is cross-checked in
  `logic.test.ts` against a digest generated by the REAL Python signer
  (`event_webhook.py::sign_body`), not just internal self-consistency,
  and checks every candidate token even after a match (no early-exit
  timing signal).

## What this review does NOT cover (be honest about the gap, not silent about it)

- **The live Supabase project was never touched.** Everything above was
  tested against a local, disposable Postgres instance
  (`web/supabase/tests/rls/run.sh`) standing in for the parts of a real
  Supabase project this schema assumes exist. Supabase Auth itself (JWT
  issuance, session refresh, email delivery) and PostgREST (the actual
  HTTP layer in front of Postgres) were never exercised. See
  `web/supabase/tests/rls/README.md`'s own "what this does NOT prove"
  section.
- **The `ingest-job` Edge Function was never run under Deno.** Deno is
  not installed in the environment this review was performed in. Its
  pure decision logic (HMAC verification, rate-limit bookkeeping) is
  unit-tested for real via `logic.ts`/`logic.test.ts` under Node/vitest
  (identical TypeScript, only Web Crypto APIs, no Deno-specific code),
  but the actual `index.ts` wiring (the Postgres queries, the
  `Deno.serve` handler, reading `X-Forwarded-For` from a real request)
  has only been read and type-checked with a standalone `tsc` pass
  ignoring `Deno.*`/`npm:` resolution errors, never executed.
- **Residual risk: `ingest_tokens.secret` is stored in plaintext, by
  necessity.** Unlike `src/gui/device_tokens.py` (which stores only a
  SHA-256 hash, since it only ever needs to compare a presented token
  against that hash), the Edge Function must recompute an HMAC using the
  actual secret as the key — a hash of the secret cannot substitute for
  the secret itself in that computation. A compromised database or
  leaked service-role key exposes every stored webhook secret at once.
  The mitigation here is restricting who can ever read the column back
  (SVCS-WEB-003), not hashing, because hashing is not available for this
  specific use.
- **No external network penetration test.** Matches `docs/SECURITY.md`'s
  own "Owner and deferred security work" entry for the desktop app: this
  needs a live deployment and an external tester, not a sandboxed
  code-level pass.
- **No fuzzing of the Edge Function's request parsing** (malformed JSON
  bodies, oversized payloads, unusual header casing/repetition beyond
  the specific malformed-signature and unknown-token cases
  `logic.test.ts` covers).

## Operational rules carried over from `docs/SECURITY.md`

These applied to this new surface too, not just referenced in passing:

- **Never log secrets.** No webhook secret, session token, or service-role
  key appears in a log line, error message, or HTTP response body
  anywhere in `web/`.
- **Delete the original only after a verified output exists** — not
  applicable here (SVCS Web never touches source video at all; see
  `web/README.md`'s "no media hosting" decision), but the underlying
  principle ("verify before you trust") is exactly why SVCS-WEB-003's fix
  is a column-level `REVOKE`, not just documentation saying not to
  re-fetch the secret.
- **Do not weaken or delete a test to make something pass.** Every fix
  above shipped with the adversarial test that reproduces the original
  hole continuing to pass against the fixed schema, not a loosened
  assertion.
