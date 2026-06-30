"""
Phase 3 — тесты обновлённого GET /roles с context_limit.

Проверяем:
- Каждая роль содержит context_limit
- Если модель есть в кеше — context_limit не None
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestRolesEndpointContextLimit:
    """GET /roles содержит context_limit для каждой роли."""

    async def test_roles_endpoint_has_context_limit(self, client):
        """Каждая роль содержит context_limit (может быть None)."""
        resp = await client.get("/roles")
        assert resp.status_code == 200
        data = resp.json()
        roles = data["roles"]
        for role_name, role in roles.items():
            assert "context_limit" in role, f"{role_name} missing context_limit"

    async def test_roles_coordinator_context_limit_not_none(self, client):
        """Если модель coordinator есть в кеше — context_limit не None."""
        # Добавляем model info для coordinator
        coord_model = router.state.config.get("role_models", {}).get(
            "coordinator"
        ) or router.get_role_default_model("coordinator")
        if coord_model:
            router.state.available_models[coord_model] = {
                "id": coord_model,
                "name": "Coordinator Model",
                "context_length": 16384,
                "input_price_1m": 10.0,
                "output_price_1m": 20.0,
            }

        resp = await client.get("/roles")
        assert resp.status_code == 200
        data = resp.json()
        roles = data["roles"]
        assert roles["coordinator"]["context_limit"] is not None
        assert roles["coordinator"]["context_limit"] > 0

    async def test_roles_worker_default_context_limit_not_none(self, client):
        """Если модель worker_default есть в кеше — context_limit не None."""
        worker_model = router.state.config.get("role_models", {}).get(
            "worker_default"
        ) or router.get_role_default_model("worker_default")
        if worker_model:
            router.state.available_models[worker_model] = {
                "id": worker_model,
                "name": "Worker Model",
                "context_length": 8192,
                "input_price_1m": 5.0,
                "output_price_1m": 10.0,
            }

        resp = await client.get("/roles")
        data = resp.json()
        roles = data["roles"]
        assert roles["worker_default"]["context_limit"] is not None
