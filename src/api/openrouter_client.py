"""Robust HTTP client for the OpenRouter API.

Wraps the OpenAI SDK (fully compatible with OpenRouter via ``base_url``) and
adds:
- Automatic retries with exponential back-off (tenacity).
- A thin ``get_models()`` method that fetches model metadata via httpx.
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
from typing import Any

import httpx
import openai
import tenacity
from openai.types.chat import ChatCompletion

from src.core.config import Settings

logger = logging.getLogger(__name__)

# HTTP status codes that warrant a retry attempt.
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class OpenRouterError(Exception):
    """Raised when the OpenRouter API returns an unrecoverable error."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception should trigger a retry."""
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code in _RETRYABLE_STATUS_CODES
    return isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError))


# ── Synchronous client ─────────────────────────────────────────────────────────


class OpenRouterClient:
    """Thread-safe wrapper around the OpenAI SDK pointed at OpenRouter."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
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
        **kwargs: Any,
    ) -> ChatCompletion:
        """Send a chat completion request with automatic retries."""
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
            return _call()
        except openai.APIStatusError as exc:
            raise OpenRouterError(
                f"OpenRouter API error {exc.status_code} for model '{model}': {exc.message}"
            ) from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise OpenRouterError(
                f"OpenRouter connection/timeout error for model '{model}': {exc}"
            ) from exc

    def get_models(self) -> list[dict[str, Any]]:
        """Fetch all available models and their metadata from OpenRouter."""
        try:
            response = self._http.get("/models")
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenRouterError(
                f"Failed to fetch models: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Failed to fetch models: {exc}") from exc

        data: list[dict[str, Any]] = response.json().get("data", [])
        return data

    def close(self) -> None:
        """Release underlying HTTP connections."""
        self._http.close()

    def __enter__(self) -> OpenRouterClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ── Asynchronous client ────────────────────────────────────────────────────────


class AsyncOpenRouterClient:
    """Async wrapper around the OpenAI SDK pointed at OpenRouter.

    Uses ``asyncio.Semaphore`` to cap concurrent in-flight requests and
    ``tenacity.AsyncRetrying`` for resilient retries without blocking the
    event loop.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
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
        **kwargs: Any,
    ) -> ChatCompletion:
        """Send an async chat completion request with automatic retries.

        The semaphore is acquired per-attempt (not per-call) so it is released
        during exponential back-off waits, keeping concurrency slots free.

        Raises:
            OpenRouterError: On non-retryable errors or exhausted retries.
        """
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
                        return await self._client.chat.completions.create(
                            model=model,
                            messages=messages,  # type: ignore[arg-type]
                            **kwargs,
                        )
        except openai.APIStatusError as exc:
            raise OpenRouterError(
                f"OpenRouter API error {exc.status_code} for model '{model}': {exc.message}"
            ) from exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            raise OpenRouterError(
                f"OpenRouter connection/timeout error for model '{model}': {exc}"
            ) from exc
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
            raise OpenRouterError(
                f"Failed to fetch models: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise OpenRouterError(f"Failed to fetch models: {exc}") from exc

        data: list[dict[str, Any]] = response.json().get("data", [])
        return data

    async def aclose(self) -> None:
        """Release underlying async HTTP connections."""
        await self._http.aclose()
        await self._client.close()

    async def __aenter__(self) -> AsyncOpenRouterClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

