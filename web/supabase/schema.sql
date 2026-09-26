-- SVCS Web — Supabase schema
--
-- Run this once against a fresh Supabase project (SQL Editor -> New query
-- -> paste this whole file -> Run). It creates:
--   * profiles      one row per signed-up user, holding their role
--   * ingest_tokens one row per "desktop app -> this account" sync link
--   * jobs          the synced job-history rows the desktop app reports
--
-- Roles: 'admin' (sees every user's jobs), 'operator' (the default; sees
-- only their own jobs), 'guest' (signed in, but sees nothing until an
-- operator or admin explicitly shares something with them — this schema
-- ships with guests seeing nothing, which is the safe default; loosen the
-- guest policy later if you want a shared demo view).
--
-- Nothing here lets the browser's anon/public key insert or update a job.
-- Rows only ever arrive via the ingest-job Edge Function using the
-- service-role key, which bypasses RLS on purpose and is never sent to the
-- browser.

-- ── profiles ─────────────────────────────────────────────────────────────

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  role text not null default 'operator' check (role in ('admin', 'operator', 'guest')),
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

-- Everyone can read their own profile (to know their own role/name).
create policy "profiles: read own" on public.profiles
  for select using (auth.uid() = id);

-- Admins can read every profile (needed for an admin user list).
create policy "profiles: admin reads all" on public.profiles
  for select using (
    exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin')
  );

-- Users may only change their own display_name, never their own role
-- (role changes go through an admin, or manually in the SQL editor).
create policy "profiles: update own display_name" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

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

create table if not exists public.ingest_tokens (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  label text not null default 'My desktop app',
  secret text not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);

alter table public.ingest_tokens enable row level security;

-- Users manage only their own tokens. The secret is only ever shown to its
-- owner (in the Settings page, once, right after they generate it) — same
-- "user sees it once, server keeps it after that" pattern SVCS's own device
-- tokens use.
create policy "ingest_tokens: read own" on public.ingest_tokens
  for select using (auth.uid() = user_id);

create policy "ingest_tokens: insert own" on public.ingest_tokens
  for insert with check (auth.uid() = user_id);

create policy "ingest_tokens: delete own" on public.ingest_tokens
  for delete using (auth.uid() = user_id);

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

-- Users see their own jobs; admins see every job. No insert/update/delete
-- policy exists for the anon/authenticated roles at all — every write
-- comes from the ingest-job Edge Function using the service-role key,
-- which bypasses RLS entirely, by design.
create policy "jobs: read own" on public.jobs
  for select using (auth.uid() = user_id);

create policy "jobs: admin reads all" on public.jobs
  for select using (
    exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin')
  );
