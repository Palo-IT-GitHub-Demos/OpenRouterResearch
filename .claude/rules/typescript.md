---
paths:
  - "**/*.ts"
  - "**/*.tsx"
---

Use TypeScript with strict mode enabled (`"strict": true` in tsconfig).
Target Node 20+ — use native `fetch`, `structuredClone`, and `crypto.randomUUID()`.
Never use `any` — prefer `unknown` with explicit type guards.
Use Zod for runtime validation at system boundaries (API inputs, env vars, external data).
Prefer named exports over default exports.
Never hardcode secrets; read them from environment variables.
Use `const` by default; only use `let` when reassignment is required.
