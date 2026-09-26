// src/lib/supabase.js — the one Supabase client the whole app shares.
//
// Only the anon/public key ever lives here. It can only do what the RLS
// policies in supabase/schema.sql allow an authenticated user to do: read
// their own profile, read their own jobs (or all jobs, if their role is
// 'admin'), and manage their own ingest tokens. It can never read another
// user's jobs, and it can never write to the jobs table at all — that
// table only accepts inserts from the ingest-job Edge Function's
// service-role key, which this file never sees.
import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // Fail loudly in dev rather than silently rendering a broken app.
  console.error(
    "Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY. Copy web/.env.example to web/.env and fill them in from your Supabase project's Settings -> API page.",
  );
}

export const supabase = createClient(url, anonKey);
