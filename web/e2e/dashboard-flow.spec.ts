// web/e2e/dashboard-flow.spec.ts
//
// Plan section 3 item 2's Playwright requirement: "sign up -> generate
// ingest token -> (mock) job arrives -> appears on the dashboard."
//
// This talks to the real, built frontend running against the real Vite
// dev server, driven by a real Chromium instance - but every Supabase
// call is intercepted with page.route() and answered with a fixture, not
// sent to any real Supabase project. That is a deliberate choice, not a
// shortcut taken to avoid writing the real thing:
//
//   - it never depends on network access to a live project (this session
//     was explicitly told not to touch the live Supabase project without
//     asking first, and a signup flow creates a durable auth.users row -
//     not something to do routinely just by running a test suite);
//   - it is deterministic and fast, with no email-confirmation step, rate
//     limits, or leftover test accounts to clean up;
//   - "a job arrives" has no real desktop app or deployed Edge Function
//     in this test at all - it is simulated by the mock's own state, so
//     this test proves the FRONTEND'S reaction to a job appearing in the
//     jobs table, not that the Edge Function actually inserts one. The
//     Edge Function's own logic is covered separately and for real by
//     web/supabase/functions/ingest-job/logic.test.ts and the ingestion
//     contract by web/supabase/tests/rls/01_adversarial.sql.
//
// If this is ever pointed at the real project instead, every route.*
// block below is exactly what would need to come back out.
import { test, expect, type Route } from "@playwright/test";

const USER_ID = "11111111-1111-1111-1111-111111111111";
const FAKE_SESSION_USER = {
  id: USER_ID,
  aud: "authenticated",
  role: "authenticated",
  email: "smoke-test@example.com",
  email_confirmed_at: new Date().toISOString(),
  app_metadata: {},
  user_metadata: { display_name: "Smoke Tester" },
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

function fakeAuthSession() {
  return {
    access_token: "fake-access-token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "fake-refresh-token",
    user: FAKE_SESSION_USER,
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

test("sign up -> generate ingest token -> a synced job appears on the dashboard", async ({
  page,
}) => {
  let ingestTokenGenerated = false;
  let jobArrived = false;

  // Supabase Auth: sign-up returns a session immediately (no email
  // confirmation step in this fixture), matching GoTrue's real response
  // shape closely enough for supabase-js to accept it as a valid session.
  await page.route("**/auth/v1/signup**", (route) => json(route, fakeAuthSession()));

  // The profile row a real Postgres trigger would have created by now
  // (see handle_new_user() in supabase/schema.sql) - role defaults to
  // 'operator', matching that trigger's real behavior.
  await page.route("**/rest/v1/profiles**", (route) =>
    json(route, {
      id: USER_ID,
      display_name: "Smoke Tester",
      role: "operator",
      created_at: new Date().toISOString(),
    }),
  );

  // jobs: empty until the simulated "webhook delivery" below, then one row.
  await page.route("**/rest/v1/jobs**", (route) => {
    if (!jobArrived) return json(route, []);
    return json(route, [
      {
        id: "job-1",
        kind: "pipeline",
        label: "demo-clip.mp4",
        started_at: new Date(Date.now() - 60_000).toISOString(),
        ended_at: new Date().toISOString(),
        elapsed_s: 12.3,
        status: "completed",
        counts: {},
        bytes_in: 10_485_760,
        bytes_out: 2_097_152,
        error: null,
        received_at: new Date().toISOString(),
      },
    ]);
  });

  // ingest_tokens: the list the Settings page shows (never includes the
  // secret column - see web/supabase/schema.sql's column-level GRANT).
  await page.route("**/rest/v1/ingest_tokens**", (route) => {
    if (route.request().method() === "POST") {
      // Settings.jsx's handleGenerateToken does a plain .insert() with no
      // .select() chained, so the real request carries
      // "Prefer: return=minimal" and expects an empty 201 body - exactly
      // what a real un-.select()-ed Supabase insert gets back.
      ingestTokenGenerated = true;
      return route.fulfill({ status: 201, body: "" });
    }
    if (!ingestTokenGenerated) return json(route, []);
    return json(route, [
      {
        id: "token-1",
        label: "smoke-test desktop",
        created_at: new Date().toISOString(),
        last_used_at: null,
      },
    ]);
  });

  // ── sign up ──────────────────────────────────────────────────────────
  await page.goto("/signup");
  await page.getByLabel("Display name").fill("Smoke Tester");
  await page.getByLabel("Email").fill("smoke-test@example.com");
  await page.getByLabel("Password").fill("correct-horse-battery-staple");
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByText("Your compression jobs")).toBeVisible();
  await expect(page.getByText("No jobs synced yet")).toBeVisible();

  // ── generate an ingest token ─────────────────────────────────────────
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByText("Connect a desktop app")).toBeVisible();
  await expect(page.getByText("No desktop apps connected yet.")).toBeVisible();

  await page.getByLabel("Label").fill("smoke-test desktop");
  await page.getByRole("button", { name: "Generate a new secret" }).click();

  // The secret shown is the value the page generated client-side and
  // inserted, never a value re-fetched from the server (the server
  // literally cannot return it again - see SVCS-WEB-003 in
  // web/SECURITY.md), so this assertion is really "the UI shows what it
  // just generated", not "the UI faithfully echoes the server".
  await expect(
    page.getByText(/paste it into the desktop app's Webhook secret field/),
  ).toBeVisible();
  await expect(page.getByRole("cell", { name: "smoke-test desktop" })).toBeVisible();

  // ── a job "arrives" (the real path is the desktop app's webhook ->
  //    ingest-job Edge Function -> jobs INSERT; simulated here by
  //    flipping the mock's own state, per this file's header) ──────────
  jobArrived = true;

  await page.getByRole("link", { name: "Jobs" }).click();
  await expect(page.getByText("No jobs synced yet")).not.toBeVisible();
  await expect(page.getByRole("cell", { name: "demo-clip.mp4" })).toBeVisible();
  await expect(page.getByText("completed")).toBeVisible();
});
