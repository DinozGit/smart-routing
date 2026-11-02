"""
Phase 2.5 — тесты управления моделями через админку.

Проверяем:
- Загрузка кеша из models_cache.json
- GET /models/available — список моделей
- POST /models/sync — синхронизация с RouterAI
- GET /v1/models — объединение config.yaml + кеш
- log_usage — цены из кеша если нет в PRICES
- Повреждённый кеш → fallback на config.yaml
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestModelsCache:
    """Загрузка и работа с models_cache.json."""

    def test_cache_file_exists(self):
        """models_cache.json существует."""
        assert router.state.models_cache_file.exists()

    def test_available_models_is_dict(self):
        """available_models — dict."""
        assert isinstance(router.state.available_models, dict)

    def test_get_model_info_returns_none_for_unknown(self):
        """Неизвестная модель → None."""
        assert router.state.get_model_info("nonexistent/model") is None

    def test_get_all_available_models_returns_list(self):
        """get_all_available_models возвращает list."""
        result = router.state.get_all_available_models()
        assert isinstance(result, list)


class TestModelsAvailableEndpoint:
    """GET /models/available."""

    async def test_returns_200(self, client):
        resp = await client.get("/models/available")
        assert resp.status_code == 200

    async def test_returns_models_list(self, client):
        resp = await client.get("/models/available")
        data = resp.json()
        assert "models" in data
        assert isinstance(data["models"], list)

    async def test_returns_last_sync(self, client):
        resp = await client.get("/models/available")
        data = resp.json()
        assert "last_sync" in data

    async def test_refresh_param_triggers_sync(self, client, monkeypatch):
        """?refresh=true вызывает sync_models_from_provider."""
        mock_sync = AsyncMock(return_value={"synced": 5, "last_sync": 123})
        monkeypatch.setattr(router.state, "sync_models_from_provider", mock_sync)
        resp = await client.get("/models/available?refresh=true")
        assert resp.status_code == 200
        mock_sync.assert_called_once()


class TestModelsSyncEndpoint:
    """POST /models/sync."""

    async def test_sync_returns_200_on_success(self, client, monkeypatch):
        mock_sync = AsyncMock(return_value={"synced": 10, "last_sync": 999})
        monkeypatch.setattr(router.state, "sync_models_from_provider", mock_sync)
        resp = await client.post("/models/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["synced"] == 10

    async def test_sync_returns_502_on_network_error(self, client, monkeypatch):
        mock_sync = AsyncMock(side_effect=ConnectionError("Network down"))
        monkeypatch.setattr(router.state, "sync_models_from_provider", mock_sync)
        resp = await client.post("/models/sync")
        assert resp.status_code == 502

    async def test_sync_returns_400_on_config_error(self, client, monkeypatch):
        mock_sync = AsyncMock(side_effect=ValueError("models_endpoint не настроен"))
        monkeypatch.setattr(router.state, "sync_models_from_provider", mock_sync)
        resp = await client.post("/models/sync")
        assert resp.status_code == 400


class TestV1ModelsUnion:
    """GET /v1/models — объединение config.yaml + кеш."""

    async def test_returns_config_models(self, client):
        """Модели из config.yaml всегда есть (составные ID)."""
        resp = await client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        # Из config.yaml — теперь с префиксом провайдера
        assert "routerai::deepseek/deepseek-v4-flash" in ids
        assert "routerai::deepseek/deepseek-v4-pro" in ids

    async def test_returns_cached_models(self, client, monkeypatch):
        """Модели из кеша добавляются к config.yaml (составные ID)."""
        monkeypatch.setattr(
            router.state,
            "available_models",
            {
                "routerai::test/cached-model": {
                    "id": "test/cached-model",
                    "name": "Test Cached",
                    "context_length": 4096,
                    "input_price_1m": 1.0,
                    "output_price_1m": 2.0,
                    "provider": "routerai",
                }
            },
        )
        monkeypatch.setattr(
            router.state,
            "models_by_provider",
            {"routerai": ["test/cached-model"]},
        )
        resp = await client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        assert "routerai::test/cached-model" in ids

    async def test_no_duplicates(self, client, monkeypatch):
        """Модель из config.yaml не дублируется (составные ID)."""
        # Добавим в кеш модель, которая уже есть в config.yaml
        monkeypatch.setattr(
            router.state,
            "available_models",
            {
                "routerai::deepseek/deepseek-v4-flash": {
                    "id": "deepseek/deepseek-v4-flash",
                    "name": "Flash (cached)",
                    "context_length": 1048576,
                    "input_price_1m": 9.0,
                    "output_price_1m": 18.0,
                    "provider": "routerai",
                }
            },
        )
        monkeypatch.setattr(
            router.state,
            "models_by_provider",
            {"routerai": ["deepseek/deepseek-v4-flash"]},
        )
        resp = await client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        assert ids.count("routerai::deepseek/deepseek-v4-flash") == 1


class TestLogUsageWithCache:
    """log_usage берёт цены из кеша, если нет в PRICES."""

    def test_log_usage_uses_cache_prices(self):
        """Модель не в PRICES, но в кеше → цена из кеша."""
        import router as r

        # Сохраняем оригинальное состояние
        orig_stats = dict(r.state.stats)
        try:
            # Модель только в кеше
            r.state.available_models = {
                "test/cached-pricing": {
                    "id": "test/cached-pricing",
                    "input_price_1m": 10.0,
                    "output_price_1m": 20.0,
                }
            }
            # Удаляем из PRICES если есть
            r.PRICES.pop("test/cached-pricing", None)

            r.log_usage("test/cached-pricing", 1000, 500)

            # cost = (1000 * 10 + 500 * 20) / 1M = 0.02
            assert r.state.stats["total_cost"] > 0
        finally:
            r.state.stats = orig_stats

    def test_log_usage_fallback_when_not_anywhere(self):
        """Модель ни в PRICES, ни в кеше → цена 0 (дельтой)."""
        import router as r

        r.PRICES.pop("ghost/model", None)
        r.state.available_models = {}

        before = r.state.stats["total_cost"]
        r.log_usage("ghost/model", 100, 50)
        # неизвестная модель даёт 0, поэтому total_cost не меняется
        assert r.state.stats["total_cost"] == before


class TestCacheCorruption:
    """Повреждённый кеш → fallback на config.yaml."""

    def test_corrupted_cache_does_not_crash(self, tmp_path, monkeypatch):
        """Битый models_cache.json → available_models = {}."""
        bad_file = tmp_path / "models_cache.json"
        bad_file.write_text("{ invalid json !!!", encoding="utf-8")

        monkeypatch.setattr(router.state, "models_cache_file", bad_file)
        router.state.available_models = {"old": {}}
        router.state._load_models_cache()

        assert router.state.available_models == {}

    def test_empty_cache_does_not_crash(self, tmp_path, monkeypatch):
        """Пустой models_cache.json → available_models = {}."""
        empty_file = tmp_path / "models_cache.json"
        empty_file.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(router.state, "models_cache_file", empty_file)
        router.state.available_models = {"old": {}}
        router.state._load_models_cache()

        assert router.state.available_models == {}
