// web/supabase/functions/ingest-job/logic.ts
//
// The ingest-job Edge Function's decision logic, pulled out of index.ts so
// it can be unit-tested with a plain test runner instead of only ever
// being exercised by an actual deployed Edge Function. Every function here
// is pure (no Deno.*, no npm: imports, no network, no clock reads beyond a
// `now` parameter the caller supplies) and uses only the Web Crypto API
// (crypto.subtle), which both Deno and Node 19+ provide natively - the
// same file runs unmodified under either runtime.
//
// index.ts is the thin wiring layer: it reads the request, calls into
// here for every decision, and does the actual Postgres/HTTP I/O. Keeping
// that split is what makes the HMAC verification and rate-limit logic
// testable at all without standing up a real Edge Function deployment.

// ── HMAC verification, matching event_webhook.py::sign_body exactly ──────
//
// sign_body() there does `hmac.new(secret, body, hashlib.sha256).hexdigest()`
// prefixed with "sha256=". Same construction here, byte for byte: HMAC-
// SHA256 of the exact raw request body (not a re-serialized/re-parsed
// version of it - re-serializing JSON can reorder keys or change
// whitespace and would make the signature simply never match).

export async function hmacSha256Hex(secret: string, body: string): Promise<string> {
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

// Constant-time string compare. Deliberately hand-rolled rather than using
// a runtime-specific API (Node's crypto.timingSafeEqual takes Buffers and
// throws on unequal length rather than just returning false, and isn't
// available under Deno without the node: compat layer) so the same code
// runs identically under both. The length check up front leaks only
// whether the input is the expected 64 hex characters, which is public
// knowledge about the sha256-hex format, not the presented digest itself;
// every byte of an equal-length comparison is still visited regardless of
// where the first mismatch falls.
export function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export interface IngestToken {
  id: string;
  user_id: string;
  secret: string;
}

export interface TokenMatch {
  tokenId: string;
  userId: string;
}

// Verifies `presentedDigest` (already lowercase hex, with any "sha256="
// prefix already stripped by the caller) against every candidate token's
// HMAC of `rawBody`, and returns whichever one matched, or null.
// Deliberately checks EVERY candidate even after a match (mirrors
// src/gui/device_tokens.py's verify_token, for the identical reason: if
// this returned as soon as it found a match, the handler's response time
// would leak how far down the token list the right one sat, which for a
// small number of connected desktop installs is a real distinguishing
// signal).
export async function matchTokenAgainstBody(
  tokens: IngestToken[],
  rawBody: string,
  presentedDigest: string,
): Promise<TokenMatch | null> {
  let matched: TokenMatch | null = null;
  for (const token of tokens) {
    const expected = await hmacSha256Hex(token.secret, rawBody);
    if (timingSafeEqual(expected, presentedDigest) && matched === null) {
      matched = { tokenId: token.id, userId: token.user_id };
    }
  }
  return matched;
}

// ── rate limiting, mirroring src/gui/auth.py's lockout scheme exactly ────
//
// _FAIL_WINDOW_S = 300, _FAIL_MAX = 10, _LOCKOUT_S = 300: a sliding window
// of failure timestamps, and 10 failures inside any 300s window locks the
// key out for 300s. auth.py tracks this in an in-process dict keyed by
// source IP; an Edge Function has no such shared memory between
// invocations (and may run as several concurrent instances), so index.ts
// persists the same shape (a list of failure timestamps, a lockout
// deadline) in a Postgres table instead - see the ingest_rate_limits
// table in web/supabase/schema.sql. The DECISION logic itself is copied
// here unchanged so it can be tested without a database.

export const FAIL_WINDOW_S = 300;
export const FAIL_MAX = 10;
export const LOCKOUT_S = 300;

export interface RateLimitRow {
  fail_times: number[]; // epoch seconds of failures still inside the window
  locked_until: number | null; // epoch seconds, or null if not locked out
}

export function emptyRateLimitRow(): RateLimitRow {
  return { fail_times: [], locked_until: null };
}

// Mirrors _is_locked_out: true while still inside a lockout. Once the
// lockout has expired, the caller gets a clean slate to persist (mirrors
// _is_locked_out's own housekeeping of popping both dicts once served).
export function checkLockout(
  row: RateLimitRow | null,
  now: number,
): { locked: boolean; resetRow: RateLimitRow | null } {
  if (!row || row.locked_until == null) {
    return { locked: false, resetRow: null };
  }
  if (now >= row.locked_until) {
    return { locked: false, resetRow: emptyRateLimitRow() };
  }
  return { locked: true, resetRow: null };
}

// Mirrors _record_failure: filters the sliding window, appends `now`, and
// trips a new lockout (clearing the timestamp list, same as the Python)
// once FAIL_MAX is reached inside the window.
export function recordFailure(
  row: RateLimitRow | null,
  now: number,
): { row: RateLimitRow; lockedOut: boolean } {
  const times = (row?.fail_times ?? []).filter((t) => now - t < FAIL_WINDOW_S);
  times.push(now);
  if (times.length >= FAIL_MAX) {
    return { row: { fail_times: [], locked_until: now + LOCKOUT_S }, lockedOut: true };
  }
  return { row: { fail_times: times, locked_until: null }, lockedOut: false };
}

// Mirrors _record_success: a clean slate for an address that just
// authenticated. (auth.py only pops fail_times on success, never
// locked_until - but that path is only reachable when not locked out in
// the first place, so there is nothing to distinguish here.)
export function recordSuccess(): RateLimitRow {
  return emptyRateLimitRow();
}
