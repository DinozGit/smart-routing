"""
Phase 0 — тесты Config endpoints.
"""

import pytest


class TestConfig:
    async def test_config_get(self, client):
        """GET /config → 200, есть agent_to_worker_mapping."""
        resp = await client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_to_worker_mapping" in data

    async def test_config_has_coordinator(self, client):
        """Mapping содержит coordinator."""
        resp = await client.get("/config")
        data = resp.json()
        mapping = data.get("agent_to_worker_mapping", {})
        assert "coordinator" in mapping

    async def test_config_has_default_worker(self, client):
        """Есть default_worker."""
        resp = await client.get("/config")
        data = resp.json()
        assert "default_worker" in data
        assert data["default_worker"]

    async def test_config_has_enable_auto_routing(self, client):
        """Есть enable_auto_routing (bool)."""
        resp = await client.get("/config")
        data = resp.json()
        assert "enable_auto_routing" in data
        assert isinstance(data["enable_auto_routing"], bool)

    async def test_config_post_valid(self, client):
        """POST /config с валидными данными → 200."""
        new_config = {
            "agent_to_worker_mapping": {
                "coordinator": "deepseek/deepseek-v4-pro",
                "database": "deepseek/deepseek-v4-flash",
            },
            "default_worker": "deepseek/deepseek-v4-flash",
            "enable_auto_routing": True,
        }
        resp = await client.post("/config", json=new_config)
        assert resp.status_code == 200
        data = resp.json()
        assert "config" in data
        # Проверяем, что сохранённое значение = отправленное
        assert (
            data["config"]["agent_to_worker_mapping"]["coordinator"]
            == "deepseek/deepseek-v4-pro"
        )

    async def test_config_post_invalid(self, client):
        """POST /config с невалидным JSON → 400."""
        resp = await client.post(
            "/config", content="not json", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 400

    async def test_config_default_worker_not_empty(self, client):
        """default_worker не пустая строка."""
        resp = await client.get("/config")
        data = resp.json()
        assert data["default_worker"] != ""

    async def test_config_coordinator_not_glm(self, client):
        """Coordinator не должен быть GLM (проверка что тесты не портят конфиг)."""
        resp = await client.get("/config")
        data = resp.json()
        coord = data.get("agent_to_worker_mapping", {}).get("coordinator", "")
        assert "glm" not in coord.lower(), f"Coordinator is GLM: {coord}"
