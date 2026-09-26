# Migrations

`0001_fix_rls_holes.sql` is a one-time migration for a project that
already ran the **original** `draft/web-dashboard` scaffold's
`schema.sql` (the one with the recursive admin policies and the other
holes documented in `web/SECURITY.md`) against a live Supabase project.

If that's you - you ran the SQL Editor against the original draft and
already have signed-up users - run `0001_fix_rls_holes.sql` once in the
same SQL Editor. It brings the schema up to the current, fixed state in
`web/supabase/schema.sql` without dropping any table or losing any
existing row.

If you are instead setting up a **brand new** project that has never run
any version of this schema, don't run this file - just run the current
`web/supabase/schema.sql` once. It already has everything in this
migration built in from the start.

This migration was verified before being handed over, not just written
and assumed to work: applied to a local Postgres seeded with the exact
original draft schema (reproducing the real "infinite recursion detected
in policy for relation profiles" error first), confirmed the error was
gone afterward, confirmed the full 24-check adversarial suite
(`web/supabase/tests/rls/01_adversarial.sql`) passes against the result
exactly as it does against a fresh `schema.sql` apply, and confirmed
running it a second time is a harmless no-op.
