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

* the desktop app keeps compressing video and keeps its own local job
  history exactly as it does today;
* it POSTs a small JSON summary of each finished job (not the video
  itself) to a Supabase Edge Function whenever one finishes, using the
  webhook feature it already has (Settings → Webhook — no code changes
  needed in the desktop app, just a URL and a secret);
* that Edge Function verifies the request really came from a known
  desktop install and writes one row into a `jobs` table, tagged with
  that install's owner;
* this web app reads that table straight from the browser through
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

## What this is not (yet)

* No video files are uploaded anywhere — only job metadata (name, size
  before/after, duration, status). Hosting full video would have real
  storage and bandwidth cost; that's a deliberate later decision, not an
  oversight.
* Guests currently see nothing (the safe default). If you want a shared
  read-only demo view for guests, add a policy for that explicitly in
  `supabase/schema.sql` rather than loosening the operator policy.
* Roles are changed manually in the SQL Editor for now — no admin UI for
  promoting/demoting users yet.
* This only ingests "job" events (job_history.py, one row per finished
  compression run). SVCS's behavior/motion events go through the same
  webhook but aren't stored here yet — the Edge Function accepts and
  no-ops on them (see `supabase/functions/ingest-job/index.ts`).
