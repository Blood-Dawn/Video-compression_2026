#!/usr/bin/env bash
# web/supabase/tests/rls/run.sh
#
# Builds a throwaway Postgres database, applies the local auth/roles stub
# (00_local_harness.sql), the REAL schema.sql, then runs the adversarial
# probe (01_adversarial.sql). Exits non-zero if anything failed. Used by
# both a local developer and CI (see .github/workflows/web.yml) - the same
# script either way, so "it passed in CI" and "it passed on my machine"
# mean the same thing.
#
# Requires: a reachable Postgres server and a role that can CREATE DATABASE
# and CREATE ROLE (a fresh `postgres` superuser, e.g. the default local
# install or a GitHub Actions `postgres:16` service container). Never point
# this at a real Supabase project - it creates roles named anon/
# authenticated/service_role and an `auth` schema, which a real Supabase
# project already has, in a shape this script does not control.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$(cd "${HERE}/../../.." && pwd)"
DB_NAME="${SVCS_WEB_RLS_TEST_DB:-svcs_web_rls_test}"
PSQL="${PSQL:-psql}"
# PGHOST/PGPORT/PGUSER/PGPASSWORD are read from the environment the normal
# libpq way, so CI can point this at its service container without editing
# this file.

run() {
  "${PSQL}" -v ON_ERROR_STOP=1 "$@"
}

echo "==> Dropping and recreating ${DB_NAME}"
run -d postgres -c "drop database if exists ${DB_NAME};"
run -d postgres -c "create database ${DB_NAME};"

echo "==> Enabling pgcrypto (for gen_random_uuid(), same as a real Supabase project)"
run -d "${DB_NAME}" -c "create extension if not exists pgcrypto;"

echo "==> Applying the local auth/roles stub"
run -d "${DB_NAME}" -f "${HERE}/00_local_harness.sql"

echo "==> Applying the real schema.sql (the same file a Supabase project runs)"
run -d "${DB_NAME}" -f "${WEB_DIR}/supabase/schema.sql"

echo "==> Running the adversarial probe"
run -d "${DB_NAME}" -f "${HERE}/01_adversarial.sql"

echo "==> Dropping ${DB_NAME}"
run -d postgres -c "drop database if exists ${DB_NAME};"

echo "RLS adversarial suite: PASSED"
