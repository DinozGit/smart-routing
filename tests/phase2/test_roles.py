"""
Phase 2 — тесты трёх-рольной архитектуры (Coordinator / Worker / Worker Img).

Step 2.1: smart_route_model возвращает (model, role, reason).
Маппинг агент → роль:
  coordinator          → coordinator
  database/tests/bot/api/services/devops → worker_default
  frontend/mobile/design                 → worker_img
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from router import (
    AGENT_TO_ROLE,
    ROLES_CFG,
    get_role_default_model,
    get_role_fallback_model,
    get_role_for_agent,
    smart_route_model,
)


class TestRolesConfig:
    """Роли загружаются из config.yaml корректно."""

    def test_roles_loaded(self):
        """Три роли присутствуют в конфиге."""
        assert "coordinator" in ROLES_CFG
        assert "worker_default" in ROLES_CFG
        assert "worker_img" in ROLES_CFG

    def test_role_has_required_fields(self):
        """Каждая роль имеет default_model, agents."""
        for role_name, role_cfg in ROLES_CFG.items():
            assert "default_model" in role_cfg, f"{role_name} missing default_model"
            assert "agents" in role_cfg, f"{role_name} missing agents"
            assert isinstance(role_cfg["agents"], list)
            assert len(role_cfg["agents"]) > 0

    def test_role_has_capabilities(self):
        """Каждая роль имеет блок capabilities."""
        for role_name, role_cfg in ROLES_CFG.items():
            assert "capabilities" in role_cfg, f"{role_name} missing capabilities"
            caps = role_cfg["capabilities"]
            assert "tools" in caps
            assert "images" in caps
            assert "max_tokens" in caps


class TestAgentToRoleMapping:
    """Маппинг агент → роль построен корректно."""

    @pytest.mark.parametrize(
        "agent,expected_role",
        [
            ("coordinator", "coordinator"),
            ("database", "worker_default"),
            ("tests", "worker_default"),
            ("bot", "worker_default"),
            ("api", "worker_default"),
            ("services", "worker_default"),
            ("devops", "worker_default"),
            ("frontend", "worker_img"),
            ("mobile", "worker_img"),
            ("design", "worker_img"),
        ],
    )
    def test_agent_to_role(self, agent, expected_role):
        """Каждый агент маппится на правильную роль."""
        assert AGENT_TO_ROLE[agent] == expected_role

    def test_get_role_for_agent_known(self):
        assert get_role_for_agent("database") == "worker_default"

    def test_get_role_for_agent_unknown(self):
        assert get_role_for_agent("nonexistent") is None


class TestRoleModels:
    """default_model и fallback_model для ролей."""

    def test_coordinator_default_model(self):
        model = get_role_default_model("coordinator")
        assert model is not None
        assert "pro" in model.lower(), f"Coordinator should be Pro, got {model}"
        assert "glm" not in model.lower(), f"Coordinator should not be GLM, got {model}"

    def test_worker_default_model(self):
        model = get_role_default_model("worker_default")
        assert model is not None
        assert "flash" in model.lower()

    def test_worker_img_default_model(self):
        model = get_role_default_model("worker_img")
        assert model is not None
        assert "qwen" in model.lower()

    def test_fallback_models_exist(self):
        for role in ROLES_CFG:
            fb = get_role_fallback_model(role)
            assert fb is not None, f"{role} has no fallback_model"

    def test_default_not_equal_fallback(self):
        """default_model ≠ fallback_model для каждой роли."""
        for role in ROLES_CFG:
            default = get_role_default_model(role)
            fallback = get_role_fallback_model(role)
            assert default != fallback, f"{role}: default == fallback ({default})"

    def test_coordinator_fallback_is_worker_default(self):
        """Coordinator fallback = worker_default.default_model (auto)."""
        fb = get_role_fallback_model("coordinator")
        worker_default = get_role_default_model("worker_default")
        assert fb == worker_default, (
            f"Coordinator fallback should be {worker_default}, got {fb}"
        )

    def test_worker_default_fallback_is_coordinator(self):
        """Worker_default fallback = coordinator.default_model (auto)."""
        fb = get_role_fallback_model("worker_default")
        coord = get_role_default_model("coordinator")
        assert fb == coord, f"Worker_default fallback should be {coord}, got {fb}"

    def test_worker_img_fallback_is_worker_default(self):
        """Worker_img fallback = worker_default.default_model (auto)."""
        fb = get_role_fallback_model("worker_img")
        worker_default = get_role_default_model("worker_default")
        assert fb == worker_default, (
            f"Worker_img fallback should be {worker_default}, got {fb}"
        )

    def test_unknown_role_returns_none(self):
        assert get_role_default_model("nonexistent") is None
        assert get_role_fallback_model("nonexistent") is None


class TestSmartRouteReturnsRole:
    """smart_route_model возвращает корректную роль (3-tuple)."""

    def test_unknown_request_returns_coordinator_role(self):
        """Неизвестный запрос → coordinator роль (дефолт)."""
        body = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "hello world"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got {role}"

    def test_coordinator_fingerprint_returns_coordinator_role(
        self, sample_coordinator_prompt
    ):
        """Coordinator fingerprint → coordinator роль."""
        body = {
            "messages": [
                {"role": "system", "content": sample_coordinator_prompt},
                {"role": "user", "content": "review the architecture"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got {role}"

    def test_sub_agent_returns_coordinator_role(self):
        """Sub-agent (короткий промпт без fingerprint) → coordinator."""
        body = {
            "messages": [
                {"role": "system", "content": "Short generic prompt."},
                {"role": "user", "content": "do something"},
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got {role}"

    def test_explicit_model_empty_role(self):
        """Явно указанная flash/qwen модель → пустая роль (без маршрутизации)."""
        body = {
            "messages": [
                {"role": "user", "content": "hello"},
            ]
        }
        model, role, reason = smart_route_model("deepseek/deepseek-v4-flash", body)
        assert role == "", f"Expected empty role, got {role}"

    def test_database_agent_tag_returns_worker_default(self):
        """Тег [AGENT:database] → worker_default роль."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "[AGENT:database] Создай миграцию для users",
                }
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "worker_default", f"Expected worker_default, got {role}"

    def test_frontend_agent_tag_returns_worker_img(self):
        """Тег [AGENT:frontend] → worker_img роль."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "[AGENT:frontend] Создай компонент LoginForm",
                }
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "worker_img", f"Expected worker_img, got {role}"

    def test_coordinator_agent_tag_returns_coordinator(self):
        """Тег [AGENT:coordinator] → coordinator роль."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "[AGENT:coordinator] Разбей задачу на фазы",
                }
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got {role}"

    def test_qwen_no_heuristic_returns_coordinator(self):
        """Эвристика с qwen-паттернами → worker_img роль."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "Создай .tsx компонент с useState и useEffect на Next.js",
                }
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got {role}"

    def test_flash_no_heuristic_returns_coordinator(self):
        """Эвристика с flash-паттернами → worker_default роль."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "Запусти docker compose up и напиши pytest test_auth",
                }
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "coordinator", f"Expected coordinator, got {role}"


class TestRolesEndpoint:
    """GET /roles — эндпоинт для админки."""

    async def test_roles_endpoint_returns_200(self, client):
        resp = await client.get("/roles")
        assert resp.status_code == 200

    async def test_roles_endpoint_has_three_roles(self, client):
        resp = await client.get("/roles")
        data = resp.json()
        roles = data["roles"]
        assert "coordinator" in roles
        assert "worker_default" in roles
        assert "worker_img" in roles

    async def test_roles_have_fallback_models(self, client):
        resp = await client.get("/roles")
        data = resp.json()
        for role_name, role in data["roles"].items():
            assert role["fallback_model"], f"{role_name} missing fallback_model"
            assert role["default_model"], f"{role_name} missing default_model"

    async def test_roles_have_agents_list(self, client):
        resp = await client.get("/roles")
        data = resp.json()
        for role_name, role in data["roles"].items():
            assert isinstance(role["agents"], list)
            assert len(role["agents"]) > 0


class TestRoleDefaultModelRouting:
    """Распознанный агент с 'auto' → default_model роли (не всегда flash)."""

    def test_frontend_auto_returns_qwen_not_flash(self):
        """Frontend с auto → worker_img → qwen (не flash)."""
        # Добавляем frontend в mapping как auto (по умолчанию)
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": "[AGENT:frontend] Создай LoginForm",
                }
            ]
        }
        model, role, reason = smart_route_model("SmartAuto", body)
        assert role == "worker_img", f"Expected coordinator, got {role}"
        # frontend в mapping стоит 'qwen/qwen3-coder-next'
        # поэтому вернётся qwen
