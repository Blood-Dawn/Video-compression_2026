# SVCS Web dashboard plan

Written 2026-09-26 by Claude (Cowork), at Kheiven's request, as a plan for a
separate engineering pass to pick up and execute (a fresh Claude Code cloud
session, a teammate, or future-Kheiven) rather than something built out
in-place in a chat. There is a draft scaffold to start from or diverge from
(see section 2), but nothing here is reviewed, tested against a real
Supabase project, or ready to merge.

Same operating rule as every other plan in this directory: no em or en
dashes, and this project's dishonesty-audit culture applies here too -
report only what you actually tested, not what you assume works.

## 0. What this is, and what it deliberately is not

This is **not** "port the desktop app to the web." The desktop app's real
work (OpenCV frame capture, FFmpeg encoding, the ROI encoder) needs a real
machine with a filesystem and no execution-time limit. Netlify only hosts a
static site plus short-lived serverless functions, neither of which can run
a long-lived compression pipeline. So there is no way to "move" the
compression itself onto Netlify, full stop.

What this actually is: a **third client**, "SVCS Web," alongside the
desktop app and the Android app. It's a companion cloud dashboard: real
user accounts, a role per user (admin / operator / guest), and a per-user
view of jobs that have already finished. The desktop app keeps doing 100%
of the actual compressing, unmodified, and pushes a small JSON summary of
each finished job (not the video) to a cloud endpoint through the outbound
webhook feature it already has (`src/utils/event_webhook.py`, wired up in
the desktop UI at Settings -> Webhook). SVCS Web reads that summary.

This also does not reopen the "no in-app RBAC" decision already recorded in
`docs/BLOCKERS.md` ("Multi-user / RBAC ... Full RBAC would make SVCS a VMS
... do not build in-app RBAC"). That decision was about the desktop tool
itself, which stays single-operator and local-first. Multi-user accounts
and roles live entirely in this new, separate, additive client instead.

## 1. Why Supabase + Netlify, modeled on `life-manager`

Kheiven pointed at his own `life-manager` repo (Blood-Dawn/life-manager) as
the pattern to follow: React + Vite + Tailwind CSS frontend, Supabase for
both Auth (email + password) and the database (Postgres with row-level
security), deployed to Netlify as a static site needing only two env vars
(`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`). That pattern transfers
directly: the anon key is safe to ship in a static site precisely because
Postgres RLS, not application code, is what actually enforces "you only see
your own rows, unless you're an admin."

## 2. Draft scaffold already sketched (unreviewed - start here or discard it)

Branch `draft/web-dashboard`, commit `9107b13`, based on `mobile` at the
point the SEC-017 fix landed. `npm run build` succeeds locally. Nothing
else has been verified: no test suite, no lint config, no CI, and it has
never been pointed at a real Supabase project. Treat every line as a
draft, not a foundation to build on faithfully.

What's there, for orientation:

* `web/package.json`, `vite.config.js`, `tailwind.config.js`,
  `netlify.toml` - a plain Vite + React + Tailwind static site, built to
  `web/dist`, with `netlify.toml` pointing Netlify's build at the `web/`
  subdirectory.
* `web/supabase/schema.sql` - three tables: `profiles` (one row per user,
  a `role` column checked to `admin`/`operator`/`guest`, a trigger that
  creates the row automatically on sign-up), `ingest_tokens` (a per-desktop-
  install webhook secret, owned by one user), and `jobs` (the synced job
  rows). RLS policies: a user reads their own `jobs`/`ingest_tokens` rows;
  an admin reads every `jobs` and `profiles` row; nothing (not even the
  owner) can insert/update/delete a `jobs` row through the anon key - only
  the Edge Function, using the service-role key, can write one.
* `web/supabase/functions/ingest-job/index.ts` - a Deno Edge Function that
  receives the desktop app's existing webhook POST unmodified, verifies its
  `X-SVCS-Signature: sha256=...` HMAC (same scheme as
  `event_webhook.py::sign_body`) against every known `ingest_tokens` secret
  (constant-time compare, checks every candidate even after a match - same
  approach as `src/gui/device_tokens.py::verify_token`, for the same
  timing-side-channel reason), and inserts a `jobs` row for whichever
  token matched.
* `web/src/` - the React app: `Login.jsx`/`Signup.jsx` (Supabase Auth),
  `Dashboard.jsx` (the signed-in user's own jobs), `AdminDashboard.jsx`
  (every user's jobs and a user list, admin-only via `RequireRole`),
  `Settings.jsx` (edit display name; generate/revoke an ingest token and
  see the desktop-app-facing webhook URL and secret - the secret is shown
  once, right after generating it, and is never re-fetched afterward).
* `web/README.md` - the setup walkthrough (Supabase project, running
  `schema.sql`, deploying the Edge Function, Netlify env vars, promoting
  the first admin by hand in the SQL editor, connecting a desktop install).

## 3. What real engineering is still needed

In roughly the order it should happen:

1. **Verify the RLS policies actually hold**, adversarially, against a real
   or local Supabase instance - not just read them and assume they're
   correct. Check specifically: can an operator ever see another
   operator's `jobs` row; can a user forge their own `role` to `admin`
   through the `profiles` update policy (the policy only allows updating
   `display_name`, but verify Postgres actually enforces that column
   restriction the way the policy intends); can a guest see anything at
   all right now (it shouldn't be able to).
2. **Add automated tests**: RLS policy tests (Supabase's own testing
   tooling or pgTAP), a unit test suite for the Edge Function's HMAC
   verification logic (constant-time behavior, malformed bodies, unknown
   signatures, replayed bodies), and at minimum one Playwright smoke test
   covering sign up -> generate ingest token -> (mock) job arrives ->
   appears on the dashboard.
3. **Wire CI** (GitHub Actions) to run those tests plus `npm run build` and
   a linter on every PR touching `web/`, matching the rigor the Python side
   already has in `tests/`.
4. **Add ESLint + Prettier config** - none exists in the draft yet.
5. **Decide the guest role's actual scope.** The draft ships guests seeing
   nothing, which is the safe default, not a finished design. If a shared
   read-only demo view is wanted, that needs its own explicit RLS policy,
   never a loosened operator policy.
6. **Admin role management UI.** Right now promoting/demoting a user's
   role is a manual SQL statement in Supabase's SQL editor. Fine for one
   admin bootstrapping the system, not fine as the only way going forward.
7. **Rate-limit the `ingest-job` Edge Function.** There is currently no
   rate limit at all - a misbehaving or malicious desktop-shaped client
   could hammer it. `src/gui/auth.py`'s failed-login lockout (10 failures
   per 300s, 300s lockout) is the pattern already established in this
   codebase for exactly this kind of abuse; adapt it rather than inventing
   a new scheme.
8. **Decide what happens to non-job events.** `event_webhook.py` also
   sends behavior/motion events (`event != "job"`); the draft Edge Function
   currently accepts and silently no-ops on them. Store and surface them,
   or explicitly document that only job completions are in scope.
9. **Decide on media hosting.** Nothing here uploads video or thumbnail
   bytes anywhere - only text metadata (name, sizes, timing, status). That
   was a deliberate scope cut in the draft, not an oversight, because
   Supabase Storage has real cost and bandwidth implications once video
   is involved. Make that a real decision, not a default.
10. **A SECURITY.md-style review pass** once the above is done - findings
    format, severity, fix status - matching how the rest of this project
    tracks security work, before calling any of this production-ready.
11. **Update `README.md` and `docs/BLOCKERS.md`** to describe the real,
    shipped state once this is actually reviewed and merged, rather than
    the aspirational state this plan describes.

## 4. Setup steps only a human can do

None of the following can be automated by an agent - they require signing
up for and clicking through third-party consoles:

1. Create a Supabase project at supabase.com.
2. Run `web/supabase/schema.sql` in that project's SQL editor.
3. Install the Supabase CLI, `supabase login`, `supabase link`, then
   `supabase functions deploy ingest-job --no-verify-jwt` from `web/`.
4. Copy the project's URL and anon key into Netlify's site environment
   variables (and a local `web/.env` for development).
5. Connect the GitHub repo to Netlify, base directory `web`, build command
   `npm run build`, publish directory `dist` (already set in
   `web/netlify.toml`, but Netlify's UI wants it confirmed on first setup).
6. Sign up through the deployed app once, then promote that account to
   `admin` with one `update public.profiles set role = 'admin' where id =
   '...'` in the SQL editor - there is deliberately no self-service path
   to becoming an admin.
7. Per desktop install to connect: sign in to SVCS Web, go to Settings,
   generate an ingest secret, then in the desktop app's Settings ->
   Webhook, turn it on and paste in the shown URL and secret.

## 5. How to pick this up

* Start from `git checkout draft/web-dashboard`, or branch fresh off
  `mobile` and treat the draft as reference material to raid rather than
  a base to build on faithfully - whichever gets to a genuinely reviewed
  result faster.
* Read `docs/BLOCKERS.md`'s existing RBAC decision and `docs/SECURITY.md`
  in full before touching anything auth- or security-adjacent. This
  project reports only what has actually been tested and reproduced, never
  what "should" work - carry that standard into this new surface too.
* This is outside the currently-planned Fall 2026 roadmap
  (see `ROADMAP.md`) for the other four team members (Jorge, Ashleyn,
  Riley, Victor) - it's Kheiven's own initiative on top of that plan, not a
  reassignment of anyone else's work. Coordinate before merging anything
  into `mobile` that could collide with an in-flight teammate task.

## Appendix: the data flow, in words

Desktop app finishes a job -> `job_history.py::record_job()` writes the
local log entry (unchanged) -> `event_webhook.py::publish_job()` enqueues
it -> `_post()` HMAC-signs and POSTs the JSON body to whatever URL the
operator configured in Settings -> Webhook -> the `ingest-job` Edge
Function receives it, finds which `ingest_tokens` row's secret verifies the
signature, and inserts a `jobs` row tagged with that token's `user_id` ->
the SVCS Web frontend, signed in as that user, reads `jobs` straight from
Supabase - Postgres RLS decides what that query is allowed to return, no
application code in the loop enforcing that boundary.
