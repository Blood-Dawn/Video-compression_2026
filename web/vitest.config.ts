import { defineConfig } from "vitest/config";

// Separate from vite.config.js on purpose: vitest here only needs to run
// plain TS unit tests (the Edge Function's logic.ts, and any future
// frontend unit tests) - it does not need the React plugin or the Vite
// dev/build settings. Kept as its own file so `npm run build`'s Vite
// config never picks up test-only settings by accident.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.{js,jsx,ts,tsx}", "supabase/**/*.test.ts"],
  },
});
