"""Robust HTTP client for the OpenRouter API.

Wraps the OpenAI SDK (fully compatible with OpenRouter via ``base_url``) and
adds:
- Automatic retries with exponential back-off (tenacity).
- A thin ``get_models()`` method that fetches model metadata via httpx.
- An in-memory ledger of OpenRouter-reported actual costs per completion.
- A typed ``OpenRouterError`` for unrecoverable failures.

Both a synchronous (``OpenRouterClient``) and an asynchronous
(``AsyncOpenRouterClient``) variant are provided.

Usage (async):
    async with AsyncOpenRouterClient(get_settings()) as client:
        completion = await client.chat_completion(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
        )
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from threading import Lock
from time import perf_counter
from typing import Any

import httpx
import openai
import tenacity
from openai.types.chat import ChatCompletion

from src.core.config import Settings

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry attempt.
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class CallCostRecord:
    """Auditable cost and usage metadata for one completed OpenRouter call.

    ``actual_cost_credits`` is taken directly from OpenRouter's authoritative
    ``response.usage.cost`` field. It is ``None`` when the provider response
    does not include a cost; callers must not replace it with a price estimate.
    """

    usage_context: str
    requested_model: str
    resolved_model: str
    generation_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    actual_cost_credits: float | None
    cost_source: str
    latency_ms: float
    """Wall-clock time since the call was first attempted, including any time spent
    queueing behind :class:`AsyncOpenRouterClient`'s concurrency semaphore and any
    retry back-off waits. Kept for backward compatibility with existing exports.
    """
    network_latency_ms: float
    run_id: str | None = None
    scenario_id: str | None = None
    probe_id: str | None = None
    case_id: str | None = None
    turn_index: int | None = None
    """Time spent on the actual request/response round-trip of the attempt that
    succeeded — excludes semaphore queueing and retry back-off waits. This is the
    field that reflects model/provider response time; see docs/quality-methodology.md
    for why ``latency_ms`` alone over-counts it.
    """

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation without prompt content."""
        return asdict(self)


class OpenRouterError(Exception):
    """Raised when the OpenRouter API returns an unrecoverable error."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception should trigger a retry."""
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(exc, openai.APIConnectionError | openai.APITimeoutError)


def _response_value(response: object, name: str) -> object | None:
    """Read a normal or Pydantic-extra response field safely."""
    if isinstance(response, Mapping):
        mapping_value: object | None = response.get(name)
        return mapping_value

    value: object | None = getattr(response, name, None)
    if value is not None:
        return value

    model_extra: object | None = getattr(response, "model_extra", None)
    if isinstance(model_extra, Mapping):
        extra_value: object | None = model_extra.get(name)
        return extra_value
    return None


def _non_negative_int(value: object | None) -> int | None:
    """Convert a non-negative integer-like usage value, otherwise return None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    return None


def _non_negative_float(value: object | None) -> float | None:
    """Convert a finite non-negative monetary value, otherwise return None."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0.0 else None


def _build_call_cost_record(
    completion: ChatCompletion,
    *,
    requested_model: str,
    usage_context: str,
    latency_ms: float,
    network_latency_ms: float,
    run_id: str | None = None,
    scenario_id: str | None = None,
    probe_id: str | None = None,
    case_id: str | None = None,
    turn_index: int | None = None,
) -> CallCostRecord:
    """Build a record from OpenRouter's completion response and usage object."""
    usage = _response_value(completion, "usage")
    actual_cost_credits = _non_negative_float(_response_value(usage, "cost"))
    resolved_model = _response_value(completion, "model")
    generation_id = _response_value(completion, "id")

    return CallCostRecord(
        usage_context=usage_context,
        requested_model=requested_model,
        resolved_model=resolved_model if isinstance(resolved_model, str) else requested_model,
        generation_id=generation_id if isinstance(generation_id, str) else None,
        prompt_tokens=_non_negative_int(_response_value(usage, "prompt_tokens")),
        completion_tokens=_non_negative_int(_response_value(usage, "completion_tokens")),
        total_tokens=_non_negative_int(_response_value(usage, "total_tokens")),
        actual_cost_credits=actual_cost_credits,
        cost_source="openrouter_usage" if actual_cost_credits is not None else "unavailable",
        latency_ms=round(latency_ms, 3),
        network_latency_ms=round(network_latency_ms, 3),
        run_id=run_id,
        scenario_id=scenario_id,
        probe_id=probe_id,
        case_id=case_id,
        turn_index=turn_index,
    )


class _CallCostLedger:
    """Thread-safe in-memory ledger shared by the sync and async clients."""

    def _init_call_cost_ledger(self) -> None:
        self._call_costs: list[CallCostRecord] = []
        self._call_costs_lock = Lock()

    @property
    def call_costs(self) -> tuple[CallCostRecord, ...]:
        """Return an immutable snapshot of all successful completion calls."""
        with self._call_costs_lock:
            return tuple(self._call_costs)

    def _record_call_cost(
        self,
        completion: ChatCompletion,
        *,
        requested_model: str,
        usage_context: str,
        started_at: float,
        network_started_at: float | None = None,
        run_id: str | None = None,
        scenario_id: str | None = None,
        probe_id: str | None = None,
        case_id: str | None = None,
        turn_index: int | None = None,
    ) -> None:
        now = perf_counter()
        record = _build_call_cost_record(
            completion,
            requested_model=requested_model,
            usage_context=usage_context,
            latency_ms=(now - started_at) * 1_000,
            network_latency_ms=(now - (network_started_at if network_started_at is not None else started_at)) * 1_000,
            run_id=run_id,
            scenario_id=scenario_id,
            probe_id=probe_id,
            case_id=case_id,
            turn_index=turn_index,
        )
        with self._call_costs_lock:
            self._call_costs.append(record)


# ── Synchronous client ─────────────────────────────────────────────────────────


class OpenRouterClient(_CallCostLedger):
    """Thread-safe wrapper around the OpenAI SDK pointed at OpenRouter."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._init_call_cost_ledger()
        self._client = openai.OpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=settings.request_timeout,
            max_retries=0,  # Retries are handled by tenacity below.
        )
        self._http = httpx.Client(
            base_url=settings.openrouter_base_url,
            timeout=settings.request_timeout,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}",
            },
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        usage_context: str = "unclassified",
        run_id: str | None = None,
        scenario_id: str | None = None,
        probe_id: str | None = None,
        case_id: str | None = None,
        turn_index: int | None = None,
        **kwargs: Any,
    ) -> ChatCompletion:
        """Send a completion and record OpenRouter's actual response cost."""
        started_at = perf_counter()
        retry_decorator = tenacity.retry(
            retry=tenacity.retry_if_exception(_is_retryable),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
            stop=tenacity.stop_after_attempt(self._settings.max_retries),
            before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

        @retry_decorator
        def _call() -> ChatCompletion:
            return self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )

        try:
            completion = _call()
            self._record_call_cost(
                completion,
                requested_model=model,
                usage_context=usage_context,
                started_at=started_at,
                run_id=run_id,
                scenario_id=scenario_id,
                probe_id=probe_id,
                case_id=case_id,
                turn_index=turn_index,
            )
            return completion
        except openai.APIStatusError as exc:
            raise OpenRouterError(f"OpenRouter API error {exc.status_code} for model '{model}': {exc.message}") from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise OpenRouterError(f"OpenRouter connection/timeout error for model '{model}': {exc}") from exc

    def get_models(self) -> list[dict[str, Any]]:
        """Fetch all available models and their metadata from OpenRouter."""
        try:
            response = self._http.get("/models")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenRouterError(f"Failed to fetch models: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Failed to fetch models: {exc}") from exc

        data: list[dict[str, Any]] = response.json().get("data", [])
        return data

    def get_key_info(self) -> dict[str, Any]:
        """Fetch account/key metadata (credit balance, usage) from ``GET /api/v1/key``.

        Metadata-only endpoint — OpenRouter does not bill this call. A failure
        here (typically HTTP 401) means the configured API key itself is
        invalid, independent of any model or prompt.

        Raises:
            OpenRouterError: On HTTP or network errors.
        """
        try:
            response = self._http.get("/key")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise OpenRouterError(
                    "OpenRouter rejected the API key (HTTP 401 Unauthorized) — " "check OPENROUTER_API_KEY in .env."
                ) from exc
            raise OpenRouterError(f"Failed to fetch key info: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Failed to fetch key info: {exc}") from exc

        data: dict[str, Any] = response.json().get("data", {})
        return data

    def close(self) -> None:
        """Release underlying HTTP connections."""
        self._http.close()

    def __enter__(self) -> OpenRouterClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── Asynchronous client ────────────────────────────────────────────────────────


class AsyncOpenRouterClient(_CallCostLedger):
    """Async wrapper around the OpenAI SDK pointed at OpenRouter.

    Uses ``asyncio.Semaphore`` to cap concurrent in-flight requests and
    ``tenacity.AsyncRetrying`` for resilient retries without blocking the
    event loop.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._init_call_cost_ledger()
        self._client = openai.AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=settings.request_timeout,
            max_retries=0,
        )
        self._http = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=settings.request_timeout,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}",
            },
        )
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_requests)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        usage_context: str = "unclassified",
        run_id: str | None = None,
        scenario_id: str | None = None,
        probe_id: str | None = None,
        case_id: str | None = None,
        turn_index: int | None = None,
        **kwargs: Any,
    ) -> ChatCompletion:
        """Send an async chat completion request with automatic retries.

        The semaphore is acquired per-attempt (not per-call) so it is released
        during exponential back-off waits, keeping concurrency slots free.

        Raises:
            OpenRouterError: On non-retryable errors or exhausted retries.
        """
        started_at = perf_counter()
        try:
            async for attempt in tenacity.AsyncRetrying(
                retry=tenacity.retry_if_exception(_is_retryable),
                wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
                stop=tenacity.stop_after_attempt(self._settings.max_retries),
                before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
                reraise=True,
            ):
                with attempt:
                    async with self._semaphore:
                        # Captured after the semaphore is acquired so network_latency_ms
                        # excludes time spent queueing behind MAX_CONCURRENT_REQUESTS.
                        network_started_at = perf_counter()
                        completion = await self._client.chat.completions.create(
                            model=model,
                            messages=messages,  # type: ignore[arg-type]
                            **kwargs,
                        )
                        self._record_call_cost(
                            completion,
                            requested_model=model,
                            usage_context=usage_context,
                            started_at=started_at,
                            network_started_at=network_started_at,
                            run_id=run_id,
                            scenario_id=scenario_id,
                            probe_id=probe_id,
                            case_id=case_id,
                            turn_index=turn_index,
                        )
                        return completion
        except openai.APIStatusError as exc:
            raise OpenRouterError(f"OpenRouter API error {exc.status_code} for model '{model}': {exc.message}") from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise OpenRouterError(f"OpenRouter connection/timeout error for model '{model}': {exc}") from exc
        # Unreachable — tenacity always either returns or raises.
        raise OpenRouterError(f"Unexpected retry exhaustion for model '{model}'")  # pragma: no cover

    async def get_models(self) -> list[dict[str, Any]]:
        """Async fetch of all available models from ``GET /api/v1/models``.

        Raises:
            OpenRouterError: On HTTP or network errors.
        """
        try:
            response = await self._http.get("/models")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenRouterError(f"Failed to fetch models: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Failed to fetch models: {exc}") from exc

        data: list[dict[str, Any]] = response.json().get("data", [])
        return data

    async def get_key_info(self) -> dict[str, Any]:
        """Async fetch of account/key metadata from ``GET /api/v1/key``.

        Metadata-only endpoint — OpenRouter does not bill this call. A failure
        here (typically HTTP 401) means the configured API key itself is
        invalid, independent of any model or prompt.

        Raises:
            OpenRouterError: On HTTP or network errors.
        """
        try:
            response = await self._http.get("/key")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise OpenRouterError(
                    "OpenRouter rejected the API key (HTTP 401 Unauthorized) — " "check OPENROUTER_API_KEY in .env."
                ) from exc
            raise OpenRouterError(f"Failed to fetch key info: HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Failed to fetch key info: {exc}") from exc

        data: dict[str, Any] = response.json().get("data", {})
        return data

    async def aclose(self) -> None:
        """Release underlying async HTTP connections."""
        await self._http.aclose()
        await self._client.close()

    async def __aenter__(self) -> AsyncOpenRouterClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
