"""
Phase 6 — Спринт 5 / A2: цепочка fallback-моделей роли.

Контракт: ``docs/PROVIDER_CONTRACT.md`` → «🛡️ Спринт 5» → A2 и A5 (тест 7).

Проверяем:
- ``get_role_fallback_models``: строка → ``[s]``; список сохраняет порядок;
  не-строки и пустые строки отфильтровываются; дубликаты убираются;
- пустой список → авто-правило из config.yaml;
- ``_build_fallback_chain``: ``[spec] + fallback'и`` без дубликатов и
  совпадения с ``spec``; ``role == ""`` → ``[spec]``;
- ``GET /roles`` отдаёт ``fallback_models`` + BC-поле ``fallback_model``;
- ``POST /config`` принимает строку и список, возвращает ``warnings``.

Запись конфига в тестах уходит в tmp
(``tests/phase6/conftest.py::sprint5_config_guard``).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


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


def _set_role_fallbacks(value):
    """Подменяет role_fallbacks в runtime-конфиге (in-memory)."""
    router.state.config["role_fallbacks"] = value


# ============================================================
# 7. Порядок и дедупликация цепочки
# ============================================================


class TestFallbackChainOrderAndDedup:
    """A5/7: ``get_role_fallback_models`` + ``_build_fallback_chain``."""

    def test_string_fallback_is_single_item(self):
        _set_role_fallbacks({"coordinator": "routerai::model-a"})
        assert router.get_role_fallback_models("coordinator") == ["routerai::model-a"]
        # BC-обёртка возвращает первый элемент
        assert router.get_role_fallback_model("coordinator") == "routerai::model-a"

    def test_list_fallback_preserves_order(self):
        _set_role_fallbacks(
            {
                "coordinator": [
                    "routerai::model-a",
                    "openrouter::model-b",
                    "ollama::model-c",
                ]
            }
        )
        assert router.get_role_fallback_models("coordinator") == [
            "routerai::model-a",
            "openrouter::model-b",
            "ollama::model-c",
        ]

    def test_list_fallback_filters_non_strings_and_blanks(self):
        _set_role_fallbacks(
            {
                "worker_default": [
                    "routerai::model-a",
                    "",
                    "   ",
                    42,
                    None,
                    "openrouter::model-b",
                ]
            }
        )
        assert router.get_role_fallback_models("worker_default") == [
            "routerai::model-a",
            "openrouter::model-b",
        ]

    def test_list_fallback_deduplicates(self):
        _set_role_fallbacks(
            {"coordinator": ["routerai::a", "routerai::b", "routerai::a"]}
        )
        assert router.get_role_fallback_models("coordinator") == [
            "routerai::a",
            "routerai::b",
        ]

    def test_empty_fallback_falls_back_to_auto_rule(self):
        """Пустой список → приоритет 3: авто-правило (coordinator → worker_default)."""
        _set_role_fallbacks({"coordinator": []})
        worker_model = router.get_role_default_model("worker_default")
        assert worker_model
        assert router.get_role_fallback_models("coordinator") == [worker_model]

    def test_build_chain_drops_spec_and_duplicates(self):
        _set_role_fallbacks(
            {
                "coordinator": [
                    "routerai::model-b",
                    "routerai::model-a",
                    "routerai::model-b",
                ]
            }
        )
        # spec совпадает с одним из fallback'ов и не должен дублироваться
        assert router._build_fallback_chain("routerai::model-a", "coordinator") == [
            "routerai::model-a",
            "routerai::model-b",
        ]

    def test_build_chain_empty_role_ignores_fallbacks(self):
        """Явная спецификация клиента (role == "") → только [spec]."""
        _set_role_fallbacks({"coordinator": ["routerai::model-b"]})
        assert router._build_fallback_chain("routerai::model-a", "") == [
            "routerai::model-a"
        ]


# ============================================================
# GET /roles — fallback_models + BC fallback_model
# ============================================================


class TestRolesEndpointFallbackModels:
    """``GET /roles`` дополнен цепочкой, ``fallback_model`` остаётся (BC)."""

    async def test_roles_expose_fallback_models_chain(self, client):
        _set_role_fallbacks(
            {"coordinator": ["routerai::model-a", "openrouter::model-b"]}
        )

        data = (await client.get("/roles")).json()
        coordinator = data["roles"]["coordinator"]

        assert coordinator["fallback_models"] == [
            "routerai::model-a",
            "openrouter::model-b",
        ]
        # BC: строка = первый элемент цепочки
        assert coordinator["fallback_model"] == "routerai::model-a"

    async def test_roles_fallback_model_is_first_of_chain(self, client):
        _set_role_fallbacks({"worker_img": "openrouter::only-model"})

        data = (await client.get("/roles")).json()
        worker_img = data["roles"]["worker_img"]

        assert worker_img["fallback_models"] == ["openrouter::only-model"]
        assert worker_img["fallback_model"] == "openrouter::only-model"


# ============================================================
# POST /config — строка/список + warnings
# ============================================================


class TestPostConfigRoleFallbacks:
    """``POST /config`` принимает строку и список, отвечает ``warnings``."""

    async def test_post_config_accepts_string(self, client):
        _install_catalog([("routerai", "known-model", 1000)])

        resp = await client.post(
            "/config", json={"role_fallbacks": {"coordinator": "routerai::known-model"}}
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "ok"
        assert data["warnings"] == []
        assert (
            router.state.config["role_fallbacks"]["coordinator"]
            == "routerai::known-model"
        )
        assert router.get_role_fallback_models("coordinator") == [
            "routerai::known-model"
        ]

    async def test_post_config_accepts_list_and_preserves_order(self, client):
        _install_catalog(
            [
                ("routerai", "model-a", 1000),
                ("openrouter", "model-b", 2000),
            ]
        )

        chain = ["routerai::model-a", "openrouter::model-b"]
        resp = await client.post("/config", json={"role_fallbacks": {"coordinator": chain}})
        assert resp.status_code == 200

        data = resp.json()
        assert data["warnings"] == []
        assert router.get_role_fallback_models("coordinator") == chain

    async def test_post_config_warns_about_unknown_model(self, client):
        _install_catalog([("routerai", "known-model", 1000)])

        resp = await client.post(
            "/config",
            json={"role_fallbacks": {"worker_default": ["openrouter::missing-model"]}},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["warnings"]) == 1
        warning = data["warnings"][0]
        assert "role_fallbacks.worker_default" in warning
        assert "openrouter::missing-model" in warning
        # Предупреждение НЕ блокирует сохранение
        assert (
            router.state.config["role_fallbacks"]["worker_default"]
            == ["openrouter::missing-model"]
        )
