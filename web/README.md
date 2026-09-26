# SVCS Web

A companion cloud dashboard for [SVCS](../README.md). Real user accounts
(Supabase Auth), a role per user (admin / operator / guest, enforced by
Postgres row-level security, not by trusting the browser), and a per-user
job history synced up from the desktop app.

**This does not replace the desktop app.** All the actual video compression
still happens there — OpenCV, FFmpeg, the ROI encoder, all of it needs a
real machine and a real filesystem, and none of that runs on Netlify or in
a browser. This is purely a "here's what you've already compressed" view,
plus accounts, so more than one person can each see only their own jobs.

## Why Netlify + Supabase, and not "the desktop app as a web app"

Netlify hosts a static site (this React app) and can run short-lived
serverless functions, both with hard execution-time and memory limits.
Neither can run a long-lived compression pipeline. So the architecture is:

- the desktop app keeps compressing video and keeps its own local job
  history exactly as it does today;
- it POSTs a small JSON summary of each finished job (not the video
  itself) to a Supabase Edge Function whenever one finishes, using the
  webhook feature it already has (Settings → Webhook — no code changes
  needed in the desktop app, just a URL and a secret);
- that Edge Function verifies the request really came from a known
  desktop install and writes one row into a `jobs` table, tagged with
  that install's owner;
- this web app reads that table straight from the browser through
  Supabase's client, and Postgres RLS (not this app's code) makes sure a
  signed-in user only ever sees their own rows unless they're an admin.

## One-time setup (you, not Claude — account creation can't be automated)

1. Create a free project at [supabase.com](https://supabase.com).
2. In the Supabase dashboard's SQL Editor, paste the entire contents of
   `supabase/schema.sql` and run it. This creates the `profiles`,
   `ingest_tokens`, and `jobs` tables with their RLS policies, and a
   trigger that gives every new sign-up a `profiles` row automatically.
3. Deploy the ingest function: install the
   [Supabase CLI](https://supabase.com/docs/guides/cli), then from this
   `web/` directory:
   ```
   supabase login
   supabase link --project-ref YOUR-PROJECT-REF
   supabase functions deploy ingest-job --no-verify-jwt
   ```
   `--no-verify-jwt` is required: the desktop app authenticates to this
   function with its own webhook secret (HMAC-signed), not a Supabase user
   session, since it's a background process with nobody logged in.
4. In Supabase's Settings → API page, copy the Project URL and the
   `anon` `public` key into `web/.env` (copy `.env.example` first). Never
   put the `service_role` key here — the Edge Function already has it
   automatically, and it must never reach the browser.
5. To become an admin yourself: sign up once through the app, then in
   Supabase's SQL Editor run
   `update public.profiles set role = 'admin' where id = '<your user id, from the auth.users table>';`
   There's no self-service "make me admin" button on purpose.
6. Deploy to Netlify: connect this GitHub repo, set the **base directory**
   to `web` (already set in `web/netlify.toml`, but Netlify's UI needs it
   too on first setup), and add the same two `VITE_SUPABASE_*` variables
   as environment variables in Netlify's site settings. Netlify will run
   `npm run build` and publish `web/dist`.
7. In each SVCS desktop app install you want synced: sign into this web
   app, go to Settings, generate a secret, then in the desktop app go to
   Settings → Webhook, turn it on, and paste in the URL shown on this
   page and the secret you just generated.

## Local development

```
cd web
npm install
cp .env.example .env   # then fill in the two Supabase values
npm run dev
```

## Design decisions (plan section 3, items 5, 8, 9)

These three were flagged in `docs/plans/WEB-DASHBOARD-PLAN.md` as things
the draft left as an accidental default rather than an actual decision.
Recorded here now that each has been deliberately decided:

- **Guest role scope: guests see nothing at all, not even their own
  data, until an explicit share feature exists.** Not "the safe default
  that happened to fall out of RLS" — the draft's policies didn't
  actually check role at all, so a guest with their own connected
  desktop app and synced jobs would have seen exactly what an operator
  sees. Fixed with an explicit `current_role() <> 'guest'` check on the
  `jobs` and `ingest_tokens` policies (see `supabase/schema.sql` and the
  adversarial tests in `supabase/tests/rls/01_adversarial.sql`), so a
  guest cannot read or create anything, full stop, in this MVP. A future
  "share this job/view with a guest" feature needs its own explicit
  policy when it's built — never by loosening the operator policy to
  quietly include guests.
- **Non-job events (behavior/motion) are out of scope for v1, by
  decision, not by silent no-op.** `event_webhook.py` sends both `"job"`
  and other event kinds through the same webhook. The ingest-job Edge
  Function accepts non-`"job"` events with a 200 (so the desktop app's
  webhook delivery doesn't retry forever) but does not store them. This
  is deliberate: behavior events carry per-frame labels/geometry and
  camera identifiers that haven't been reviewed for multi-user exposure
  the way job summaries have, and the desktop app already has its own
  notification paths for those (`push_notify.py`, the in-app UI). If
  behavior-event history in the dashboard is wanted later, it needs its
  own table, its own RLS policies, and its own adversarial test pass —
  not a quiet addition to the jobs table.
- **No media hosting.** Only text metadata ever reaches Supabase (name,
  sizes, timing, status) — never the video itself, never a thumbnail.
  Supabase Storage has real per-GB storage and egress cost that scales
  with exactly the kind of usage this dashboard would otherwise
  encourage, and video/thumbnail bytes raise the same "who else can see
  this" questions the RLS work above exists to answer carefully rather
  than by default. Revisiting this is a deliberate future decision that
  needs its own storage-quota and access-policy design, not a
  side effect of adding an `image` column somewhere.

## Admin role management

Promoting or demoting a user's role goes through the `admin_set_role(
target_user uuid, new_role text)` Postgres function (see
`supabase/schema.sql`), callable via
`supabase.rpc('admin_set_role', {...})` from an admin's signed-in
session — never a direct `UPDATE` of `profiles.role`, which is no longer
possible even for a user's own row (see `web/SECURITY.md`, SVCS-WEB-002).
The Admin dashboard's user list has a role picker wired to this RPC (see
`src/pages/AdminDashboard.jsx`), replacing the manual-SQL-editor-only
path plan section 3 item 6 flagged.
