---
applyTo: "**/*.py"
---

Use Python 3.11+ syntax and type hints on all public functions.
Use FastAPI and Pydantic v2 idioms; prefer `model_validator` over `validator`.
Never hardcode secrets; read them from environment variables.
Return structured errors via `HTTPException` with explicit status codes.
Write pytest tests for any behavior-changing code.
