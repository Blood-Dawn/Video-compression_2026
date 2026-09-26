import fs from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// Smoke test config (plan section 3 item 2's Playwright requirement). Runs
// against a real PRODUCTION BUILD (vite build, then vite preview), not the
// dev server and not a live Supabase project - every Supabase call the app
// makes is intercepted and answered with a fixture in
// e2e/dashboard-flow.spec.ts (see that file's header for exactly why, and
// what this does and does not prove). VITE_SUPABASE_URL only needs to be a
// syntactically valid URL for createClient() to accept; it is never
// actually reached.
//
// Build+preview rather than the dev server: the dev server's first request
// after a fresh `npm ci` can trigger Vite's on-demand dependency
// pre-bundling (esbuild scanning node_modules), which is usually fast but
// was observed to occasionally stall past Playwright's webServer timeout
// under CI's shared-CPU runners - a real, reproduced flake (`CI=true npx
// playwright test` hung locally on one run and passed instantly on the
// next, with nothing about the test or the code having changed). A prebuilt
// `dist/` that `vite preview` just serves as static files removes that
// on-demand compilation step entirely, which is also arguably a MORE
// faithful smoke test: it exercises the same build Netlify actually
// deploys, not a dev-only code path.

// The sandbox this was developed in pre-installs one specific Chromium
// build that does not necessarily match whatever revision the installed
// @playwright/test version would otherwise try to download, so it must be
// pointed at directly there rather than running `playwright install`. A
// normal CI runner (see .github/workflows/web.yml) has neither that path
// nor that restriction, and runs its own `playwright install` step
// instead - so this only overrides the executable when that sandbox path
// actually exists, and lets Playwright manage its own browser everywhere
// else.
const SANDBOX_CHROMIUM = "/opt/pw-browsers/chromium";
const executablePath = fs.existsSync(SANDBOX_CHROMIUM) ? SANDBOX_CHROMIUM : undefined;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:4317",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(executablePath ? { launchOptions: { executablePath } } : {}),
      },
    },
  ],
  webServer: {
    command: "npm run build && npm run preview -- --port 4317 --strictPort",
    url: "http://127.0.0.1:4317",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000, // the build step itself is included in this wait
    env: {
      VITE_SUPABASE_URL: "https://smoke-test-project.supabase.co",
      VITE_SUPABASE_ANON_KEY: "smoke-test-anon-key",
    },
  },
});
