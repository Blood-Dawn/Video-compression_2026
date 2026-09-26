-- SVCS Web — Supabase schema
--
-- Run this once against a fresh Supabase project (SQL Editor -> New query
-- -> paste this whole file -> Run). It creates:
--   * profiles           one row per signed-up user, holding their role
--   * ingest_tokens      one row per "desktop app -> this account" sync link
--   * jobs               the synced job-history rows the desktop app reports
--   * ingest_rate_limits per-IP failed-signature bookkeeping for the
--                        ingest-job Edge Function's rate limiting
--
-- Roles: 'admin' (sees every user's jobs), 'operator' (the default; sees
-- only their own jobs), 'guest' (signed in, but sees nothing at all until
-- an explicit share feature exists — see docs/plans/WEB-DASHBOARD-PLAN.md
-- section 3 item 5 for why that is a deliberate MVP decision, not an
-- oversight).
--
-- Nothing here lets the browser's anon/public key insert or update a job.
-- Rows only ever arrive via the ingest-job Edge Function using the
-- service-role key, which bypasses RLS on purpose and is never sent to the
-- browser.
--
-- Every policy and grant in this file was adversarially tested against a
-- real Postgres instance before being written this way — see
-- web/supabase/tests/rls/ for the test harness and what it checks, and
-- web/SECURITY.md for the findings that shaped this version (in
-- particular: the first draft of the admin policies below caused Postgres
-- to raise "infinite recursion detected in policy for relation profiles",
-- the role-escalation and secret-readback holes noted in the plan were
-- both real and are fixed here via column-level GRANTs, not just RLS).

-- ── profiles ─────────────────────────────────────────────────────────────

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  role text not null default 'operator' check (role in ('admin', 'operator', 'guest')),
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- SECURITY DEFINER so it reads profiles without triggering profiles' own
-- RLS a second time — see web/SECURITY.md finding SVCS-WEB-001 for why a
-- naive self-referencing EXISTS-subquery policy recurses instead. Defined
-- here, right after the table it reads, because a `language sql` function
-- body is resolved against real objects at CREATE time, not deferred like
-- plpgsql's is.
--
-- Returns the caller's own role, or null if they have no profile row (not
-- signed in, or their profile row was deleted). STABLE + SECURITY DEFINER
-- + a pinned search_path: the same shape as handle_new_user below, for the
-- same reason (a mutable search_path in a SECURITY DEFINER function is an
-- injection surface).
create or replace function public.current_role() returns text
language sql
security definer
set search_path = public
stable
as $$
  select role from public.profiles where id = auth.uid()
$$;

-- Everyone can read their own profile (to know their own role/name, even a
-- guest — knowing you're a guest is not the same as seeing anyone's data).
create policy "profiles: read own" on public.profiles
  for select using (auth.uid() = id);

-- Admins can read every profile (needed for an admin user list). Calls the
-- SECURITY DEFINER helper above instead of a self-referencing EXISTS
-- subquery on profiles, which is what caused the recursion error during
-- adversarial testing (see web/SECURITY.md, SVCS-WEB-001).
create policy "profiles: admin reads all" on public.profiles
  for select using (public.current_role() = 'admin');

-- RLS alone does not stop a user from changing their OWN role: this policy
-- only restricts which ROW may be touched (auth.uid() = id), not which
-- COLUMN. Adversarial testing confirmed a user could UPDATE their own
-- `role` to 'admin' through exactly this policy before the column-level
-- GRANT below was added (SVCS-WEB-002). The policy stays permissive on the
-- row; the column privilege below is what actually blocks it.
create policy "profiles: update own row" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

-- `authenticated` gets table-level UPDATE from Supabase's default
-- privileges (see web/supabase/tests/rls/00_local_harness.sql, which
-- mirrors that default so this exact hole would show up locally too).
-- Restrict it to display_name only: role changes go through
-- admin_set_role() below, never a direct UPDATE.
revoke update on public.profiles from authenticated;
grant update (display_name) on public.profiles to authenticated;

-- The only way a role ever changes, other than a superuser doing it by
-- hand in the SQL editor. SECURITY DEFINER so it can perform the actual
-- UPDATE (which the caller has no column privilege to do directly), after
-- checking the CALLER is an admin. A non-admin calling this gets an
-- exception, not a silent no-op, so a broken admin check fails loudly
-- rather than looking like it worked.
create or replace function public.admin_set_role(target_user uuid, new_role text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if public.current_role() <> 'admin' then
    raise exception 'only an admin may change a user''s role';
  end if;
  if new_role not in ('admin', 'operator', 'guest') then
    raise exception 'role must be admin, operator, or guest';
  end if;
  update public.profiles set role = new_role where id = target_user;
end;
$$;

-- Any signed-in user may CALL this function (the function body itself
-- enforces the admin check, and enforces it against the caller, not the
-- target) — this is the standard Postgres pattern for "privileged action
-- gated by an in-function check" rather than a table grant.
grant execute on function public.admin_set_role(uuid, text) to authenticated;

-- A new auth.users row automatically gets a matching profiles row, default
-- role 'operator', so every fresh sign-up can use the dashboard right away.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'display_name', split_part(new.email, '@', 1)));
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ── ingest_tokens ────────────────────────────────────────────────────────
-- One row per desktop install a user has connected. The `secret` is the
-- SAME string typed into the SVCS desktop app's existing Webhook settings
-- screen (Settings -> Webhook -> Secret) — event_webhook.py HMAC-signs
-- every job POST with it, and the ingest-job function recomputes that HMAC
-- with the matching row to prove the request really came from that user's
-- desktop app before attributing a job to them.
--
-- Storing the raw secret (not a hash of it) is unavoidable here, unlike
-- src/gui/device_tokens.py's SHA-256-only storage: verifying an HMAC
-- signature requires the actual key that produced it, not a one-way hash
-- of it. See web/SECURITY.md for that residual-risk note (a compromised
-- database/service-role key exposes every stored secret) and why the fix
-- is restricting who can ever read the column back, below, not hashing.

create table if not exists public.ingest_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  label text not null default 'My desktop app',
  secret text not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);

alter table public.ingest_tokens enable row level security;

-- Users manage only their own tokens, and never if they are a guest (see
-- current_role() above — guests get no ingest tokens in this MVP, so they
-- cannot originate job data either).
create policy "ingest_tokens: read own" on public.ingest_tokens
  for select using (auth.uid() = user_id and public.current_role() <> 'guest');

create policy "ingest_tokens: insert own" on public.ingest_tokens
  for insert with check (auth.uid() = user_id and public.current_role() <> 'guest');

create policy "ingest_tokens: delete own" on public.ingest_tokens
  for delete using (auth.uid() = user_id and public.current_role() <> 'guest');

-- The docs (and the Settings page's UI copy) say the secret is "shown once
-- and never re-fetched" — adversarial testing showed that was only a
-- frontend convention, not an enforced guarantee: the row's own owner
-- could re-SELECT the secret column at any time through the "read own"
-- policy above (SVCS-WEB-003). Column-level GRANT is what actually makes
-- "shown once" true: the secret column is simply never selectable again,
-- by anyone but the service role, regardless of what any future RLS
-- policy on this table says.
revoke select on public.ingest_tokens from authenticated;
grant select (id, user_id, label, created_at, last_used_at) on public.ingest_tokens to authenticated;

-- ── jobs ─────────────────────────────────────────────────────────────────
-- Mirrors the shape of SVCS's own job_history.py entries (kind, label,
-- started_at/ended_at, status, counts, bytes_in/out, error) plus the
-- user_id the ingest function attributes it to.

create table if not exists public.jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  kind text not null,                 -- "pipeline" | "autocompress"
  label text,
  started_at timestamptz,
  ended_at timestamptz,
  elapsed_s numeric,
  status text not null default 'completed',   -- "completed" | "stopped" | "error"
  counts jsonb not null default '{}'::jsonb,
  bytes_in bigint not null default 0,
  bytes_out bigint not null default 0,
  error text,
  received_at timestamptz not null default now()
);

alter table public.jobs enable row level security;

create index if not exists jobs_user_id_received_at_idx
  on public.jobs (user_id, received_at desc);

-- Users see their own jobs, unless they are a guest (guests see nothing in
-- this MVP — see current_role() above and docs/plans/WEB-DASHBOARD-PLAN.md
-- section 3 item 5). Admins see every job. No insert/update/delete policy
-- exists for the anon/authenticated roles at all — every write comes from
-- the ingest-job Edge Function using the service-role key, which bypasses
-- RLS entirely, by design (confirmed in
-- web/supabase/tests/rls/01_adversarial.sql: a direct authenticated INSERT
-- is refused with insufficient_privilege, since no policy grants it).
create policy "jobs: read own" on public.jobs
  for select using (auth.uid() = user_id and public.current_role() <> 'guest');

create policy "jobs: admin reads all" on public.jobs
  for select using (public.current_role() = 'admin');

-- ── ingest_rate_limits ───────────────────────────────────────────────────
-- Backs the ingest-job Edge Function's rate limiting (plan section 3 item
-- 7). Mirrors src/gui/auth.py's lockout scheme exactly (10 failures per
-- 300s window per client IP trips a 300s lockout — see
-- web/supabase/functions/ingest-job/logic.ts for the actual decision
-- logic and why it needs a Postgres-backed table at all: an Edge Function
-- has no in-process memory shared across invocations the way auth.py's
-- module-level dict does).
--
-- Never exposed to anon or authenticated at all, in either direction —
-- this is failed-signature-attempt bookkeeping keyed by IP address, not
-- user data anyone has a legitimate reason to read through the browser
-- client, and RLS with no permissive policy already defaults to deny, but
-- the explicit REVOKE is the same belt-and-suspenders approach as the
-- column-level GRANTs above: don't rely solely on "no policy happens to
-- allow it" when "the grant does not exist at all" is just as easy to
-- write down.

create table if not exists public.ingest_rate_limits (
  client_ip text primary key,
  fail_times jsonb not null default '[]'::jsonb,
  locked_until timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.ingest_rate_limits enable row level security;

revoke all on public.ingest_rate_limits from anon, authenticated;
