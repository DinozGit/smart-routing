"""
Phase 3 — тесты применения Fine Tuning в proxy.

Проверяем, что в эндпоинте POST /v1/chat/completions:
- Default-параметры (temperature, top_p и др.) добавляются если клиент их не указал
- Если клиент указал temperature — НЕ перезаписываем
- max_tokens капается до context_length модели
- system_prompt_prefix добавляется перед system сообщением
- Если system сообщения нет — создаётся новое
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router

# Дефолтный tuning для тестов
BASE_TUNING = {
    "coordinator": {
        "temperature": 0.7,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "system_prompt_prefix": "",
    },
    "worker_default": {
        "temperature": 0.3,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "system_prompt_prefix": "Ты отвечаешь на русском языке.",
    },
    "worker_img": {
        "temperature": 0.5,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "system_prompt_prefix": "",
    },
}

# Мок-ответ от провайдера
MOCK_PROVIDER_RESPONSE = {
    "choices": [{"message": {"content": "ok"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}

# Мок-информация о модели (для context_length)
MOCK_MODEL_INFO = {
    "id": "deepseek/deepseek-v4-flash",
    "name": "Flash",
    "context_length": 4096,
    "input_price_1m": 1.0,
    "output_price_1m": 2.0,
}


@pytest.fixture(autouse=True)
def setup_role_tuning():
    """Добавляет role_tuning в state.config."""
    router.state.config["role_tuning"] = BASE_TUNING


@pytest.fixture(autouse=True)
def setup_model_info():
    """Добавляет информацию о модели в кеш."""
    router.state.available_models = {
        "deepseek/deepseek-v4-flash": MOCK_MODEL_INFO,
    }


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    """Подменяет ROUTERAI_KEY, чтобы не было 502."""
    monkeypatch.setenv("ROUTERAI_KEY", "fake-test-key-123")


@pytest.fixture
def mock_proxy_post():
    """
    Перехватывает http_client.post, возвращает фейковый ответ,
    но даёт доступ к body, с которым был вызван post.
    """
    mock = AsyncMock(return_value=MockResponse())
    with patch.object(router.http_client, "post", mock):
        yield mock


class MockResponse:
    """Фейковый httpx.Response для тестов proxy."""

    status_code = 200

    def raise_for_status(self):
        pass

    @staticmethod
    def json():
        return MOCK_PROVIDER_RESPONSE


class TestTuningAppliesDefaults:
    """Tuning применяет дефолтные параметры если клиент их не указал."""

    async def test_tuning_applies_default_temperature(self, client, mock_proxy_post):
        """Если body без temperature, добавляется из role_tuning (worker_default → 0.3)."""
        body = {
            "model": "SmartAuto",
            "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        # Проверяем, что temperature был добавлен
        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        assert sent_body["temperature"] == 0.3

    async def test_tuning_does_not_override_client_temperature(
        self, client, mock_proxy_post
    ):
        """Если Zed прислал temperature, НЕ перезаписываем."""
        body = {
            "model": "SmartAuto",
            "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
            "temperature": 0.9,
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        # Должен остаться 0.9, а не 0.3 (worker_default)
        assert sent_body["temperature"] == 0.9

    async def test_tuning_applies_top_p_default(self, client, mock_proxy_post):
        """top_p добавляется если не указан."""
        body = {
            "model": "SmartAuto",
            "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        assert sent_body["top_p"] == 0.9


class TestTuningCapsMaxTokens:
    """Tuning автоматически капает max_tokens."""

    async def test_tuning_caps_max_tokens(self, client, mock_proxy_post):
        """Если max_tokens > context_length, капаем до context_length."""
        body = {
            "model": "SmartAuto",
            "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
            "max_tokens": 99999,
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        # context_length = 4096
        assert sent_body["max_tokens"] == 4096

    async def test_tuning_does_not_cap_when_below_limit(self, client, mock_proxy_post):
        """Если max_tokens в пределах — не трогаем."""
        body = {
            "model": "SmartAuto",
            "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
            "max_tokens": 1000,
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        assert sent_body["max_tokens"] == 1000


class TestTuningSystemPromptPrefix:
    """Tuning добавляет system_prompt_prefix."""

    async def test_tuning_prepends_system_prompt_prefix(self, client, mock_proxy_post):
        """prefix добавляется перед system сообщением."""
        # worker_default имеет prefix "Ты отвечаешь на русском языке."
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "Будь полезным ассистентом."},
                {"role": "user", "content": "[AGENT:database] hello"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        messages = sent_body["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"].startswith("Ты отвечаешь на русском языке.")

    async def test_tuning_inserts_system_if_none(self, client, mock_proxy_post):
        """Если нет system сообщения — создаётся."""
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "user", "content": "[AGENT:database] hello"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        messages = sent_body["messages"]
        # Должно быть 2 сообщения: новое system + user
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Ты отвечаешь на русском языке."
        assert messages[1]["role"] == "user"

    async def test_tuning_prefix_does_not_apply_on_empty_prefix(
        self, client, mock_proxy_post
    ):
        """Если prefix пустая строка — system сообщение не меняется."""
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "Будь полезным ассистентом."},
                {"role": "user", "content": "[AGENT:database] hello"},
            ],
        }
        # Устанавливаем пустой prefix для worker_default
        router.state.config["role_tuning"]["worker_default"]["system_prompt_prefix"] = (
            ""
        )
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        messages = sent_body["messages"]
        assert messages[0]["content"] == "Будь полезным ассистентом."


class TestTuningCoordinatorDefaults:
    """Coordinator tuning применяется для запросов без агента."""

    async def test_tuning_coordinator_default_temperature(
        self, client, mock_proxy_post
    ):
        """Запрос без агента → coordinator → temperature 0.7."""
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello world"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        # coordinator temperature = 0.7
        assert sent_body["temperature"] == 0.7
