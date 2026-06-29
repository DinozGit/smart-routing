"""
Phase 2 — тесты Fallback Chain (Step 2.2).

При 5xx/timeout от основного провайдера → fallback_model из роли.
При 4xx → fallback не происходит (client error).
Только non-streaming (как договорились).
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import router

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestFallbackChain:
    """Non-streaming fallback chain: primary 5xx → fallback model."""

    @pytest.fixture
    def mock_200_response(self):
        """Успешный ответ от провайдера."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "id": "chatcmpl-test",
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        resp.raise_for_status = MagicMock()
        return resp

    @pytest.fixture
    def mock_500_response(self):
        """5xx ответ от провайдера."""
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = {"error": "Internal Server Error"}
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(),
                response=resp,
            )
        )
        return resp

    @pytest.fixture
    def mock_429_response(self):
        """4xx ответ (Rate Limit)."""
        resp = MagicMock()
        resp.status_code = 429
        resp.json.return_value = {"error": "Rate Limited"}
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Too Many Requests",
                request=MagicMock(),
                response=resp,
            )
        )
        return resp

    async def test_primary_success_no_fallback(
        self, client, monkeypatch, mock_200_response
    ):
        """Успешный ответ от primary → fallback не вызывается."""
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_200_response

        monkeypatch.setattr(router.http_client, "post", mock_post)

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
        )
        assert resp.status_code == 200
        assert call_count == 1  # fallback не вызывался

    async def test_5xx_triggers_fallback(
        self, client, monkeypatch, mock_500_response, mock_200_response
    ):
        """5xx от primary → запрос к fallback model."""
        call_count = 0
        models_used = []

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            models_used.append(kwargs.get("json", {}).get("model", ""))
            if call_count == 1:
                return mock_500_response
            return mock_200_response

        monkeypatch.setattr(router.http_client, "post", mock_post)

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant.",
                    },
                    {"role": "user", "content": "hello"},
                ],
                "stream": False,
            },
        )
        assert resp.status_code == 200
        assert call_count == 2  # primary + fallback
        # Первая модель — coordinator (glm/pro), вторая — fallback (flash)
        assert "glm" in models_used[0].lower() or "pro" in models_used[0].lower(), f"Expected coordinator, got {models_used[0]}"
        assert "flash" in models_used[1].lower()

    async def test_4xx_no_fallback(self, client, monkeypatch, mock_429_response):
        """4xx от primary → fallback НЕ происходит."""
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_429_response

        monkeypatch.setattr(router.http_client, "post", mock_post)

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
        )
        # 4xx пробрасывается как ошибка
        assert resp.status_code == 429
        assert call_count == 1  # fallback не вызывался

    async def test_all_models_fail_502(self, client, monkeypatch, mock_500_response):
        """Все модели в цепочке упали → 502."""
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_500_response

        monkeypatch.setattr(router.http_client, "post", mock_post)

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant.",
                    },
                    {"role": "user", "content": "hello"},
                ],
                "stream": False,
            },
        )
        assert resp.status_code == 502
        # 2 попытки: primary + fallback
        assert call_count == 2

    async def test_timeout_triggers_fallback(
        self, client, monkeypatch, mock_200_response
    ):
        """Timeout от primary → fallback."""
        call_count = 0
        models_used = []

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            models_used.append(kwargs.get("json", {}).get("model", ""))
            if call_count == 1:
                raise httpx.TimeoutException("Connection timeout")
            return mock_200_response

        monkeypatch.setattr(router.http_client, "post", mock_post)

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant.",
                    },
                    {"role": "user", "content": "hello"},
                ],
                "stream": False,
            },
        )
        assert resp.status_code == 200
        assert call_count == 2

    async def test_fallback_count_incremented(
        self, client, monkeypatch, mock_500_response, mock_200_response
    ):
        """При fallback счётчик fallback_count увеличивается."""
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_500_response
            return mock_200_response

        monkeypatch.setattr(router.http_client, "post", mock_post)

        await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant.",
                    },
                    {"role": "user", "content": "hello"},
                ],
                "stream": False,
            },
        )

        # Проверяем, что fallback_count увеличился
        stats_resp = await client.get("/stats")
        stats = stats_resp.json()
        assert stats.get("fallback_count", 0) >= 1

    async def test_explicit_model_no_role_no_fallback(
        self, client, monkeypatch, mock_200_response
    ):
        """Явная модель (role='') → нет fallback model → один вызов."""
        call_count = 0

        async def mock_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_200_response

        monkeypatch.setattr(router.http_client, "post", mock_post)

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek/deepseek-v4-flash",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
        )
        assert resp.status_code == 200
        assert call_count == 1  # нет fallback без роли
