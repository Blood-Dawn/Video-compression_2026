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
// it tries every ingest_tokens row's secret (constant-time compare, keeps
// checking every candidate even after a match — the same approach SVCS's
// own device_tokens.verify_token uses for exactly the same reason: don't
// let comparison timing leak which secret, if any, is correct) until one
// verifies the signature, and attributes the job to that row's user_id.
//
// Deploy: `supabase functions deploy ingest-job` (see web/README.md). Needs
// the project's own SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, which
// Supabase injects into every Edge Function automatically — nothing to
// configure here beyond deploying it.

import { createClient } from "npm:@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
  auth: { persistSession: false },
});

async function hmacSha256Hex(secret: string, body: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return Array.from(new Uint8Array(mac))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Constant-time string compare (equal-length hex digests here, but never
// short-circuit on the first differing byte regardless).
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }

  const signatureHeader = req.headers.get("x-svcs-signature") || "";
  const rawBody = await req.text();

  if (!signatureHeader.startsWith("sha256=")) {
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

  let matchedUserId: string | null = null;
  let matchedTokenId: string | null = null;
  // Deliberately check EVERY token, even after a match, so how long this
  // handler takes never reveals which secret (if any) verified.
  for (const token of tokens ?? []) {
    const expectedDigest = await hmacSha256Hex(token.secret, rawBody);
    if (timingSafeEqual(expectedDigest, presentedDigest) && matchedUserId === null) {
      matchedUserId = token.user_id;
      matchedTokenId = token.id;
    }
  }

  if (!matchedUserId) {
    return new Response("signature did not match any known ingest token", { status: 401 });
  }

  let payload: { event?: string; data?: Record<string, unknown> };
  try {
    payload = JSON.parse(rawBody);
  } catch {
    return new Response("body was not valid JSON", { status: 400 });
  }

  if (payload.event !== "job") {
    // Other event kinds (behavior/motion events) aren't stored yet - accept
    // and no-op rather than making the desktop app's webhook retry forever.
    return new Response("ok (event kind not stored)", { status: 200 });
  }

  const entry = payload.data ?? {};
  const toIso = (v: unknown) =>
    typeof v === "number" ? new Date(v * 1000).toISOString() : null;

  const { error: insertError } = await supabase.from("jobs").insert({
    user_id: matchedUserId,
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
    .eq("id", matchedTokenId);

  return new Response("ok", { status: 200 });
});
