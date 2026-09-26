import fs from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// Smoke test config (plan section 3 item 2's Playwright requirement). Runs
// against the Vite DEV server, not a live Supabase project - every
// Supabase call the app makes is intercepted and answered with a fixture
// in e2e/dashboard-flow.spec.ts (see that file's header for exactly why,
// and what this does and does not prove). VITE_SUPABASE_URL only needs to
// be a syntactically valid URL for createClient() to accept; it is never
// actually reached.

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
    command: "npm run dev -- --port 4317 --strictPort",
    url: "http://127.0.0.1:4317",
    reuseExistingServer: !process.env.CI,
    env: {
      VITE_SUPABASE_URL: "https://smoke-test-project.supabase.co",
      VITE_SUPABASE_ANON_KEY: "smoke-test-anon-key",
    },
  },
});
