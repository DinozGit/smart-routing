"""
Phase 3 — тесты API endpoints для Fine Tuning.

Проверяем:
- GET /roles/tuning — список всех tuning-конфигов
- GET /roles/{name}/tuning — конкретная роль
- PUT /roles/{name}/tuning — обновление tuning
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router

DEFAULT_TUNING = {
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
        "system_prompt_prefix": "",
    },
    "worker_img": {
        "temperature": 0.5,
        "top_p": 0.9,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "system_prompt_prefix": "",
    },
}


@pytest.fixture(autouse=True)
def setup_role_tuning():
    """
    Добавляет role_tuning в state.config перед каждым тестом,
    потому что isolate_config в conftest.py не включает его.
    """
    router.state.config["role_tuning"] = DEFAULT_TUNING


class TestRolesTuningEndpoint:
    """GET /roles/tuning."""

    async def test_get_roles_tuning_returns_200(self, client):
        resp = await client.get("/roles/tuning")
        assert resp.status_code == 200

    async def test_get_roles_tuning_has_three_roles(self, client):
        resp = await client.get("/roles/tuning")
        data = resp.json()
        assert "coordinator" in data
        assert "worker_default" in data
        assert "worker_img" in data


class TestRoleTuningEndpoint:
    """GET /roles/{name}/tuning."""

    async def test_get_role_tuning_returns_200(self, client):
        resp = await client.get("/roles/coordinator/tuning")
        assert resp.status_code == 200

    async def test_get_role_tuning_not_found(self, client):
        resp = await client.get("/roles/nonexistent/tuning")
        assert resp.status_code == 404

    async def test_get_role_tuning_has_context_limit(self, client):
        """Ответ GET /roles/{name}/tuning содержит поле context_limit."""
        resp = await client.get("/roles/coordinator/tuning")
        data = resp.json()
        assert "context_limit" in data


class TestPutRoleTuningEndpoint:
    """PUT /roles/{name}/tuning."""

    async def test_put_role_tuning_updates_temperature(self, client):
        resp = await client.put(
            "/roles/coordinator/tuning",
            json={"temperature": 1.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["tuning"]["temperature"] == 1.0

        # Проверяем, что сохранилось в state
        assert router.state.config["role_tuning"]["coordinator"]["temperature"] == 1.0

    async def test_put_role_tuning_updates_prefix(self, client):
        resp = await client.put(
            "/roles/worker_default/tuning",
            json={"system_prompt_prefix": "Ты эксперт по базам данных."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tuning"]["system_prompt_prefix"] == "Ты эксперт по базам данных."

        # Проверяем, что сохранилось в state
        assert (
            router.state.config["role_tuning"]["worker_default"]["system_prompt_prefix"]
            == "Ты эксперт по базам данных."
        )

    async def test_put_role_tuning_invalid_json(self, client):
        resp = await client.put(
            "/roles/coordinator/tuning",
            content="не json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_put_role_tuning_not_found(self, client):
        resp = await client.put(
            "/roles/nonexistent/tuning",
            json={"temperature": 0.5},
        )
        assert resp.status_code == 404

    async def test_put_role_tuning_updates_only_allowed_fields(self, client):
        """Обновляются только разрешённые поля (unknown поля игнорируются)."""
        # Сначала сброс
        router.state.config["role_tuning"]["coordinator"]["temperature"] = 0.7

        resp = await client.put(
            "/roles/coordinator/tuning",
            json={"temperature": 0.5, "unknown_field": "should_be_ignored"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tuning"]["temperature"] == 0.5
        # Проверяем, что tuning не содержит unknown_field
        assert "unknown_field" not in data["tuning"]
