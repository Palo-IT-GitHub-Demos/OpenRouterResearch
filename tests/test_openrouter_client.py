"""Unit tests for src/api/openrouter_client.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.api.openrouter_client import AsyncOpenRouterClient, OpenRouterClient, OpenRouterError
from src.core.config import Settings


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        openrouter_api_key="sk-test",  # type: ignore[arg-type]
        target_models="openai/gpt-4o-mini",
    )


@pytest.fixture()
def client(settings: Settings) -> OpenRouterClient:
    return OpenRouterClient(settings)


class TestChatCompletion:
    def test_returns_completion_on_success(self, client: OpenRouterClient) -> None:
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Hello!"

        with patch.object(
            client._client.chat.completions,
            "create",
            return_value=mock_completion,
        ):
            result = client.chat_completion(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
            )

        assert result is mock_completion

    def test_records_actual_cost_from_openrouter_usage(self, client: OpenRouterClient) -> None:
        mock_completion = MagicMock()
        mock_completion.id = "gen-123"
        mock_completion.model = "openai/gpt-4o-mini"
        mock_completion.usage = SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=45,
            total_tokens=165,
            model_extra={"cost": 0.000321},
        )

        with patch.object(client._client.chat.completions, "create", return_value=mock_completion):
            client.chat_completion(
                model="requested/model",
                messages=[{"role": "user", "content": "Hi"}],
                usage_context="quality_screen",
            )

        assert len(client.call_costs) == 1
        record = client.call_costs[0]
        assert record.usage_context == "quality_screen"
        assert record.requested_model == "requested/model"
        assert record.resolved_model == "openai/gpt-4o-mini"
        assert record.generation_id == "gen-123"
        assert record.prompt_tokens == 120
        assert record.completion_tokens == 45
        assert record.actual_cost_credits == pytest.approx(0.000321)
        assert record.cost_source == "openrouter_usage"

    def test_marks_missing_usage_cost_as_unavailable(self, client: OpenRouterClient) -> None:
        mock_completion = MagicMock()
        mock_completion.id = "gen-456"
        mock_completion.model = "openai/gpt-4o-mini"
        mock_completion.usage = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            model_extra={},
        )

        with patch.object(client._client.chat.completions, "create", return_value=mock_completion):
            client.chat_completion(
                model="openai/gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
            )

        record = client.call_costs[0]
        assert record.actual_cost_credits is None
        assert record.cost_source == "unavailable"

    def test_raises_open_router_error_on_status_error(self, client: OpenRouterClient) -> None:
        import openai

        with patch.object(
            client._client.chat.completions,
            "create",
            side_effect=openai.APIStatusError(
                "Bad request",
                response=MagicMock(status_code=400),
                body=None,
            ),
        ):
            with pytest.raises(OpenRouterError, match="400"):
                client.chat_completion(
                    model="openai/gpt-4o-mini",
                    messages=[{"role": "user", "content": "Hi"}],
                )


class TestGetModels:
    def test_returns_model_list(self, client: OpenRouterClient) -> None:
        fake_response = MagicMock(spec=httpx.Response)
        fake_response.json.return_value = {"data": [{"id": "openai/gpt-4o-mini", "name": "GPT-4o mini"}]}
        fake_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", return_value=fake_response):
            models = client.get_models()

        assert len(models) == 1
        assert models[0]["id"] == "openai/gpt-4o-mini"

    def test_raises_open_router_error_on_http_error(self, client: OpenRouterClient) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401

        with patch.object(
            client._http,
            "get",
            side_effect=httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=mock_response),
        ):
            with pytest.raises(OpenRouterError, match="401"):
                client.get_models()


class TestGetKeyInfo:
    def test_returns_key_metadata(self, client: OpenRouterClient) -> None:
        fake_response = MagicMock(spec=httpx.Response)
        fake_response.json.return_value = {
            "data": {"label": "my-key", "usage": 1.23, "limit": None, "limit_remaining": None, "is_free_tier": False}
        }
        fake_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", return_value=fake_response):
            info = client.get_key_info()

        assert info["label"] == "my-key"
        assert info["usage"] == 1.23

    def test_raises_open_router_error_with_actionable_message_on_401(self, client: OpenRouterClient) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401

        with patch.object(
            client._http,
            "get",
            side_effect=httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=mock_response),
        ):
            with pytest.raises(OpenRouterError, match="OPENROUTER_API_KEY"):
                client.get_key_info()

    def test_raises_open_router_error_on_other_http_error(self, client: OpenRouterClient) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503

        with patch.object(
            client._http,
            "get",
            side_effect=httpx.HTTPStatusError("Unavailable", request=MagicMock(), response=mock_response),
        ):
            with pytest.raises(OpenRouterError, match="503"):
                client.get_key_info()

    def test_raises_open_router_error_on_network_error(self, client: OpenRouterClient) -> None:
        with patch.object(client._http, "get", side_effect=httpx.ConnectError("boom")):
            with pytest.raises(OpenRouterError, match="Failed to fetch key info"):
                client.get_key_info()


class TestAsyncChatCompletion:
    async def test_records_actual_cost_from_openrouter_usage(self, settings: Settings) -> None:
        client = AsyncOpenRouterClient(settings)
        mock_completion = MagicMock()
        mock_completion.id = "gen-async"
        mock_completion.model = "openai/gpt-4o-mini"
        mock_completion.usage = SimpleNamespace(
            prompt_tokens=90,
            completion_tokens=12,
            total_tokens=102,
            model_extra={"cost": 0.0001},
        )

        try:
            with patch.object(client._client.chat.completions, "create", new=AsyncMock(return_value=mock_completion)):
                await client.chat_completion(
                    model="openai/gpt-4o-mini",
                    messages=[{"role": "user", "content": "Hi"}],
                    scenario_id="security-01",
                    turn_index=2,
                    usage_context="security_scan",
                )
        finally:
            await client.aclose()

        record = client.call_costs[0]
        assert record.usage_context == "security_scan"
        assert record.actual_cost_credits == pytest.approx(0.0001)

    async def test_network_latency_excludes_semaphore_queueing_time(self, settings: Settings) -> None:
        import asyncio

        # Force serialization so the second call must wait for the first to
        # release the semaphore before its own network call can even start.
        settings.max_concurrent_requests = 1
        client = AsyncOpenRouterClient(settings)

        async def _slow_create(**kwargs: object) -> MagicMock:
            del kwargs
            await asyncio.sleep(0.05)
            completion = MagicMock()
            completion.id = "gen-async"
            completion.model = "openai/gpt-4o-mini"
            completion.usage = SimpleNamespace(
                prompt_tokens=1, completion_tokens=1, total_tokens=2, model_extra={"cost": 0.0}
            )
            return completion

        try:
            with patch.object(client._client.chat.completions, "create", new=AsyncMock(side_effect=_slow_create)):
                await asyncio.gather(
                    client.chat_completion(model="openai/gpt-4o-mini", messages=[{"role": "user", "content": "A"}]),
                    client.chat_completion(model="openai/gpt-4o-mini", messages=[{"role": "user", "content": "B"}]),
                )
        finally:
            await client.aclose()

        # Whichever call went second queued behind the first for ~0.05s, so its
        # wall-clock latency_ms is well above its own network_latency_ms — the
        # opposite would mean queueing time is still leaking into the network figure.
        # Bounds are generous (not a strict 2x ratio) to stay robust to scheduler jitter.
        queued_record = max(client.call_costs, key=lambda r: r.latency_ms)
        assert queued_record.latency_ms > 90  # queued (~50ms) + own network call (~50ms)
        assert queued_record.network_latency_ms < 90  # its own network call only


class TestAsyncGetKeyInfo:
    async def test_returns_key_metadata(self, settings: Settings) -> None:
        client = AsyncOpenRouterClient(settings)
        fake_response = MagicMock(spec=httpx.Response)
        fake_response.json.return_value = {"data": {"label": "my-key", "usage": 0.5}}
        fake_response.raise_for_status = MagicMock()

        try:
            with patch.object(client._http, "get", new=AsyncMock(return_value=fake_response)):
                info = await client.get_key_info()
        finally:
            await client.aclose()

        assert info["label"] == "my-key"

    async def test_raises_open_router_error_with_actionable_message_on_401(self, settings: Settings) -> None:
        client = AsyncOpenRouterClient(settings)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401

        try:
            with patch.object(
                client._http,
                "get",
                new=AsyncMock(
                    side_effect=httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=mock_response)
                ),
            ):
                with pytest.raises(OpenRouterError, match="OPENROUTER_API_KEY"):
                    await client.get_key_info()
        finally:
            await client.aclose()
