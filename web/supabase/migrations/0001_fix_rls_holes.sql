-- web/supabase/migrations/0001_fix_rls_holes.sql
--
-- Run this ONCE in the Supabase SQL Editor of a project that already ran
-- the ORIGINAL draft/web-dashboard schema.sql (the one with the recursive
-- admin policies). It brings that project's schema up to the fixed state
-- in web/supabase/schema.sql, without dropping and recreating tables or
-- losing any existing rows.
--
-- Safe to run more than once (every statement is idempotent: CREATE OR
-- REPLACE, CREATE TABLE IF NOT EXISTS, DROP POLICY IF EXISTS before each
-- CREATE POLICY, REVOKE/GRANT). This is exactly the script that was
-- verified against a local Postgres seeded with the original draft
-- schema before being handed over - see web/SECURITY.md SVCS-WEB-001
-- through 006 for what each part below fixes and why.
--
-- If you are instead setting up a BRAND NEW Supabase project that has
-- never run any version of this schema, do not run this file - just run
-- the current web/supabase/schema.sql once, which already has all of
-- this built in.

-- ── SVCS-WEB-001: fix the infinite-recursion bug in the admin policies ──
-- This is what "infinite recursion detected in policy for relation
-- profiles" means: the old admin policies queried profiles from inside a
-- policy ON profiles. This function reads profiles without re-triggering
-- profiles' own RLS (it runs as the table owner, which is exempt from its
-- own policies).
create or replace function public.current_role() returns text
language sql
security definer
set search_path = public
stable
as $$
  select role from public.profiles where id = auth.uid()
$$;

drop policy if exists "profiles: admin reads all" on public.profiles;
create policy "profiles: admin reads all" on public.profiles
  for select using (public.current_role() = 'admin');

drop policy if exists "jobs: admin reads all" on public.jobs;
create policy "jobs: admin reads all" on public.jobs
  for select using (public.current_role() = 'admin');

-- ── SVCS-WEB-002: close the role self-escalation hole ───────────────────
-- The old policy only restricted which ROW a user could update, not which
-- COLUMN - a plain UPDATE profiles SET role='admin' WHERE id=auth.uid()
-- passed it outright given Supabase's default broad UPDATE grant.
drop policy if exists "profiles: update own display_name" on public.profiles;
drop policy if exists "profiles: update own row" on public.profiles;
create policy "profiles: update own row" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

revoke update on public.profiles from authenticated;
grant update (display_name) on public.profiles to authenticated;

-- The only remaining way a role ever changes, other than a superuser
-- doing it by hand here in the SQL editor.
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

grant execute on function public.admin_set_role(uuid, text) to authenticated;

-- ── SVCS-WEB-003: stop the ingest-token secret from being re-readable ───
-- "Shown once, never re-fetched" was only a frontend convention before
-- this: the row's own owner could re-SELECT the secret column at any
-- time. This is what actually makes "shown once" true.
revoke select on public.ingest_tokens from authenticated;
grant select (id, user_id, label, created_at, last_used_at) on public.ingest_tokens to authenticated;

-- ── SVCS-WEB-004: guests see nothing at all (not just "whatever the read
--    own policy happened to allow") ─────────────────────────────────────
drop policy if exists "jobs: read own" on public.jobs;
create policy "jobs: read own" on public.jobs
  for select using (auth.uid() = user_id and public.current_role() <> 'guest');

drop policy if exists "ingest_tokens: read own" on public.ingest_tokens;
create policy "ingest_tokens: read own" on public.ingest_tokens
  for select using (auth.uid() = user_id and public.current_role() <> 'guest');

drop policy if exists "ingest_tokens: insert own" on public.ingest_tokens;
create policy "ingest_tokens: insert own" on public.ingest_tokens
  for insert with check (auth.uid() = user_id and public.current_role() <> 'guest');

drop policy if exists "ingest_tokens: delete own" on public.ingest_tokens;
create policy "ingest_tokens: delete own" on public.ingest_tokens
  for delete using (auth.uid() = user_id and public.current_role() <> 'guest');

-- ── SVCS-WEB-005 / 006: rate limiting for the ingest-job Edge Function ───
-- New table; existing projects won't have it yet. No RLS policy is
-- granted to anon/authenticated at all - only the Edge Function's
-- service-role key touches this, by design.
create table if not exists public.ingest_rate_limits (
  client_ip text primary key,
  fail_times jsonb not null default '[]'::jsonb,
  locked_until timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.ingest_rate_limits enable row level security;

revoke all on public.ingest_rate_limits from anon, authenticated;
