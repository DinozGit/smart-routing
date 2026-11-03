"""
Phase 6 — F2: enabled-флаг провайдера (выключить провайдера без удаления).

Контракт: docs/PROVIDER_CONTRACT.md, раздел F2, тесты 5–9, 13–14.

- GET /v1/models не отдаёт модели выключенного провайдера.
- Sync-all пропускает выключенных (status=skipped, reason=disabled), сеть
  на них не ходит; итоговый status = "ok".
- POST /models/sync {"provider": "X"} для выключенного → 409.
- Явный запрос disabled::model → 400.
- Fallback-цепочка не ходит на выключенного провайдера (запись пропускается).
- GET /providers содержит enabled: bool.
- default_provider нельзя выключить → 400.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class MockSyncResponse:
    """Фейковый ответ GET /v1/models провайдера для sync-тестов (без сети)."""

    status_code = 200

    def raise_for_status(self):
        pass

    @staticmethod
    def json():
        return {"data": []}


class Mock500Response:
    """
    Фейковый HTTP-ответ 500 — срабатывание fallback-цепочки.

    raise_for_status() бросает httpx.HTTPStatusError(cod=500), чтобы основной
    провайдер «упал» и цепочка перешла к следующей записи.
    """

    status_code = 500

    def raise_for_status(self):
        request = httpx.Request("POST", "http://routerai.test")
        response = httpx.Response(500, request=request)
        raise httpx.HTTPStatusError(
            "Server error", request=request, response=response
        )


class TestF2DisabledProvider:
    """F2: поведение enabled=false в API."""

    def _catalog_with_disabled_openrouter(self):
        """Каталог: routerai включён, openrouter выключен."""
        router.state.default_provider = "routerai"
        router.state.models_by_provider = {
            "routerai": ["deepseek/deepseek-v4-flash"],
            "openrouter": ["deepseek/deepseek-chat"],
        }
        router.state.available_models = {
            "routerai::deepseek/deepseek-v4-flash": {
                "id": "deepseek/deepseek-v4-flash",
                "provider": "routerai",
                "name": "Flash",
            },
            "openrouter::deepseek/deepseek-chat": {
                "id": "deepseek/deepseek-chat",
                "provider": "openrouter",
                "name": "DeepSeek Chat",
            },
        }

    async def test_disabled_provider_not_in_v1_models(self, client, disable_provider):
        """GET /v1/models не содержит моделей выключенного провайдера."""
        disable_provider("openrouter")
        self._catalog_with_disabled_openrouter()

        resp = await client.get("/v1/models")
        assert resp.status_code == 200
        ids = [m["id"] for m in resp.json()["data"]]
        assert not any(i.startswith("openrouter::") for i in ids), ids
        assert "routerai::deepseek/deepseek-v4-flash" in ids

    async def test_disabled_provider_skipped_in_sync_all(
        self, client, disable_provider, monkeypatch
    ):
        """Sync-all: выключенный → skipped/disabled, сеть не опрашивается, status=ok."""
        disable_provider("openrouter")
        monkeypatch.setenv("ROUTERAI_KEY", "fake-ra-key")

        mock_get = AsyncMock(return_value=MockSyncResponse())
        with patch.object(router.http_client, "get", mock_get):
            resp = await client.post("/models/sync", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["results"]["openrouter"] == {
            "status": "skipped",
            "reason": "disabled",
            "synced": 0,
            "last_sync": None,
        }
        # Ни один HTTP-запрос не ушёл на выключенный openrouter
        assert mock_get.call_args_list, "sync-all не дёрнул ни одного провайдера"
        assert all(
            "openrouter" not in str(call.args[0])
            for call in mock_get.call_args_list
        )

    async def test_sync_disabled_provider_returns_409(self, client, disable_provider):
        """POST /models/sync {"provider": "openrouter"} для выключенного → 409."""
        disable_provider("openrouter")

        mock_get = AsyncMock()
        with patch.object(router.http_client, "get", mock_get):
            resp = await client.post("/models/sync", json={"provider": "openrouter"})

        assert resp.status_code == 409
        assert resp.json()["detail"] == "Provider 'openrouter' is disabled"
        mock_get.assert_not_awaited()

    async def test_disabled_provider_explicit_request_400(self, client, disable_provider):
        """Явный запрос openrouter::model при выключенном openrouter → 400."""
        disable_provider("openrouter")

        mock_post = AsyncMock()
        with patch.object(router.http_client, "post", mock_post):
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "openrouter::deepseek/deepseek-chat",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Provider 'openrouter' is disabled"
        mock_post.assert_not_awaited()

    async def test_disabled_provider_skipped_in_fallback(
        self, client, disable_provider, monkeypatch
    ):
        """Fallback на выключенного провайдера: запись пропускается (без сети)."""
        disable_provider("openrouter")
        monkeypatch.setenv("ROUTERAI_KEY", "fake-ra-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-or-key")
        # Основная модель — на включённом routerai, fallback — на выключенном openrouter
        router.state.config["role_models"] = {
            "coordinator": "routerai::deepseek/deepseek-v4-flash"
        }
        router.state.config["role_fallbacks"] = {
            "coordinator": "openrouter::deepseek/deepseek-chat"
        }

        # Основной провайдер отвечает 500 → цепочка должна перейти к fallback
        mock_post = AsyncMock(return_value=Mock500Response())
        with patch.object(router.http_client, "post", mock_post):
            resp = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "SmartAuto",
                    "messages": [
                        {"role": "system", "content": "You are helpful."},
                        {"role": "user", "content": "hello"},
                    ],
                },
            )

        # Выключенный fallback-провайдер последний в цепочке → 502 с понятным detail
        assert resp.status_code == 502
        assert "Provider 'openrouter' is disabled" in str(
            resp.json().get("detail", "")
        )
        # В сеть ходили только на routerai; на openrouter — ни одного запроса
        assert mock_post.await_count == 1
        url = str(mock_post.call_args_list[0].args[0])
        assert "routerai.ru" in url
        assert "openrouter.ai" not in url

    async def test_providers_response_has_enabled(self, client, clean_providers):
        """GET /providers → у каждого провайдера поле enabled: bool."""
        resp = await client.get("/providers")
        assert resp.status_code == 200
        providers = resp.json()["providers"]
        assert providers
        for name, p in providers.items():
            assert "enabled" in p, f"У провайдера '{name}' нет поля enabled"
            assert isinstance(p["enabled"], bool)

    async def test_default_provider_cannot_be_disabled(self, client, clean_providers):
        """Попытка выключить default_provider → 400."""
        resp = await client.post(
            "/providers",
            json={
                "name": "routerai",
                "display_name": "RouterAI",
                "base_url": "https://routerai.ru/api/v1/chat/completions",
                "api_key_env": "ROUTERAI_KEY",
                "models_endpoint": "https://routerai.ru/api/v1/models",
                "enabled": False,
                "default": True,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot disable default provider 'routerai'"