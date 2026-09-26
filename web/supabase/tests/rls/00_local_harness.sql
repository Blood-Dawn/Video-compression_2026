-- web/supabase/tests/rls/00_local_harness.sql
--
-- Stands in for the pieces of a real Supabase project that schema.sql
-- assumes exist (the auth.users table, auth.uid(), and the anon /
-- authenticated / service_role roles) so schema.sql's actual RLS policies
-- can be adversarially tested against a plain, throwaway local Postgres
-- instead of trusting a read of the SQL.
--
-- This file is NEVER run against a real Supabase project (it already has
-- all of this) - only against a local Postgres for CI and local testing.
-- See web/supabase/tests/rls/README.md for how to run these.

-- ── auth schema stub ─────────────────────────────────────────────────────

create schema if not exists auth;

create table if not exists auth.users (
  id uuid primary key default gen_random_uuid(),
  email text,
  raw_user_meta_data jsonb not null default '{}'::jsonb
);

-- Real Supabase's auth.uid() reads the "sub" claim PostgREST puts in a
-- per-request Postgres setting from the caller's verified JWT. This stub
-- does the same thing against a plain session-local setting so a test can
-- "become" a given user with `select set_config('request.jwt.claim.sub',
-- '<uuid>', true)` the same way a real request's JWT would.
create or replace function auth.uid() returns uuid
  language sql stable
as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

-- ── roles ────────────────────────────────────────────────────────────────
-- Mirrors real Supabase exactly: anon/authenticated are ordinary roles with
-- no BYPASSRLS attribute and no table ownership, so RLS actually applies to
-- them; service_role has BYPASSRLS, matching how the Edge Function's
-- service-role key is able to write jobs rows with RLS enabled and no
-- insert policy granting that to anyone else.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
end
$$;

grant usage on schema public to anon, authenticated, service_role;
grant usage on schema auth to anon, authenticated, service_role;

-- Same default privilege shape a fresh Supabase project ships with: broad
-- grants at the SQL level, with RLS actually doing the restricting. This
-- matters for the adversarial tests: a too-narrow local grant would hide a
-- real hole (RLS alone looking safe only because the grant never let the
-- query through), and a too-broad one is exactly the class of bug
-- (SEC-017-style, "the guard looked right but the real path bypassed it")
-- this project's culture says to test for rather than assume.
grant select, insert, update, delete on all tables in schema public to authenticated;
grant select on all tables in schema public to anon;
grant all privileges on all tables in schema public to service_role;

alter default privileges in schema public
  grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema public
  grant select on tables to anon;
alter default privileges in schema public
  grant all privileges on tables to service_role;
