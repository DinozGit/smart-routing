"""
Phase 4 — тесты transport-hardening: ретраи, SSL-клиенты, таймауты.

Проверяем:
- post_with_retry: повторы, экспоненциальная задержка, не-retryable ошибки
- get_provider_client: SSL-контексты, кэширование, инвалидация
- Streaming-ретраи: повторы до отправки данных, отсутствие повторов после
- Сообщения об ошибках в SSE содержат тип исключения
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


# ============================================================
# 🔧 Вспомогательные классы
# ============================================================


class MockResponse:
    """Фейковый httpx.Response для тестов post_with_retry."""

    status_code = 200

    def raise_for_status(self):
        pass

    @staticmethod
    def json():
        return {"choices": [{"message": {"content": "ok"}}]}


class MockStreamResponse:
    """Фейковый httpx.Response для streaming-тестов (успех)."""

    status_code = 200

    def __init__(self, chunks=None):
        self._chunks = chunks or [
            'data: {"choices": [{"delta": {"content": "hello"}}]}',
            "data: [DONE]",
        ]

    async def aiter_lines(self):
        for chunk in self._chunks:
            yield chunk


class MockStreamResponseFailsAfter:
    """Фейковый httpx.Response: отдаёт чанк, потом бросает исключение."""

    status_code = 200

    def __init__(self, error=None):
        self._error = error or httpx.ReadTimeout("connection lost")

    async def aiter_lines(self):
        yield 'data: {"choices": [{"delta": {"content": "hello"}}]}'
        raise self._error


# ============================================================
# 🔧 Фикстуры
# ============================================================


@pytest.fixture(autouse=True)
def clean_provider_clients():
    """Очищает кэш SSL-клиентов перед каждым тестом."""
    router._provider_clients.clear()


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    """Подменяет ROUTERAI_KEY, чтобы не было 502."""
    monkeypatch.setenv("ROUTERAI_KEY", "fake-test-key-123")


@pytest.fixture(autouse=True)
def fake_sleep():
    """Подменяет asyncio.sleep на мок, чтобы тесты были быстрыми."""
    with patch.object(router.asyncio, "sleep", AsyncMock()):
        yield


@pytest.fixture
def save_providers():
    """Сохраняет и восстанавливает state.providers."""
    original = dict(router.state.providers)
    yield
    router.state.providers.clear()
    router.state.providers.update(original)


# ============================================================
# A. post_with_retry
# ============================================================


class TestPostWithRetry:
    """post_with_retry: повторы, задержки, обработка ошибок."""

    async def test_success_first_attempt(self):
        """Успех с первой попытки → возвращает ответ, post вызван 1 раз."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MockResponse()
        mock_client.post = AsyncMock(return_value=mock_response)

        resp = await router.post_with_retry(mock_client, "http://test", {}, {})

        assert resp is mock_response
        assert mock_client.post.call_count == 1

    async def test_retry_then_success(self):
        """ConnectError на первой попытке, успех на второй → возвращает ответ, post вызван 2 раза."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MockResponse()
        mock_client.post = AsyncMock(
            side_effect=[httpx.ConnectError("first fail"), mock_response]
        )

        resp = await router.post_with_retry(mock_client, "http://test", {}, {})

        assert resp is mock_response
        assert mock_client.post.call_count == 2

    async def test_all_attempts_fail(self):
        """ConnectError всегда → исключение пробрасывается наружу, post вызван RETRY_ATTEMPTS раз."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("always fail"))

        with pytest.raises(httpx.ConnectError, match="always fail"):
            await router.post_with_retry(mock_client, "http://test", {}, {})

        assert mock_client.post.call_count == router.RETRY_ATTEMPTS

    async def test_attempts_param_one(self):
        """attempts=1 → без повторов, 1 вызов."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("fail"))

        with pytest.raises(httpx.ConnectError):
            await router.post_with_retry(
                mock_client, "http://test", {}, {}, attempts=1
            )

        assert mock_client.post.call_count == 1

    async def test_non_retryable_error(self):
        """Не-retryable ошибка (HTTPStatusError) → повторов нет, 1 вызов."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "400", request=MagicMock(), response=MagicMock()
            )
        )

        with pytest.raises(httpx.HTTPStatusError):
            await router.post_with_retry(mock_client, "http://test", {}, {})

        assert mock_client.post.call_count == 1

    async def test_exponential_backoff(self):
        """Задержки растут экспоненциально: sleep вызывается с 0.7 и 1.4."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("fail"))

        mock_sleep = AsyncMock()
        with patch.object(router.asyncio, "sleep", mock_sleep):
            with pytest.raises(httpx.ConnectError):
                await router.post_with_retry(mock_client, "http://test", {}, {})

        # RETRY_ATTEMPTS=3 → 3 попытки, 2 сна: backoff и backoff*2
        assert mock_sleep.call_count == 2
        backoff = router.RETRY_BACKOFF
        mock_sleep.assert_has_calls([call(backoff), call(backoff * 2)])


# ============================================================
# B. get_provider_client
# ============================================================


class TestGetProviderClient:
    """get_provider_client: SSL-контексты, кэширование, инвалидация."""

    def test_default_no_ssl_settings(self, save_providers):
        """Провайдер без SSL-настроек → возвращается router.http_client."""
        router.state.providers["test_provider"] = {}
        client = router.get_provider_client("test_provider")
        assert client is router.http_client

    def test_verify_ssl_false(self, save_providers):
        """Провайдер с verify_ssl: False → отдельный клиент, кэшируется."""
        router.state.providers["test_provider"] = {"verify_ssl": False}

        with patch("ssl.create_default_context", return_value=MagicMock()):
            client1 = router.get_provider_client("test_provider")
            client2 = router.get_provider_client("test_provider")

        assert client1 is not router.http_client
        assert client1 is client2  # кэш

    def test_ca_bundle(self, save_providers):
        """Провайдер с ca_bundle → отдельный клиент (не глобальный)."""
        router.state.providers["test_provider"] = {"ca_bundle": "/fake/ca.pem"}

        with patch("ssl.create_default_context", return_value=MagicMock()):
            client = router.get_provider_client("test_provider")

        assert client is not router.http_client

    def test_invalidate_clients(self, save_providers):
        """invalidate_provider_clients сбрасывает кэш для провайдера."""
        router.state.providers["test_provider"] = {"verify_ssl": False}

        with patch("ssl.create_default_context", return_value=MagicMock()):
            client1 = router.get_provider_client("test_provider")
            router.invalidate_provider_clients("test_provider")
            client2 = router.get_provider_client("test_provider")

        assert client1 is not client2


# ============================================================
# C. Streaming-ретраи
# ============================================================


class TestStreamingRetry:
    """Streaming-ретраи в эндпоинте POST /v1/chat/completions."""

    async def test_streaming_retry_then_success(self, client, save_providers):
        """Первый stream бросает ConnectError, второй успешен → SSE-чанки, ошибок нет."""
        router.state.providers["routerai"] = {}

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(
            side_effect=[
                httpx.ConnectError("connection refused"),
                MockStreamResponse(),
            ]
        )
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(router.http_client, "stream", return_value=mock_cm):
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "SmartAuto",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )

        assert resp.status_code == 200
        text = resp.text
        # Должны быть SSE-события, без ошибок
        assert "error" not in text.lower()
        assert "hello" in text
        # stream открыт 2 раза (первый раз упал, второй успешен)
        assert mock_cm.__aenter__.call_count == 2

    async def test_streaming_no_retry_after_sent(self, client, save_providers):
        """Ошибка ПОСЛЕ отправки чанка → повтора НЕТ, stream открыт 1 раз."""
        router.state.providers["routerai"] = {}

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(
            return_value=MockStreamResponseFailsAfter()
        )
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(router.http_client, "stream", return_value=mock_cm):
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "SmartAuto",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )

        assert resp.status_code == 200
        text = resp.text
        # Должна быть ошибка в SSE (ReadTimeout)
        assert "error" in text.lower()
        assert "ReadTimeout" in text
        # stream открыт ровно 1 раз (повтора не было)
        assert mock_cm.__aenter__.call_count == 1


# ============================================================
# D. Сообщение об ошибке
# ============================================================


class TestErrorMessage:
    """Сообщение об ошибке в SSE содержит тип исключения."""

    async def test_error_contains_exception_type(self, client, save_providers):
        """При неустранимой сетевой ошибке SSE содержит тип исключения, не 'Internal Proxy Error'."""
        router.state.providers["routerai"] = {}

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(
            side_effect=httpx.ConnectError("DNS resolution failed")
        )
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch.object(router.http_client, "stream", return_value=mock_cm):
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "SmartAuto",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                },
            )

        assert resp.status_code == 200
        text = resp.text
        # Должен быть тип исключения, а не "Internal Proxy Error"
        assert "ConnectError" in text
        assert "Internal Proxy Error" not in text