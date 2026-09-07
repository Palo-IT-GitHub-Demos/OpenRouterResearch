"""Structured, content-free pipeline events for operational logs."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


def log_event(logger: logging.Logger, *, phase: str, event: str, **fields: Any) -> None:
    """Write one JSON event without prompts, responses, probes, or secrets."""
    payload = {
        "event": event,
        "phase": phase,
        "timestamp": datetime.now(UTC).isoformat(),
        **fields,
    }
    logger.info("run_event=%s", json.dumps(payload, sort_keys=True, default=str))
