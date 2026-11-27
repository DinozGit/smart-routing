"""
Phase 6 — Спринт 5 / A4 + A5: ``max_tokens`` на роль и cap по контексту модели.

Контракт: ``docs/PROVIDER_CONTRACT.md`` → «🛡️ Спринт 5» → A4 (формула cap,
применение в proxy, поля ``GET /roles/{name}/tuning``) и A5 (тесты 1–6).

Проверяем:
- cap считается по ``context_length`` модели **её собственного** провайдера;
- ``max_tokens_cap == int(context_length * 0.6)`` для трёх провайдеров;
- при ``max_tokens: null`` → ``max_tokens_effective == min(cap, 16384)``;
- клиент прислал меньше cap — значение уважается, больше — режется до cap;
- ``role == ""`` (явная спецификация) — ``max_tokens`` не добавляется.

Все изменения конфига — in-memory; запись конфига (если случится) идёт в tmp
через ``tests/phase6/conftest.py::sprint5_config_guard``.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


# Tuning без max_tokens — «авто» (null), как в контракте A4.
BASE_TUNING = {
    "coordinator": {
        "temperature": 0.7,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "system_prompt_prefix": "",
        "max_tokens": None,
    },
    "worker_default": {
        "temperature": 0.3,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "system_prompt_prefix": "",
        "max_tokens": None,
    },
    "worker_img": {
        "temperature": 0.5,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "system_prompt_prefix": "",
        "max_tokens": None,
    },
}


class MockProviderResponse:
    """Фейковый httpx.Response для non-streaming proxy."""

    status_code = 200

    def raise_for_status(self):
        pass

    @staticmethod
    def json():
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }


@pytest.fixture(autouse=True)
def setup_role_tuning():
    """role_tuning не попадает в tmp routing.json из корневого conftest."""
    router.state.config["role_tuning"] = {
        role: dict(tuning) for role, tuning in BASE_TUNING.items()
    }


@pytest.fixture
def provider_keys(monkeypatch):
    """Ключи провайдеров, чтобы proxy не отдавал 502."""
    monkeypatch.setenv("ROUTERAI_KEY", "fake-routerai-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-openrouter-key")


@pytest.fixture
def mock_provider_post():
    """Перехватывает http_client.post и даёт доступ к отправленному body."""
    mock = AsyncMock(return_value=MockProviderResponse())
    with patch.object(router.http_client, "post", mock):
        yield mock


def _install_catalog(entries):
    """Заполняет каталог моделей: entries = [(provider, model_id, context_length)]."""
    router.state.available_models = {}
    router.state.models_by_provider = {}
    for provider, model_id, context_length in entries:
        router.state.available_models[f"{provider}::{model_id}"] = {
            "id": model_id,
            "provider": provider,
            "context_length": context_length,
            "currency": "RUB",
        }
        router.state.models_by_provider.setdefault(provider, []).append(model_id)


def _set_role_models(mapping):
    """Подменяет role_models в runtime-конфиге (in-memory, без записи на диск)."""
    role_models = dict(router.state.config.get("role_models", {}))
    role_models.update(mapping)
    router.state.config["role_models"] = role_models


def _sent_body(mock_post):
    """Body, с которым proxy обратился к провайдеру."""
    return mock_post.call_args[1]["json"]


# ============================================================
# 1. Cap берётся у модели своего провайдера
# ============================================================


class TestCapUsesModelOwnProvider:
    """A5/1: ``get_model_info("openrouter::X")`` — контекст именно openrouter."""

    async def test_cap_uses_model_own_provider(self, client, clean_providers):
        # Одна и та же модель у двух провайдеров с РАЗНЫМ контекстом.
        _install_catalog(
            [
                ("routerai", "shared/model", 100_000),
                ("openrouter", "shared/model", 200_000),
            ]
        )
        _set_role_models({"coordinator": "openrouter::shared/model"})

        # 1. Прямой вызов каталога по составному ключу
        info = router.state.get_model_info("openrouter::shared/model")
        assert info is not None
        assert info["provider"] == "openrouter"
        assert info["context_length"] == 200_000

        # 2. Тот же вызов с явным provider
        info_explicit = router.state.get_model_info(
            "shared/model", provider="openrouter"
        )
        assert info_explicit is not None
        assert info_explicit["context_length"] == 200_000

        # 3. Cap роли считается по контексту openrouter, а не routerai
        data = (await client.get("/roles/coordinator/tuning")).json()
        assert data["provider"] == "openrouter"
        assert data["context_limit"] == 200_000
        assert data["max_tokens_cap"] == int(200_000 * 0.6)


# ============================================================
# 2. cap = 60% контекста для трёх провайдеров
# ============================================================


class TestMaxTokensCapFormula:
    """A5/2: ``max_tokens_cap == int(context_length * 0.6)``."""

    async def test_max_tokens_cap_60_percent(self, client, clean_providers):
        _install_catalog(
            [
                ("routerai", "coord-model", 1000),
                ("openrouter", "worker-model", 2000),
                ("ollama", "img-model", 500),
            ]
        )
        _set_role_models(
            {
                "coordinator": "routerai::coord-model",
                "worker_default": "openrouter::worker-model",
                "worker_img": "ollama::img-model",
            }
        )

        expected = {
            "coordinator": ("routerai", 1000),
            "worker_default": ("openrouter", 2000),
            "worker_img": ("ollama", 500),
        }
        for role, (provider, context_length) in expected.items():
            data = (await client.get(f"/roles/{role}/tuning")).json()
            assert data["provider"] == provider, role
            assert data["context_limit"] == context_length, role
            assert data["max_tokens_cap"] == int(context_length * 0.6), role


# ============================================================
# 3. Дефолтный max_tokens = min(cap, 16384)
# ============================================================


class TestDefaultMaxTokens:
    """A5/3: при ``max_tokens: null`` → ``min(cap, 16384)``."""

    async def test_default_max_tokens_is_min_of_cap_and_16384(
        self, client, clean_providers
    ):
        assert router.DEFAULT_MAX_TOKENS == 16384

        _install_catalog(
            [
                # cap = 157286 > 16384
                ("routerai", "big-model", 262_144),
                # cap = 2457 < 16384
                ("openrouter", "small-model", 4096),
            ]
        )
        _set_role_models(
            {
                "coordinator": "routerai::big-model",
                "worker_default": "openrouter::small-model",
            }
        )

        for role in ("coordinator", "worker_default"):
            data = (await client.get(f"/roles/{role}/tuning")).json()
            assert data["max_tokens"] is None, role
            cap = data["max_tokens_cap"]
            assert data["max_tokens_effective"] == min(cap, 16384), role

        big = (await client.get("/roles/coordinator/tuning")).json()
        small = (await client.get("/roles/worker_default/tuning")).json()
        assert big["max_tokens_cap"] == 157_286
        assert big["max_tokens_effective"] == 16384
        assert small["max_tokens_cap"] == 2457
        assert small["max_tokens_effective"] == 2457


# ============================================================
# 4–5. Применение max_tokens в proxy
# ============================================================


class TestProxyMaxTokens:
    """A5/4–5: клиентское значение уважается до cap, выше cap — режется."""

    @pytest.fixture(autouse=True)
    def worker_role(self, clean_providers):
        # cap = int(10000 * 0.6) = 6000
        _install_catalog([("routerai", "worker-model", 10_000)])
        _set_role_models({"worker_default": "routerai::worker-model"})

    async def test_client_smaller_value_kept(
        self, client, provider_keys, mock_provider_post
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
                "max_tokens": 500,
            },
        )
        assert resp.status_code == 200
        assert _sent_body(mock_provider_post)["max_tokens"] == 500

    async def test_client_larger_value_capped(
        self, client, provider_keys, mock_provider_post
    ):
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
                "max_tokens": 999_999,
            },
        )
        assert resp.status_code == 200
        assert _sent_body(mock_provider_post)["max_tokens"] == 6000


class TestProxyDefaultMaxTokens:
    """A4: клиент молчит — proxy подставляет effective по формуле."""

    @pytest.mark.parametrize(
        "context_length, expected",
        [
            (262_144, 16384),  # cap 157286 → ограничивает DEFAULT_MAX_TOKENS
            (4096, 2457),  # cap 2457 → ограничивает контекст модели
        ],
    )
    async def test_proxy_applies_effective_when_client_silent(
        self,
        client,
        clean_providers,
        provider_keys,
        mock_provider_post,
        context_length,
        expected,
    ):
        _install_catalog([("routerai", "worker-model", context_length)])
        _set_role_models({"worker_default": "routerai::worker-model"})

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
            },
        )
        assert resp.status_code == 200
        assert _sent_body(mock_provider_post)["max_tokens"] == expected

    async def test_configured_max_tokens_applied_and_capped(
        self, client, clean_providers, provider_keys, mock_provider_post
    ):
        """max_tokens из tuning: меньше cap — как есть, больше — режется."""
        _install_catalog([("routerai", "worker-model", 10_000)])  # cap 6000
        _set_role_models({"worker_default": "routerai::worker-model"})

        router.state.config["role_tuning"]["worker_default"]["max_tokens"] = 4000
        await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
            },
        )
        assert _sent_body(mock_provider_post)["max_tokens"] == 4000

        router.state.config["role_tuning"]["worker_default"]["max_tokens"] = 50_000
        await client.post(
            "/v1/chat/completions",
            json={
                "model": "SmartAuto",
                "messages": [{"role": "user", "content": "[AGENT:database] hello"}],
            },
        )
        assert _sent_body(mock_provider_post)["max_tokens"] == 6000


# ============================================================
# 6. Явная спецификация (role == "") — max_tokens не трогаем
# ============================================================


class TestExplicitSpecNoMaxTokens:
    """A5/6: ``role == ""`` → ``max_tokens`` не добавляется в тело запроса."""

    async def test_no_max_tokens_when_role_empty(
        self, client, clean_providers, provider_keys, mock_provider_post
    ):
        _install_catalog([("routerai", "explicit-model", 10_000)])

        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "routerai::explicit-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 200

        sent = _sent_body(mock_provider_post)
        assert sent["model"] == "explicit-model"
        assert "max_tokens" not in sent
