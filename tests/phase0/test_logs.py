"""
Phase 0 — тесты Logs и Stats.
"""

import pytest


class TestLogs:
    async def test_logs_return_array(self, client):
        """GET /logs → array."""
        resp = await client.get("/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_logs_limit(self, client):
        """?limit=5 → не больше 5 записей."""
        resp = await client.get("/logs?limit=5")
        data = resp.json()
        assert len(data) <= 5

    async def test_logs_default_limit(self, client):
        """Без limit → не больше 50."""
        resp = await client.get("/logs")
        data = resp.json()
        assert len(data) <= 50

    async def test_logs_level_filter(self, client):
        """?level=INFO → только INFO."""
        resp = await client.get("/logs?level=INFO")
        data = resp.json()
        for entry in data:
            assert entry["level"] == "INFO"

    async def test_logs_structure(self, client):
        """Каждая запись имеет time, level, message."""
        resp = await client.get("/logs?limit=1")
        data = resp.json()
        if data:
            entry = data[0]
            assert "time" in entry
            assert "level" in entry
            assert "message" in entry

    async def test_logs_invalid_level(self, client):
        """?level=INVALID → пустой массив (не 500)."""
        resp = await client.get("/logs?level=INVALID")
        assert resp.status_code == 200
        assert resp.json() == []


class TestStats:
    async def test_stats_ok(self, client):
        """GET /stats → 200."""
        resp = await client.get("/stats")
        assert resp.status_code == 200

    async def test_stats_has_requests(self, client):
        """Stats содержит requests (int)."""
        resp = await client.get("/stats")
        data = resp.json()
        assert "requests" in data
        assert isinstance(data["requests"], int)

    async def test_stats_has_cost(self, client):
        """Stats содержит total_cost (float)."""
        resp = await client.get("/stats")
        data = resp.json()
        assert "total_cost" in data
        assert isinstance(data["total_cost"], (int, float))

    async def test_stats_has_by_model(self, client):
        """Stats содержит by_model (dict)."""
        resp = await client.get("/stats")
        data = resp.json()
        assert "by_model" in data
        assert isinstance(data["by_model"], dict)

    async def test_stats_routed_counts(self, client):
        """Stats содержит routed_count и not_routed_count."""
        resp = await client.get("/stats")
        data = resp.json()
        assert "routed_count" in data
        assert "not_routed_count" in data
