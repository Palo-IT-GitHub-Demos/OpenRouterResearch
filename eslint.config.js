// ESLint Flat Config (ESLint 9+)
// Docs: https://eslint.org/docs/latest/use/configure/configuration-files-new

import js from "@eslint/js";
import tsEslint from "typescript-eslint";

export default tsEslint.config(
  // ── Base recommended rules ─────────────────────────────────────────────────
  js.configs.recommended,
  ...tsEslint.configs.strictTypeChecked,

  // ── TypeScript-aware rules ─────────────────────────────────────────────────
  {
    languageOptions: {
      parserOptions: {
        project: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // Disallow `any` — use `unknown` with type guards instead
      "@typescript-eslint/no-explicit-any": "error",

      // Require explicit return types on exported functions
      "@typescript-eslint/explicit-module-boundary-types": "warn",

      // Prefer nullish coalescing (??) over logical OR (||) for defaults
      "@typescript-eslint/prefer-nullish-coalescing": "error",

      // Prefer optional chaining (?.) over manual null checks
      "@typescript-eslint/prefer-optional-chain": "error",

      // Disallow non-null assertions (!) — handle null explicitly
      "@typescript-eslint/no-non-null-assertion": "error",
    },
  },

  // ── Ignored paths ──────────────────────────────────────────────────────────
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "coverage/**",
      "*.config.*",
      "*.config.js",
    ],
  },
);
