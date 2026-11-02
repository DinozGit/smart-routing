"""
Phase 0 — тесты Health и Models endpoints.
"""

import pytest


class TestHealth:
    async def test_health_ok(self, client):
        """GET /health → 200, status: ok."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    async def test_health_has_cost(self, client):
        """GET /health содержит поле cost (без символа $)."""
        resp = await client.get("/health")
        data = resp.json()
        assert "cost" in data
        assert isinstance(data["cost"], str)
        assert not data["cost"].startswith("$")
        assert float(data["cost"]) >= 0.0

    async def test_health_cost_format(self, client):
        """Формат cost: 0.0000 (без $)."""
        resp = await client.get("/health")
        data = resp.json()
        # Проверяем что парсится как float
        cost = float(data["cost"])
        assert cost >= 0.0


class TestModels:
    async def test_v1_models_list(self, client):
        """GET /v1/models → object: list, data — массив."""
        resp = await client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

    async def test_v1_models_structure(self, client):
        """Каждая модель имеет id, object, owned_by."""
        resp = await client.get("/v1/models")
        data = resp.json()
        for model in data["data"]:
            assert "id" in model
            assert "object" in model
            assert model["object"] == "model"
            assert "owned_by" in model

    async def test_v1_models_contains_flash(self, client):
        """В списке есть routerai::deepseek/deepseek-v4-flash."""
        resp = await client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        assert "routerai::deepseek/deepseek-v4-flash" in ids

    async def test_v1_models_contains_pro(self, client):
        """В списке есть routerai::deepseek/deepseek-v4-pro."""
        resp = await client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        assert "routerai::deepseek/deepseek-v4-pro" in ids

    async def test_v1_models_contains_qwen(self, client):
        """В списке есть routerai::qwen/qwen3-coder-next."""
        resp = await client.get("/v1/models")
        data = resp.json()
        ids = [m["id"] for m in data["data"]]
        assert "routerai::qwen/qwen3-coder-next" in ids
