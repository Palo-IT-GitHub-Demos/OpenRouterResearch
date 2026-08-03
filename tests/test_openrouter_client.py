"""Unit tests for src/api/openrouter_client.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.api.openrouter_client import OpenRouterClient, OpenRouterError
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
    def test_returns_completion_on_success(
        self, client: OpenRouterClient
    ) -> None:
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

    def test_raises_open_router_error_on_status_error(
        self, client: OpenRouterClient
    ) -> None:
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
        fake_response.json.return_value = {
            "data": [{"id": "openai/gpt-4o-mini", "name": "GPT-4o mini"}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", return_value=fake_response):
            models = client.get_models()

        assert len(models) == 1
        assert models[0]["id"] == "openai/gpt-4o-mini"

    def test_raises_open_router_error_on_http_error(
        self, client: OpenRouterClient
    ) -> None:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401

        with patch.object(
            client._http,
            "get",
            side_effect=httpx.HTTPStatusError(
                "Unauthorized", request=MagicMock(), response=mock_response
            ),
        ):
            with pytest.raises(OpenRouterError, match="401"):
                client.get_models()
