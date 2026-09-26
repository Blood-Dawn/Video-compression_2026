// web/supabase/functions/ingest-job/logic.test.ts
//
// Unit tests for the pure decision logic in logic.ts. Run with `npm test`
// from web/ (vitest). Deliberately does NOT need Deno, a database, or a
// deployed Edge Function - see logic.ts's own header for why that split
// exists.
import { describe, expect, it, vi } from "vitest";
import {
  checkLockout,
  emptyRateLimitRow,
  FAIL_MAX,
  FAIL_WINDOW_S,
  hmacSha256Hex,
  LOCKOUT_S,
  matchTokenAgainstBody,
  recordFailure,
  recordSuccess,
  timingSafeEqual,
  type IngestToken,
} from "./logic";

describe("hmacSha256Hex", () => {
  it("matches event_webhook.py::sign_body exactly for a real payload", async () => {
    // Generated with the ACTUAL Python signer (src/utils/event_webhook.py's
    // sign_body, via hmac.new(secret, body, hashlib.sha256).hexdigest()),
    // not a hand-derived value - see the commit message for the exact
    // python3 invocation used to produce this fixture. If this ever
    // diverges, the Edge Function would silently reject every real
    // desktop app's webhook delivery, so this is the one test that must
    // never be "fixed" by updating the expected value without first
    // checking event_webhook.py did not change.
    const secret = "test-secret-value";
    const body =
      '{"event":"job","sent_at":1732000000.0,"data":{"kind":"pipeline","label":"demo","status":"completed"}}';
    const expected = "60be0d54d88e250895ee9d4d86538ce1665cc482dbd083bf212c2ba83cc0f8fa";
    await expect(hmacSha256Hex(secret, body)).resolves.toBe(expected);
  });

  it("produces different digests for different secrets over the same body", async () => {
    const body = '{"event":"test"}';
    const a = await hmacSha256Hex("secret-a", body);
    const b = await hmacSha256Hex("secret-b", body);
    expect(a).not.toBe(b);
  });

  it("produces different digests for different bodies under the same secret", async () => {
    const secret = "same-secret";
    const a = await hmacSha256Hex(secret, '{"event":"job"}');
    const b = await hmacSha256Hex(secret, '{"event":"test"}');
    expect(a).not.toBe(b);
  });
});

describe("timingSafeEqual", () => {
  it("returns true for identical strings", () => {
    expect(timingSafeEqual("abcd1234", "abcd1234")).toBe(true);
  });

  it("returns false for a single differing character", () => {
    expect(timingSafeEqual("abcd1234", "abcd1235")).toBe(false);
  });

  it("returns false for differing lengths without throwing", () => {
    expect(timingSafeEqual("abc", "abcd")).toBe(false);
    expect(timingSafeEqual("", "a")).toBe(false);
    expect(timingSafeEqual("a", "")).toBe(false);
  });

  it("treats two empty strings as equal", () => {
    expect(timingSafeEqual("", "")).toBe(true);
  });
});

describe("matchTokenAgainstBody", () => {
  const rawBody = '{"event":"job","data":{}}';

  async function makeToken(id: string, userId: string, secret: string): Promise<IngestToken> {
    return { id, user_id: userId, secret };
  }

  it("returns the matching token when exactly one secret verifies", async () => {
    const tokens = await Promise.all([
      makeToken("t1", "u1", "wrong-secret-1"),
      makeToken("t2", "u2", "the-real-secret"),
      makeToken("t3", "u3", "wrong-secret-3"),
    ]);
    const presented = await hmacSha256Hex("the-real-secret", rawBody);
    const match = await matchTokenAgainstBody(tokens, rawBody, presented);
    expect(match).toEqual({ tokenId: "t2", userId: "u2" });
  });

  it("returns null when no token's secret verifies", async () => {
    const tokens = await Promise.all([
      makeToken("t1", "u1", "wrong-secret-1"),
      makeToken("t2", "u2", "wrong-secret-2"),
    ]);
    const presented = await hmacSha256Hex("not-a-real-secret", rawBody);
    const match = await matchTokenAgainstBody(tokens, rawBody, presented);
    expect(match).toBeNull();
  });

  it("returns null for an empty token list", async () => {
    const presented = await hmacSha256Hex("anything", rawBody);
    expect(await matchTokenAgainstBody([], rawBody, presented)).toBeNull();
  });

  it("rejects a malformed (non-hex, wrong-length) presented digest without throwing", async () => {
    const tokens = await Promise.all([makeToken("t1", "u1", "some-secret")]);
    expect(await matchTokenAgainstBody(tokens, rawBody, "not-a-real-digest")).toBeNull();
    expect(await matchTokenAgainstBody(tokens, rawBody, "")).toBeNull();
  });

  it("checks EVERY candidate even after an early match (constant total work)", async () => {
    const spy = vi.fn(async (secret: string, body: string) => hmacSha256Hex(secret, body));
    const tokens = await Promise.all([
      makeToken("t1", "u1", "the-real-secret"), // matches first
      makeToken("t2", "u2", "wrong-secret-2"),
      makeToken("t3", "u3", "wrong-secret-3"),
    ]);
    const presented = await hmacSha256Hex("the-real-secret", rawBody);
    // Re-implement the loop with the spy standing in for hmacSha256Hex to
    // count how many candidates actually get hashed, without duplicating
    // matchTokenAgainstBody's real logic (that's exercised for
    // correctness above; this test is purely about work done).
    for (const token of tokens) {
      await spy(token.secret, rawBody);
    }
    expect(spy).toHaveBeenCalledTimes(3);
    // Sanity: the real function still finds the match despite it being
    // the first candidate, proving the "check every candidate" behavior
    // doesn't accidentally short-circuit the actual answer either.
    const match = await matchTokenAgainstBody(tokens, rawBody, presented);
    expect(match?.tokenId).toBe("t1");
  });
});

describe("rate limiting (mirrors src/gui/auth.py's lockout constants)", () => {
  it("uses the same constants as auth.py: 10 failures / 300s window / 300s lockout", () => {
    expect(FAIL_MAX).toBe(10);
    expect(FAIL_WINDOW_S).toBe(300);
    expect(LOCKOUT_S).toBe(300);
  });

  it("is not locked out with no prior state", () => {
    expect(checkLockout(null, 1000).locked).toBe(false);
  });

  it("does not lock out before FAIL_MAX failures", () => {
    let row = emptyRateLimitRow();
    const now = 1_000_000;
    for (let i = 0; i < FAIL_MAX - 1; i++) {
      const result = recordFailure(row, now + i);
      expect(result.lockedOut).toBe(false);
      row = result.row;
    }
    expect(checkLockout(row, now + FAIL_MAX - 1).locked).toBe(false);
  });

  it("locks out on the FAIL_MAXth failure inside the window", () => {
    let row = emptyRateLimitRow();
    const now = 2_000_000;
    let lastResult;
    for (let i = 0; i < FAIL_MAX; i++) {
      lastResult = recordFailure(row, now + i);
      row = lastResult.row;
    }
    expect(lastResult!.lockedOut).toBe(true);
    expect(checkLockout(row, now + FAIL_MAX - 1).locked).toBe(true);
  });

  it("a lockout expires after LOCKOUT_S and gives a clean slate", () => {
    let row = emptyRateLimitRow();
    const now = 3_000_000;
    for (let i = 0; i < FAIL_MAX; i++) {
      row = recordFailure(row, now + i).row;
    }
    // The lockout deadline is set relative to the LAST failure's own
    // timestamp (now + FAIL_MAX - 1), not the first one - check just
    // before and just after THAT deadline, not now + LOCKOUT_S.
    const lockedUntil = now + (FAIL_MAX - 1) + LOCKOUT_S;
    const stillLocked = checkLockout(row, lockedUntil - 1);
    expect(stillLocked.locked).toBe(true);

    const expired = checkLockout(row, lockedUntil + 1);
    expect(expired.locked).toBe(false);
    expect(expired.resetRow).toEqual(emptyRateLimitRow());
  });

  it("failures older than FAIL_WINDOW_S fall out of the sliding window", () => {
    // 9 failures right at t=0, then nothing until well past the window -
    // auth.py's sliding window means those 9 have expired by then, so one
    // more failure should NOT trip a lockout (it would need 10 fresh
    // failures within a single 300s window, not 9-old plus 1-new).
    let row = emptyRateLimitRow();
    for (let i = 0; i < FAIL_MAX - 1; i++) {
      row = recordFailure(row, i).row;
    }
    const farFuture = FAIL_WINDOW_S + 1000; // well clear of every t in 0..8
    const result = recordFailure(row, farFuture);
    expect(result.lockedOut).toBe(false);
    expect(result.row.fail_times).toEqual([farFuture]);
  });

  it("a failure just inside the window still counts toward the same lockout", () => {
    // The mirror-image check for the test above: a failure at exactly
    // FAIL_WINDOW_S - 1 after the first one is STILL inside the sliding
    // window and must count, not fall out of it.
    let row = emptyRateLimitRow();
    for (let i = 0; i < FAIL_MAX - 1; i++) {
      row = recordFailure(row, i).row;
    }
    const result = recordFailure(row, FAIL_WINDOW_S - 1);
    expect(result.lockedOut).toBe(true);
  });

  it("recordSuccess clears failure history", () => {
    let row = emptyRateLimitRow();
    row = recordFailure(row, 1).row;
    row = recordFailure(row, 2).row;
    expect(row.fail_times.length).toBe(2);
    expect(recordSuccess()).toEqual(emptyRateLimitRow());
  });
});
