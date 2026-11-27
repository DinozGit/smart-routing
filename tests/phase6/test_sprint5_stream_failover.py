"""
Phase 6 — Спринт 5 / A1 + A1b: streaming-failover и формат SSE-ошибки.

Контракт: ``docs/PROVIDER_CONTRACT.md`` → «🛡️ Спринт 5» → A1 (failover
«до первого байта»), A1b (объект ``error`` в SSE), A5 (тесты 8–11).

Главное правило: переключение на следующую модель цепочки разрешено **только**
пока клиенту не отправлен ни один байт. После первого чанка — честная ошибка
в SSE, без подмены модели.

Тесты не ходят в сеть: ``router.http_client.stream`` подменяется фейковым
async-контекст-менеджером; счётчик вызовов доказывает, вызывался ли второй
провайдер.
"""

import json
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


PRIMARY = "routerai::primary-model"
SECONDARY = "openrouter::secondary-model"


# ============================================================
# 🔧 Вспомогательные классы и функции
# ============================================================


class FakeStreamResponse:
    """Фейковый httpx.Response для streaming: чанки + опциональная ошибка."""

    def __init__(self, status_code=200, chunks=None, error=None):
        self.status_code = status_code
        self._chunks = list(chunks or [])
        self._error = error

    async def aread(self):
        return b'{"error": "provider boom"}'

    async def aiter_lines(self):
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


@contextmanager
def stream_patch(responses):
    """
    Подменяет ``http_client.stream`` последовательностью фейковых ответов.

    Возвращает список вызовов ``[(method, url, body_snapshot), ...]`` —
    по нему видно, сколько раз и к какому провайдеру шёл запрос.
    """
    queue = list(responses)
    calls = []

    def _stream(method, url, **kwargs):
        assert queue, f"Неожиданный вызов stream: {method} {url}"
        calls.append((method, url, dict(kwargs.get("json") or {})))
        response = queue.pop(0)
        cm = MagicMock()
        if isinstance(response, Exception):
            cm.__aenter__ = AsyncMock(side_effect=response)
        else:
            cm.__aenter__ = AsyncMock(return_value=response)
        cm.__aexit__ = AsyncMock(return_value=None)
        return cm

    with patch.object(router.http_client, "stream", MagicMock(side_effect=_stream)):
        yield calls


def _sse_payloads(text):
    """Все JSON-объекты из SSE-строк ``data: {...}``."""
    payloads = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payloads.append(json.loads(line[len("data: "):]))
        except json.JSONDecodeError:
            continue
    return payloads


def _sse_errors(text):
    """Поле ``error`` из всех SSE-событий, где оно есть."""
    return [p["error"] for p in _sse_payloads(text) if isinstance(p, dict) and "error" in p]


def _stream_body():
    return {
        "model": "SmartAuto",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
    }


# ============================================================
# 🔧 Фикстуры
# ============================================================


@pytest.fixture(autouse=True)
def sprint5_stream_env(clean_providers, monkeypatch):
    """
    Детерминированное окружение: coordinator → routerai, fallback → openrouter.

    Ключи обоих провайдеров задаются явно (корневой conftest их удаляет),
    чтобы streaming-ветка не уходила в «Missing API key».
    """
    monkeypatch.setenv("ROUTERAI_KEY", "fake-routerai-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-openrouter-key")

    router.state.default_provider = "routerai"
    router.state.config["role_models"] = {
        "coordinator": PRIMARY,
        "worker_default": PRIMARY,
        "worker_img": PRIMARY,
    }
    router.state.config["role_fallbacks"] = {"coordinator": [SECONDARY]}
    router.state.available_models = {}
    router.state.models_by_provider = {}


# ============================================================
# 8. Failover до первого байта
# ============================================================


class TestStreamFailoverBeforeFirstByte:
    """A5/8: 5xx до первого чанка → переход на следующую модель цепочки."""

    async def test_stream_failover_before_first_byte(self, client, caplog):
        first = FakeStreamResponse(status_code=503)
        second = FakeStreamResponse(
            chunks=[
                'data: {"choices": [{"delta": {"content": "hello from secondary"}}]}',
                "data: [DONE]",
            ]
        )

        with (
            caplog.at_level(logging.INFO, logger=router.logger.name),
            stream_patch([first, second]) as calls,
        ):
            resp = await client.post("/v1/chat/completions", json=_stream_body())

        assert resp.status_code == 200
        text = resp.text

        # Клиент получил данные ВТОРОЙ модели, ошибки в потоке нет
        assert "hello from secondary" in text
        assert "error" not in text.lower()

        # Оба провайдера были вызваны, в правильном порядке и с нужной моделью
        assert len(calls) == 2
        assert "routerai.ru" in calls[0][1]
        assert "openrouter.ai" in calls[1][1]
        assert calls[0][2]["model"] == "primary-model"
        assert calls[1][2]["model"] == "secondary-model"

        # A1: логи перехода и успешного fallback
        messages = [rec.getMessage() for rec in caplog.records]
        assert any("Stream fallback:" in m for m in messages)
        assert any("Stream fallback successful" in m for m in messages)


# ============================================================
# 9. Нет failover после первого байта
# ============================================================


class TestStreamNoFailoverAfterFirstByte:
    """A5/9: ошибка после первого чанка → SSE-ошибка, переключения нет."""

    async def test_stream_no_failover_after_first_byte(self, client):
        failing = FakeStreamResponse(
            chunks=['data: {"choices": [{"delta": {"content": "first-byte"}}]}'],
            error=httpx.ReadTimeout("connection lost"),
        )

        # Второй ответ намеренно не подготовлен: вызов второго провайдера
        # привёл бы к AssertionError в stream_patch.
        with stream_patch([failing]) as calls:
            resp = await client.post("/v1/chat/completions", json=_stream_body())

        assert resp.status_code == 200
        text = resp.text

        # Провайдер №2 не вызывался
        assert len(calls) == 1
        assert "routerai.ru" in calls[0][1]
        assert all("openrouter.ai" not in url for _, url, _ in calls)

        # Первый чанк дошёл до клиента, затем — ошибка в SSE
        assert "first-byte" in text
        errors = _sse_errors(text)
        assert len(errors) == 1
        assert errors[0]["type"] == "provider_error"
        assert errors[0]["code"] is None
        assert "ReadTimeout" in errors[0]["message"]


# ============================================================
# 10. Вся цепочка упала
# ============================================================


class TestStreamAllModelsFail:
    """A5/10: вся цепочка упала → в SSE объект ``error``."""

    async def test_stream_all_fail_yields_error(self, client):
        with stream_patch(
            [FakeStreamResponse(status_code=503), FakeStreamResponse(status_code=500)]
        ) as calls:
            resp = await client.post("/v1/chat/completions", json=_stream_body())

        assert resp.status_code == 200
        assert len(calls) == 2

        errors = _sse_errors(resp.text)
        assert len(errors) == 1
        assert isinstance(errors[0], dict)
        assert errors[0]["message"] == "Provider error 500"
        assert errors[0]["type"] == "provider_error"
        assert errors[0]["code"] == 500


# ============================================================
# 11. SSE-ошибка — объект, а не строка (A1b)
# ============================================================


class TestSseErrorShape:
    """A1b/A5-11: клиенты ждут ``{"error": {message, type, code}}``."""

    async def test_sse_error_is_object_not_string(self, client):
        """Явная спецификация → цепочка из одной модели; 429 → code == 429."""
        body = {
            "model": PRIMARY,
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        }

        with stream_patch([FakeStreamResponse(status_code=429)]) as calls:
            resp = await client.post("/v1/chat/completions", json=body)

        assert len(calls) == 1
        payloads = _sse_payloads(resp.text)
        assert len(payloads) == 1

        payload = payloads[0]
        assert "error" in payload
        assert isinstance(payload["error"], dict), "error должен быть объектом, не строкой"
        assert {"message", "type", "code"} <= set(payload["error"])
        assert payload["error"]["code"] == 429
        assert payload["error"]["type"] == "provider_error"
        assert payload["error"]["message"] == "Provider error 429"

    def test_sse_error_helper_format(self):
        """``_sse_error`` формирует валидную SSE-строку с объектом ошибки."""
        raw = router._sse_error("Provider error 429", "provider_error", 429)

        assert raw.startswith("data: ")
        assert raw.endswith("\n\n")

        payload = json.loads(raw[len("data: "):].strip())
        assert isinstance(payload["error"], dict)
        assert payload["error"] == {
            "message": "Provider error 429",
            "type": "provider_error",
            "code": 429,
        }
