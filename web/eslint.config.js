import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import prettierConfig from "eslint-config-prettier";
import globals from "globals";
import tseslint from "typescript-eslint";

// Flat config (ESLint 9+). Two independent source trees under web/ with
// different runtimes: the React/Vite frontend (browser globals, JSX) and
// the Supabase Edge Function (Deno globals, no JSX, no React rules) - kept
// as separate config blocks rather than one config trying to fit both.
export default [
  { ignores: ["dist/**", "node_modules/**"] },

  js.configs.recommended,

  // ── frontend (src/) ──────────────────────────────────────────────────
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, ...globals.es2022 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...react.configs.recommended.rules,
      ...react.configs["jsx-runtime"].rules, // React 18: no "React must be in scope" requirement
      ...reactHooks.configs.recommended.rules,
      "react/prop-types": "off", // this codebase does not use prop-types
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
    settings: { react: { version: "18.3" } },
  },

  // ── all TypeScript: the Supabase Edge Function, the Playwright config
  //    and smoke test - every one of these is plain TS with no bundler
  //    involved, so they all get the same parser setup. logic.ts and its
  //    test also run under Node (vitest), but the TS syntax is identical
  //    either way - this block is about parsing TypeScript at all, not
  //    about which runtime executes it. ───────────────────────────────
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: ["supabase/functions/**/*.ts", "e2e/**/*.ts", "*.config.ts"],
  })),
  {
    files: ["supabase/functions/**/*.ts", "e2e/**/*.ts", "*.config.ts"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.es2022, ...globals.node },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  // The Edge Function specifically also has Deno's globals (Deno.serve,
  // Deno.env) on top of the shared TS setup above.
  {
    files: ["supabase/functions/**/*.ts"],
    languageOptions: { globals: { Deno: "readonly" } },
  },

  // ── everything else that's plain JS config (vite.config.js etc.) ────
  {
    files: ["*.config.{js,cjs}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node, ...globals.es2022 },
    },
  },

  // Always last: turns off any ESLint stylistic rule that would conflict
  // with Prettier's own formatting - Prettier owns formatting, ESLint
  // owns correctness, and they should never fight over the same line.
  prettierConfig,
];
