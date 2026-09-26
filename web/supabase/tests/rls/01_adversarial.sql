-- web/supabase/tests/rls/01_adversarial.sql
--
-- Adversarial RLS probe, run as superuser so it can freely SET ROLE and
-- flip the JWT-sub GUC between "users". Each check RAISEs on failure, so
-- the "=== ALL ADVERSARIAL RLS CHECKS PASSED ===" line at the end is only
-- reached if every one of them held.
--
-- Run via web/supabase/tests/rls/run.sh, not directly - that script builds
-- the throwaway database and applies 00_local_harness.sql and schema.sql
-- first. See web/supabase/tests/rls/README.md for what this suite does and
-- does not prove.

\set ON_ERROR_STOP on

-- ── fixtures ─────────────────────────────────────────────────────────────
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000a', 'alice@example.com'),
  ('00000000-0000-0000-0000-00000000000b', 'bob@example.com'),
  ('00000000-0000-0000-0000-00000000000c', 'carol-admin@example.com'),
  ('00000000-0000-0000-0000-00000000000d', 'dave-guest@example.com');

-- profiles rows are normally created by the on_auth_user_created trigger;
-- insert directly here since that trigger fires off a real auth.users
-- INSERT, which we just did, so they already exist - just fix up roles.
update public.profiles set role = 'admin' where id = '00000000-0000-0000-0000-00000000000c';
update public.profiles set role = 'guest' where id = '00000000-0000-0000-0000-00000000000d';

insert into public.jobs (user_id, kind, label, status) values
  ('00000000-0000-0000-0000-00000000000a', 'pipeline', 'alice job', 'completed'),
  ('00000000-0000-0000-0000-00000000000b', 'pipeline', 'bob job', 'completed'),
  ('00000000-0000-0000-0000-00000000000d', 'pipeline', 'dave (guest) job', 'completed');

insert into public.ingest_tokens (user_id, label, secret) values
  ('00000000-0000-0000-0000-00000000000a', 'alice desktop', 'alice-super-secret-value');

-- ── helper: become a given user under a given role ──────────────────────
create or replace procedure become(p_role text, p_user uuid) language plpgsql as $$
begin
  execute format('set role %I', p_role);
  perform set_config('request.jwt.claim.sub', coalesce(p_user::text, ''), false);
end;
$$;

create or replace procedure expect_count(p_label text, p_query text, p_expected int) language plpgsql as $$
declare
  actual int;
begin
  execute p_query into actual;
  if actual is distinct from p_expected then
    raise exception 'FAIL: % -> expected % rows, got %', p_label, p_expected, actual;
  else
    raise notice 'ok: % (% rows)', p_label, actual;
  end if;
end;
$$;

-- ══════════════════════════════════════════════════════════════════════
-- 1. Cross-user jobs visibility: can alice (operator) see bob's job?
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000a');
call expect_count('alice sees only her own jobs',
  'select count(*) from public.jobs', 1);
call expect_count('alice cannot see bob''s job by id even naming it directly',
  format('select count(*) from public.jobs where user_id = %L', '00000000-0000-0000-0000-00000000000b'), 0);
reset role;
select set_config('request.jwt.claim.sub', '', false);

-- ══════════════════════════════════════════════════════════════════════
-- 2. Admin breadth: carol (admin) should see every job
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000c');
call expect_count('admin sees every job', 'select count(*) from public.jobs', 3);
call expect_count('admin sees every profile', 'select count(*) from public.profiles', 4);
reset role;
select set_config('request.jwt.claim.sub', '', false);

-- ══════════════════════════════════════════════════════════════════════
-- 3. Guest scope: dave (guest) has his OWN job row (inserted above) - does
--    he see it? The plan's stated intent is "guests see nothing" as the
--    safe MVP default, not "guests see nothing beyond their own data" -
--    verify which one the schema actually implements.
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000d');
call expect_count('guest sees nothing at all, including a job attributed to him',
  'select count(*) from public.jobs', 0);
call expect_count('guest cannot see other profiles',
  'select count(*) from public.profiles', 1);
reset role;
select set_config('request.jwt.claim.sub', '', false);

-- ══════════════════════════════════════════════════════════════════════
-- 4. Role self-escalation: can alice promote herself to admin through the
--    profiles update policy?
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000a');
do $$
begin
  begin
    update public.profiles set role = 'admin' where id = '00000000-0000-0000-0000-00000000000a';
    raise exception 'FAIL: alice was able to UPDATE her own role column at all (should be a column-privilege error)';
  exception
    when insufficient_privilege then
      raise notice 'ok: alice cannot update the role column (insufficient_privilege)';
  end;
end
$$;
reset role;
select set_config('request.jwt.claim.sub', '', false);
-- Confirm it actually did not change, belt and suspenders.
call expect_count('alice''s role is still operator after the attempted escalation',
  format('select count(*) from public.profiles where id = %L and role = %L',
         '00000000-0000-0000-0000-00000000000a', 'operator'), 1);

-- Sanity: alice CAN still update her own display_name (the column that is
-- actually supposed to be writable).
call become('authenticated', '00000000-0000-0000-0000-00000000000a');
update public.profiles set display_name = 'Alice R.' where id = '00000000-0000-0000-0000-00000000000a';
reset role;
call expect_count('alice can still update her own display_name',
  format('select count(*) from public.profiles where id = %L and display_name = %L',
         '00000000-0000-0000-0000-00000000000a', 'Alice R.'), 1);

-- ══════════════════════════════════════════════════════════════════════
-- 5. Can bob update ALICE's profile at all (different row, should fail via
--    RLS regardless of column privilege)?
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000b');
update public.profiles set display_name = 'pwned' where id = '00000000-0000-0000-0000-00000000000a';
reset role;
call expect_count('bob''s update to alice''s row silently affected zero rows',
  format('select count(*) from public.profiles where id = %L and display_name = %L',
         '00000000-0000-0000-0000-00000000000a', 'pwned'), 0);

-- ══════════════════════════════════════════════════════════════════════
-- 6. ingest_tokens secret readback: can alice re-fetch her OWN secret after
--    the fact (the docs claim "shown once, never re-fetched" - is that
--    actually enforced, or just a frontend convention)?
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000a');
do $$
begin
  begin
    perform secret from public.ingest_tokens where user_id = '00000000-0000-0000-0000-00000000000a';
    raise exception 'FAIL: alice was able to SELECT the secret column of her own ingest token (should be a column-privilege error)';
  exception
    when insufficient_privilege then
      raise notice 'ok: alice cannot re-select the secret column (insufficient_privilege)';
  end;
end
$$;
-- The non-secret columns must still be readable (the Settings page's token
-- list needs label/created_at/last_used_at).
call expect_count('alice can still read her token''s non-secret columns',
  'select count(*) from public.ingest_tokens where user_id = current_setting(''request.jwt.claim.sub'')::uuid', 1);
reset role;
select set_config('request.jwt.claim.sub', '', false);

-- Dave (guest) should not be able to see or create ingest tokens at all,
-- same "guest sees nothing" rule as jobs above.
insert into public.ingest_tokens (user_id, label, secret)
  values ('00000000-0000-0000-0000-00000000000d', 'dave desktop', 'dave-secret'); -- inserted as superuser, bypassing RLS, so there is a row to try to read
call become('authenticated', '00000000-0000-0000-0000-00000000000d');
call expect_count('guest cannot see his own ingest token row at all',
  'select count(*) from public.ingest_tokens', 0);
do $$
begin
  begin
    insert into public.ingest_tokens (user_id, label, secret)
      values ('00000000-0000-0000-0000-00000000000d', 'dave second desktop', 'dave-secret-2');
    raise exception 'FAIL: a guest was able to insert an ingest_tokens row';
  exception
    when insufficient_privilege then
      raise notice 'ok: guest cannot insert an ingest_tokens row (insufficient_privilege)';
  end;
end
$$;
reset role;
select set_config('request.jwt.claim.sub', '', false);

-- ══════════════════════════════════════════════════════════════════════
-- 7. anon (not signed in at all) sees nothing anywhere
-- ══════════════════════════════════════════════════════════════════════
call become('anon', null);
call expect_count('anon sees no jobs', 'select count(*) from public.jobs', 0);
call expect_count('anon sees no profiles', 'select count(*) from public.profiles', 0);
call expect_count('anon sees no ingest_tokens', 'select count(*) from public.ingest_tokens', 0);
reset role;

-- ══════════════════════════════════════════════════════════════════════
-- 8. anon/authenticated cannot write jobs directly at all (only the
--    service-role Edge Function may - no insert/update/delete policy
--    should let this through even though the GRANT is broad)
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000a');
do $$
begin
  begin
    insert into public.jobs (user_id, kind, label, status)
      values ('00000000-0000-0000-0000-00000000000a', 'pipeline', 'forged', 'completed');
    raise exception 'FAIL: an authenticated user was able to INSERT a jobs row directly';
  exception
    when insufficient_privilege then
      raise notice 'ok: direct jobs insert is refused (insufficient_privilege - no policy grants it)';
  end;
end
$$;
reset role;
select set_config('request.jwt.claim.sub', '', false);

-- ══════════════════════════════════════════════════════════════════════
-- 9. service_role (the Edge Function's key) bypasses RLS as intended
-- ══════════════════════════════════════════════════════════════════════
set role service_role;
call expect_count('service_role sees every job (bypassrls)', 'select count(*) from public.jobs', 3);
insert into public.ingest_rate_limits (client_ip, fail_times) values ('203.0.113.5', '[1,2,3]'::jsonb);
call expect_count('service_role can read ingest_rate_limits', 'select count(*) from public.ingest_rate_limits', 1);
reset role;

-- ══════════════════════════════════════════════════════════════════════
-- 9b. anon/authenticated cannot touch ingest_rate_limits at all - this is
--     failed-attempt bookkeeping keyed by IP, not user data
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000a');
do $$
begin
  begin
    perform count(*) from public.ingest_rate_limits;
    raise exception 'FAIL: an authenticated user was able to SELECT ingest_rate_limits';
  exception
    when insufficient_privilege then
      raise notice 'ok: authenticated cannot select ingest_rate_limits (insufficient_privilege)';
  end;
end
$$;
reset role;
select set_config('request.jwt.claim.sub', '', false);

call become('anon', null);
do $$
begin
  begin
    perform count(*) from public.ingest_rate_limits;
    raise exception 'FAIL: anon was able to SELECT ingest_rate_limits';
  exception
    when insufficient_privilege then
      raise notice 'ok: anon cannot select ingest_rate_limits (insufficient_privilege)';
  end;
end
$$;
reset role;

-- ══════════════════════════════════════════════════════════════════════
-- 10. admin_set_role: a non-admin cannot call it to promote themself, an
--     admin CAN use it to promote someone else (this is the only
--     legitimate path to changing a role at all now)
-- ══════════════════════════════════════════════════════════════════════
call become('authenticated', '00000000-0000-0000-0000-00000000000a');
do $$
begin
  begin
    perform public.admin_set_role('00000000-0000-0000-0000-00000000000a', 'admin');
    raise exception 'FAIL: a non-admin was able to call admin_set_role on themself';
  exception
    when others then
      if sqlerrm like 'only an admin may change a user''s role%' then
        raise notice 'ok: non-admin admin_set_role call raises the expected exception';
      else
        raise exception 'FAIL: admin_set_role raised the WRONG exception: %', sqlerrm;
      end if;
  end;
end
$$;
reset role;
select set_config('request.jwt.claim.sub', '', false);

call become('authenticated', '00000000-0000-0000-0000-00000000000c'); -- carol, admin
select public.admin_set_role('00000000-0000-0000-0000-00000000000b', 'admin'); -- promote bob
reset role;
select set_config('request.jwt.claim.sub', '', false);
call expect_count('bob is now admin after a real admin called admin_set_role',
  format('select count(*) from public.profiles where id = %L and role = %L',
         '00000000-0000-0000-0000-00000000000b', 'admin'), 1);

-- Reject a bogus role value even from a real admin.
call become('authenticated', '00000000-0000-0000-0000-00000000000c');
do $$
begin
  begin
    perform public.admin_set_role('00000000-0000-0000-0000-00000000000a', 'superuser');
    raise exception 'FAIL: admin_set_role accepted an invalid role value';
  exception
    when others then
      if sqlerrm like 'role must be admin, operator, or guest%' then
        raise notice 'ok: admin_set_role rejects an invalid role value';
      else
        raise exception 'FAIL: admin_set_role raised the WRONG exception: %', sqlerrm;
      end if;
  end;
end
$$;
reset role;
select set_config('request.jwt.claim.sub', '', false);

\echo '=== ALL ADVERSARIAL RLS CHECKS PASSED ==='
