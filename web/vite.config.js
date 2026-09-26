import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// SVCS Web build config. Plain Vite + React, no server-side rendering:
// Netlify serves the built `dist/` directory as a static site, and every
// data call goes straight from the browser to Supabase (auth + Postgrest),
// same pattern as life-manager.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
