"""
Phase 5 — тесты проксирования провайдеров: body["model"] без ::,
запрос к провайдеру модели, Ollama без ключа, 502 при отсутствии ключа,
extra_headers, GET /v1/models с составными ID, смена провайдера через POST /config.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


# ============================================================
# 🔧 Вспомогательные классы
# ============================================================


class MockResponse:
    """Фейковый httpx.Response для тестов proxy."""
    status_code = 200

    def raise_for_status(self):
        pass

    @staticmethod
    def json():
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


# ============================================================
# 🔧 Фикстуры
# ============================================================


@pytest.fixture
def fake_routerai_key(monkeypatch):
    """Подменяет ROUTERAI_KEY, чтобы не было 502."""
    monkeypatch.setenv("ROUTERAI_KEY", "fake-test-key-123")


@pytest.fixture
def fake_openrouter_key(monkeypatch):
    """Подменяет OPENROUTER_API_KEY для тестов."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-or-key-456")


@pytest.fixture(autouse=True)
def setup_openrouter_provider():
    """Добавляем OpenRouter как второго провайдера."""
    router.state.providers["openrouter"] = {
        "display_name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "models_endpoint": "https://openrouter.ai/api/v1/models",
        "api_key_env": "OPENROUTER_API_KEY",
        "requires_api_key": True,
        "pricing_mode": "auto",
        "default": False,
        "verify_ssl": True,
        "ca_bundle": "",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/smart-routing/smart-router",
            "X-Title": "SmartRouter",
        },
    }
    yield
    router.state.providers.pop("openrouter", None)


@pytest.fixture(autouse=True)
def setup_ollama_provider():
    """Добавляем Ollama как третьего провайдера (без ключа)."""
    router.state.providers["ollama"] = {
        "display_name": "Ollama (local)",
        "base_url": "http://localhost:11434/v1/chat/completions",
        "models_endpoint": "http://localhost:11434/api/tags",
        "api_key_env": "",
        "requires_api_key": False,
        "pricing_mode": "free",
        "default": False,
        "verify_ssl": True,
        "ca_bundle": "",
        "extra_headers": {},
    }
    yield
    router.state.providers.pop("ollama", None)


@pytest.fixture(autouse=True)
def setup_model_info():
    """Информация о модели для маршрутизации."""
    router.state.available_models = {
        "openrouter::deepseek/deepseek-chat": {
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek Chat",
            "context_length": 32768,
            "input_price_1m": 2.5,
            "output_price_1m": 10.0,
            "currency": "USD",
            "provider": "openrouter",
        },
        "routerai::deepseek/deepseek-v4-flash": {
            "id": "deepseek/deepseek-v4-flash",
            "name": "Flash",
            "context_length": 65536,
            "input_price_1m": 5.0,
            "output_price_1m": 10.0,
            "currency": "RUB",
            "provider": "routerai",
        },
        "ollama::llama3.2": {
            "id": "llama3.2",
            "name": "Llama 3.2",
            "context_length": 8192,
            "input_price_1m": 0.0,
            "output_price_1m": 0.0,
            "currency": "NONE",
            "provider": "ollama",
        },
    }
    router.state.models_by_provider = {
        "openrouter": ["deepseek/deepseek-chat"],
        "routerai": ["deepseek/deepseek-v4-flash"],
        "ollama": ["llama3.2"],
    }


@pytest.fixture
def mock_proxy_post():
    """Перехватывает http_client.post, возвращает фейковый ответ."""
    mock = AsyncMock(return_value=MockResponse())
    with patch.object(router.http_client, "post", mock):
        yield mock


# ============================================================
# body["model"] без :: у провайдера
# ============================================================


class TestModelFieldWithoutPrefix:
    """body["model"] у провайдера не содержит ::."""

    async def test_model_field_stripped_for_routerai(
        self, client, mock_proxy_post, fake_routerai_key
    ):
        """RouterAI: body["model"] не содержит ::."""
        body = {
            "model": "SmartAuto",
            "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        assert "::" not in sent_body["model"], (
            f"body.model содержит :: : {sent_body['model']}"
        )

    async def test_model_field_stripped_for_openrouter(
        self, client, mock_proxy_post, fake_openrouter_key
    ):
        """OpenRouter: body["model"] не содержит :: (через смену конфига)."""
        # Сначала меняем coordinator на OpenRouter-модель
        await client.post("/config", json={
            "role_models": {
                "coordinator": "openrouter::deepseek/deepseek-chat",
            },
        })
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        sent_body = call_kwargs["json"]
        assert "::" not in sent_body["model"]


# ============================================================
# Запрос к провайдеру модели
# ============================================================


class TestRequestGoesToModelProvider:
    """Запрос идёт на base_url провайдера модели (не дефолтного)."""

    async def test_request_to_openrouter_url(
        self, client, mock_proxy_post, fake_openrouter_key
    ):
        """OpenRouter-модель → запрос на base_url OpenRouter (через смену конфига)."""
        # Меняем coordinator на OpenRouter-модель
        await client.post("/config", json={
            "role_models": {
                "coordinator": "openrouter::deepseek/deepseek-chat",
            },
        })
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_url = mock_proxy_post.call_args[0][0]
        assert "openrouter.ai" in call_url, f"URL не OpenRouter: {call_url}"


# ============================================================
# Ollama — без API-ключа
# ============================================================


class TestOllamaNoApiKey:
    """Ollama (requires_api_key: false) → запрос без Authorization."""

    async def test_ollama_no_auth_header(self, client):
        """Ollama-запрос не содержит Authorization."""
        # Меняем coordinator на Ollama-модель
        await client.post("/config", json={
            "role_models": {
                "coordinator": "ollama::llama3.2",
            },
        })
        mock = AsyncMock(return_value=MockResponse())
        with patch.object(router.http_client, "post", mock):
            body = {
                "model": "SmartAuto",
                "messages": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "hello"},
                ],
            }
            resp = await client.post("/v1/chat/completions", json=body)
            assert resp.status_code == 200

            call_kwargs = mock.call_args[1]
            headers = call_kwargs.get("headers", {})
            auth = headers.get("Authorization", "")
            assert auth == "", f"Ollama запрос содержит Authorization: {auth}"

    async def test_ollama_no_502_missing_key(self, client):
        """Ollama без ключа → 200, не 502."""
        await client.post("/config", json={
            "role_models": {
                "coordinator": "ollama::llama3.2",
            },
        })
        mock = AsyncMock(return_value=MockResponse())
        with patch.object(router.http_client, "post", mock):
            body = {
                "model": "SmartAuto",
                "messages": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "hello"},
                ],
            }
            resp = await client.post("/v1/chat/completions", json=body)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


# ============================================================
# Провайдер с ключом, но без ключа в env → 502
# ============================================================


class TestMissingApiKey:
    """Провайдер с requires_api_key: true, но без ключа в env → 502."""

    async def test_missing_key_returns_502(self, client, monkeypatch):
        """OpenRouter без ключа → 502 (и RouterAI тоже без ключа, чтобы fallback не сработал)."""
        # Убираем оба ключа из окружения (они есть в .env)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("ROUTERAI_KEY", raising=False)
        # Меняем coordinator на OpenRouter-модель
        await client.post("/config", json={
            "role_models": {
                "coordinator": "openrouter::deepseek/deepseek-chat",
            },
        })
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 502, f"Expected 502, got {resp.status_code}"
        data = resp.json()
        assert "API key" in str(data.get("detail", ""))


# ============================================================
# extra_headers провайдера
# ============================================================


class TestExtraHeaders:
    """extra_headers провайдера попадают в заголовки запроса."""

    async def test_openrouter_extra_headers(
        self, client, mock_proxy_post, fake_openrouter_key
    ):
        """OpenRouter: extra_headers (HTTP-Referer, X-Title) присутствуют."""
        # Меняем coordinator на OpenRouter-модель
        await client.post("/config", json={
            "role_models": {
                "coordinator": "openrouter::deepseek/deepseek-chat",
            },
        })
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_kwargs = mock_proxy_post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert headers.get("HTTP-Referer") == "https://github.com/smart-routing/smart-router"
        assert headers.get("X-Title") == "SmartRouter"


# ============================================================
# GET /v1/models — составные ID
# ============================================================


class TestV1ModelsCompositeIds:
    """GET /v1/models возвращает составные ID provider::model_id."""

    async def test_v1_models_has_composite_ids(self, client):
        """ID моделей содержат ::."""
        resp = await client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        for model in data["data"]:
            assert "::" in model["id"], (
                f"ID не составной: {model['id']}"
            )

    async def test_v1_models_provider_prefix(self, client):
        """ID начинается с имени провайдера."""
        resp = await client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        # config.yaml модели имеют префикс default_provider
        assert any(i.startswith("routerai::") for i in ids)


# ============================================================
# Смена провайдера через POST /config
# ============================================================


class TestConfigChangeProvider:
    """Смена role_models через POST /config → запрос к новому провайдеру."""

    async def test_config_change_redirects_to_new_provider(
        self, client, mock_proxy_post, fake_openrouter_key
    ):
        """После смены coordinator на openrouter-модель, запрос идёт к OpenRouter."""
        # Меняем coordinator на openrouter-модель через POST /config
        new_config = {
            "role_models": {
                "coordinator": "openrouter::deepseek/deepseek-chat",
            },
        }
        resp = await client.post("/config", json=new_config)
        assert resp.status_code == 200

        # Теперь запрос без агента → coordinator → openrouter
        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        # Проверяем, что запрос ушёл на OpenRouter
        call_url = mock_proxy_post.call_args[0][0]
        assert "openrouter.ai" in call_url, (
            f"URL не OpenRouter после смены конфига: {call_url}"
        )

    async def test_config_change_no_restart_needed(
        self, client, mock_proxy_post, fake_openrouter_key
    ):
        """Смена провайдера работает без рестарта — второй запрос сразу к новому."""
        new_config = {
            "role_models": {
                "coordinator": "openrouter::deepseek/deepseek-chat",
            },
        }
        await client.post("/config", json=new_config)

        body = {
            "model": "SmartAuto",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "test without restart"},
            ],
        }
        resp = await client.post("/v1/chat/completions", json=body)
        assert resp.status_code == 200

        call_url = mock_proxy_post.call_args[0][0]
        assert "openrouter.ai" in call_url