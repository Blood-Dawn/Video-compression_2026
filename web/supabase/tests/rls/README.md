# RLS adversarial tests

What this proves, and what it does not.

## Running it

```sh
# against a local Postgres reachable with the standard PG* env vars
# (PGHOST, PGPORT, PGUSER, PGPASSWORD - defaults work for a local install
# where your OS user can connect and create databases)
web/supabase/tests/rls/run.sh
```

It builds a throwaway database, applies `00_local_harness.sql` (a stand-in
for the parts of a real Supabase project this schema assumes exist: the
`auth` schema, `auth.uid()`, and the `anon` / `authenticated` /
`service_role` roles with the same default grants a fresh Supabase project
ships), applies the real `web/supabase/schema.sql` unmodified, then runs
`01_adversarial.sql` and drops the database again.

## What it actually checks

Against real Postgres RLS enforcement (not a read of the policy text):

- An operator can only ever see their own `jobs` rows, including when they
  name another user's `user_id` directly in the `WHERE` clause.
- An admin sees every `jobs` row and every `profiles` row.
- A guest sees nothing at all: not their own `jobs` rows, not their own
  `ingest_tokens` rows, not other `profiles` rows, and cannot insert an
  `ingest_tokens` row either. This is the deliberate MVP scope from
  `docs/plans/WEB-DASHBOARD-PLAN.md` section 3 item 5, not an oversight.
- A user cannot escalate their own `role` to `admin` through the
  `profiles` update policy, even though the `USING`/`WITH CHECK` clause on
  that policy alone does not stop it (this was a real, reproduced hole in
  the draft - see `web/SECURITY.md` SVCS-WEB-002 - fixed with a
  column-level `GRANT`, not by trying to make RLS express a column
  restriction it cannot express).
- A user cannot touch another user's `profiles` row at all, not even a
  no-op update.
- A user cannot re-read their own `ingest_tokens.secret` after generating
  it, even though the row-level policy alone would allow it (also a real,
  reproduced hole - SVCS-WEB-003 - fixed the same way, with a column-level
  `GRANT`).
- `anon` (not signed in) sees nothing in any of the three tables.
- An authenticated user cannot `INSERT` a `jobs` row directly, despite the
  broad table-level `INSERT` grant `authenticated` has by Supabase
  default - no policy grants it, so it is refused.
- `service_role` (what the ingest-job Edge Function authenticates as)
  bypasses RLS entirely, as intended.
- `admin_set_role()` refuses a non-admin caller (including a caller trying
  to promote themselves) and rejects an invalid role string, and actually
  performs the change for a real admin caller - this is the only
  remaining path to changing a role at all now that direct `UPDATE` of the
  `role` column is revoked.

The very first version of the admin policies (a plain self-referencing
`EXISTS (SELECT 1 FROM profiles ...)` inside a policy ON `profiles`) made
this suite fail immediately with `infinite recursion detected in policy
for relation "profiles"` - not a security hole, a correctness bug: admin
access was simply broken. See `web/SECURITY.md` SVCS-WEB-001. That is
exactly the kind of thing this suite exists to catch before it reaches a
real project.

## What this does NOT prove

- It does not exercise Supabase Auth itself (email/password sign-up, JWT
  issuance, session refresh) - only the SQL-level RLS policies and column
  grants that `schema.sql` defines. `auth.uid()` here is a stand-in
  function reading a session-local setting, not real JWT verification.
- It does not exercise PostgREST (the actual HTTP layer a real Supabase
  project puts in front of Postgres) - only direct SQL role-switching.
  PostgREST is what actually turns a verified JWT's `sub` claim into the
  `request.jwt.claim.sub` setting this harness sets by hand.
- It has never been run against the live Supabase project
  (`nqgjrwcumdlpqudmzdcj.supabase.co`) mentioned in the task instructions -
  only against a local, disposable Postgres 16 instance. Running it there
  would require either the project's Postgres connection string (not just
  the anon key) or reproducing these same checks through the JS client
  against real Auth-issued sessions, neither of which this pass did.
