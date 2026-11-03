"""
Phase 5 — тесты резолва спецификации модели: resolve_model_spec,
составные спецификации, дефолтный провайдер, smart_route_model.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


# ============================================================
# resolve_model_spec
# ============================================================


class TestResolveModelSpec:
    """resolve_model_spec: разбор составных и голых ID."""

    def setup_method(self):
        """Перед каждым тестом — чистое состояние."""
        router.state.models_by_provider = {}
        router.state.default_provider = "routerai"
        # Добавляем openrouter в state.providers, чтобы resolve_model_spec не падал на неизвестного провайдера
        router.state.providers["openrouter"] = {
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
        }

    def test_composite_key(self):
        """"openrouter::deepseek/deepseek-chat" → ("openrouter", "deepseek/deepseek-chat")."""
        prov, model_id = router.resolve_model_spec("openrouter::deepseek/deepseek-chat")
        assert prov == "openrouter"
        assert model_id == "deepseek/deepseek-chat"

    def test_bare_id_one_provider(self):
        """Голый ID у 1 НЕ-default провайдера → default_provider (F1: fail-closed)."""
        router.state.models_by_provider = {
            "openrouter": ["deepseek/deepseek-chat"],
        }
        prov, model_id = router.resolve_model_spec("deepseek/deepseek-chat")
        # F1: source="client", allow_cross_provider_bare_id=false → default_provider
        assert prov == "routerai"
        assert model_id == "deepseek/deepseek-chat"

    def test_bare_id_two_providers(self):
        """Голый ID у 2 провайдеров (один — default) → default_provider (F1: fail-closed)."""
        router.state.models_by_provider = {
            "openrouter": ["shared-model"],
            "routerai": ["shared-model"],
        }
        prov, model_id = router.resolve_model_spec("shared-model")
        # F1: модель есть в default_provider → default_provider без warning
        assert prov == "routerai"
        assert model_id == "shared-model"

    def test_bare_id_not_found(self, caplog):
        """Голый ID не найден → default_provider + warning."""
        router.state.models_by_provider = {
            "routerai": ["existing-model"],
        }
        prov, model_id = router.resolve_model_spec("nonexistent/model")
        assert prov == "routerai"
        assert model_id == "nonexistent/model"
        assert any("не найдена" in rec.message for rec in caplog.records)

    def test_unknown_provider_in_prefix(self, caplog):
        """Неизвестный провайдер в префиксе → default_provider + warning."""
        prov, model_id = router.resolve_model_spec("unknown-provider::some-model")
        assert prov == "routerai"
        assert model_id == "some-model"
        assert any("Неизвестный провайдер" in rec.message for rec in caplog.records)

    def test_bare_id_empty_catalog(self):
        """Каталог пуст → default_provider."""
        router.state.models_by_provider = {}
        prov, model_id = router.resolve_model_spec("some-model")
        assert prov == "routerai"
        assert model_id == "some-model"


# ============================================================
# smart_route_model — составная спецификация
# ============================================================


class TestSmartRouteModelComposite:
    """smart_route_model возвращает составную спецификацию."""

    def setup_method(self):
        """Перед каждым тестом — чистое состояние."""
        router.state.models_by_provider = {}
        router.state.default_provider = "routerai"

    def test_returns_composite_spec(self):
        """smart_route_model возвращает составную 'provider::model_id'."""
        body = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hello world"},
            ]
        }
        spec, role, reason = router.smart_route_model("SmartAuto", body)
        assert "::" in spec, f"Expected composite spec, got: {spec}"
        prov, mid = spec.split("::", 1)
        assert prov == "routerai"
        assert mid is not None

    def test_flash_returns_composite(self):
        """Шаг 1: flash-модель возвращает составную спецификацию."""
        body = {"messages": [{"role": "user", "content": "hello"}]}
        spec, _, _ = router.smart_route_model("deepseek/deepseek-v4-flash", body)
        assert "::" in spec, f"Expected composite spec, got: {spec}"
        assert "flash" in spec.lower()

    def test_qwen_returns_composite(self):
        """Шаг 1: qwen-модель возвращает составную спецификацию."""
        body = {"messages": [{"role": "user", "content": "hello"}]}
        spec, _, _ = router.smart_route_model("qwen/qwen3-coder-next", body)
        assert "::" in spec, f"Expected composite spec, got: {spec}"
        assert "qwen" in spec.lower()