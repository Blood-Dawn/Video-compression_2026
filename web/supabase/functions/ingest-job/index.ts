// supabase/functions/ingest-job/index.ts
//
// Receives the exact webhook POST the SVCS desktop app already sends from
// src/utils/event_webhook.py (Settings -> Webhook in the desktop app's UI —
// no changes to the desktop app needed). Body shape, from that module's own
// _post(): {"event": "job", "sent_at": <unix seconds>, "data": <job_history
// entry: kind, label, started_at, ended_at, elapsed_s, status, counts,
// bytes_in, bytes_out, error>}, signed via the "X-SVCS-Signature: sha256=<hex>"
// header (sign_body() in the same module: HMAC-SHA256 of the raw body with
// the operator's webhook secret).
//
// This function has no idea in advance WHICH user a request belongs to, so
// it tries every ingest_tokens row's secret until one verifies the
// signature, and attributes the job to that row's user_id. The actual
// verification, and the rate-limit bookkeeping below, live in logic.ts as
// plain functions so they can be unit-tested without a deployed function
// (see web/supabase/functions/ingest-job/logic.test.ts) — this file is
// just the I/O wiring around them: read the request, ask logic.ts what to
// do, read/write Postgres, respond.
//
// Deploy: `supabase functions deploy ingest-job` (see web/README.md). Needs
// the project's own SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, which
// Supabase injects into every Edge Function automatically — nothing to
// configure here beyond deploying it.

import { createClient } from "npm:@supabase/supabase-js@2";
import {
  checkLockout,
  emptyRateLimitRow,
  LOCKOUT_S,
  matchTokenAgainstBody,
  recordFailure,
  recordSuccess,
  type RateLimitRow,
} from "./logic.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
  auth: { persistSession: false },
});

// Best-effort client identity for rate limiting, mirroring
// src/gui/auth.py's _client_ip() in spirit but not in mechanism: auth.py
// deliberately does NOT trust X-Forwarded-For because its Flask app is
// reachable directly, with no proxy in front of it, so that header would
// be entirely attacker-supplied. An Edge Function is the opposite case —
// Supabase's edge network is the ONLY hop between the internet and this
// code, and it is the one that sets/appends this header, not the caller.
// The rightmost entry is the one the trusted edge itself appended (a
// client can freely prepend fake entries before it reaches the edge, but
// cannot control what the edge appends after receiving the request), so
// that is the one entry here worth trusting.
function clientIp(req: Request): string {
  const xff = req.headers.get("x-forwarded-for") || "";
  const parts = xff.split(",").map((s) => s.trim()).filter(Boolean);
  if (parts.length > 0) return parts[parts.length - 1];
  return "unknown";
}

async function loadRateLimitRow(ip: string): Promise<RateLimitRow | null> {
  const { data, error } = await supabase
    .from("ingest_rate_limits")
    .select("fail_times, locked_until")
    .eq("client_ip", ip)
    .maybeSingle();
  if (error || !data) return null;
  return {
    fail_times: Array.isArray(data.fail_times) ? data.fail_times : [],
    locked_until: data.locked_until ? Date.parse(data.locked_until) / 1000 : null,
  };
}

async function saveRateLimitRow(ip: string, row: RateLimitRow): Promise<void> {
  await supabase.from("ingest_rate_limits").upsert({
    client_ip: ip,
    fail_times: row.fail_times,
    locked_until: row.locked_until != null ? new Date(row.locked_until * 1000).toISOString() : null,
    updated_at: new Date().toISOString(),
  });
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }

  const ip = clientIp(req);
  const now = Date.now() / 1000;

  const existingRow = await loadRateLimitRow(ip);
  const lockout = checkLockout(existingRow, now);
  if (lockout.locked) {
    return new Response("too many failed signature attempts, try again later", {
      status: 429,
      headers: { "Retry-After": String(Math.ceil(LOCKOUT_S)) },
    });
  }
  // A just-expired lockout gets its clean slate persisted now, same as
  // auth.py's _is_locked_out popping both dicts once a lockout is served.
  const baseRow = lockout.resetRow ?? existingRow ?? emptyRateLimitRow();

  const signatureHeader = req.headers.get("x-svcs-signature") || "";
  const rawBody = await req.text();

  if (!signatureHeader.startsWith("sha256=")) {
    await saveRateLimitRow(ip, recordFailure(baseRow, now).row);
    return new Response("missing or malformed signature", { status: 401 });
  }
  const presentedDigest = signatureHeader.slice("sha256=".length).toLowerCase();

  const { data: tokens, error: tokensError } = await supabase
    .from("ingest_tokens")
    .select("id, user_id, secret");
  if (tokensError) {
    console.error("could not load ingest_tokens", tokensError);
    return new Response("internal error", { status: 500 });
  }

  const match = await matchTokenAgainstBody(tokens ?? [], rawBody, presentedDigest);

  if (!match) {
    await saveRateLimitRow(ip, recordFailure(baseRow, now).row);
    return new Response("signature did not match any known ingest token", { status: 401 });
  }

  // A verified request clears this IP's failure history, same as
  // auth.py's _record_success.
  await saveRateLimitRow(ip, recordSuccess());

  let payload: { event?: string; data?: Record<string, unknown> };
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response("body was not valid JSON", { status: 400 });
  }

  if (payload.event !== "job") {
    // Other event kinds (behavior/motion events) are out of scope for v1 —
    // see docs/plans/WEB-DASHBOARD-PLAN.md section 3 item 8. Accept and
    // no-op rather than making the desktop app's webhook retry forever.
    return new Response("ok (event kind not stored)", { status: 200 });
  }

  const entry = payload.data ?? {};
  const toIso = (v: unknown) =>
    typeof v === "number" ? new Date(v * 1000).toISOString() : null;

  const { error: insertError } = await supabase.from("jobs").insert({
    user_id: match.userId,
    kind: String(entry.kind ?? "pipeline"),
    label: entry.label != null ? String(entry.label) : null,
    started_at: toIso(entry.started_at),
    ended_at: toIso(entry.ended_at),
    elapsed_s: typeof entry.elapsed_s === "number" ? entry.elapsed_s : null,
    status: String(entry.status ?? "completed"),
    counts: entry.counts ?? {},
    bytes_in: Number(entry.bytes_in ?? 0),
    bytes_out: Number(entry.bytes_out ?? 0),
    error: entry.error != null ? String(entry.error) : null,
  });

  if (insertError) {
    console.error("could not insert job", insertError);
    return new Response("internal error", { status: 500 });
  }

  await supabase
    .from("ingest_tokens")
    .update({ last_used_at: new Date().toISOString() })
    .eq("id", match.tokenId);

  return new Response("ok", { status: 200 });
});
