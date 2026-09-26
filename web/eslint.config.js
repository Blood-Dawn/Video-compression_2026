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

  // ── Supabase Edge Function (Deno runtime) ───────────────────────────
  // logic.ts and its test run under Node too (vitest), but the TS syntax
  // is identical either way - this block is about parsing TypeScript at
  // all, not about which runtime executes it.
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: ["supabase/functions/**/*.ts"],
  })),
  {
    files: ["supabase/functions/**/*.ts"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.es2022, Deno: "readonly" },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },

  // ── everything else that's plain JS config (vite.config.js etc.) ────
  {
    files: ["*.config.{js,ts}", "*.config.cjs"],
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
