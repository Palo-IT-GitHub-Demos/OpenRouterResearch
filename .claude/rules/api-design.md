---
paths:
  - "**/*.py"
---

# Python / API Design Rules

- All route handlers must have a return type annotation.
- Use Pydantic v2 models for request/response validation; group them in `models.py` when beyond 3 models.
- Use `HTTPException` with explicit status codes; never return raw dicts for errors.
- Read all secrets from environment variables — never hardcode credentials or tokens.
- Return a structured error payload (`detail`, `code`) on every non-2xx response.
