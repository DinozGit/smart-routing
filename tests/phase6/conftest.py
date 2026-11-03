"""
SmartRouter — фикстуры для Phase 6 (спринт «Багфиксинг F1–F7», тесты F7).

Изоляция состояния спринта:
- state.providers — живой dict из config.yaml (router.py:203). Мутация
  ``enabled`` в одном тесте течёт в остальные и в module-level ``cfg`` →
  глубокий снапшот и восстановление на каждый тест.
- state.default_provider — НЕ восстанавливается корневым conftest.py, поэтому
  тоже снапшотится здесь.
- Каталог моделей и routing-конфиг уже изолируются корневыми фикстурами
  (tests/conftest.py::isolate_config) — здесь их повторно НЕ трогаем, чтобы
  не конфликтовать с порядком teardown.
- .env: router.py вычисляет путь как ``Path(__file__).parent / ".env"`` на
  каждый вызов (set_env_key / delete_provider_key). Для F3 подменяем
  router.__file__ фикстурой mock_env_file, чтобы тесты писали в tmp,
  не трогая реальный .env проекта.
"""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


@pytest.fixture(autouse=True)
def phase6_state_isolation():
    """
    Снапшот state.providers / state.default_provider и их восстановление.

    Покрывает то, что НЕ восстанавливает корневой conftest.py: провайдеры
    живут в одном dict с config.yaml, поэтому выключение в одном тесте
    обязано откатываться.
    """
    orig_providers = copy.deepcopy(router.state.providers)
    orig_default = router.state.default_provider

    yield

    router.state.providers.clear()
    router.state.providers.update(orig_providers)
    router.state.default_provider = orig_default


@pytest.fixture
def clean_providers():
    """
    Базовый набор провайдеров (как в config.yaml) для детерминированных тестов.

    Возвращает живой state.providers — тесты могут выключать провайдеров
    через p["enabled"] = False; autouse-фикстура phase6_state_isolation
    восстановит исходное состояние.
    """
    router.state.providers.clear()
    router.state.providers.update(
        {
            "routerai": {
                "enabled": True,
                "display_name": "RouterAI",
                "base_url": "https://routerai.ru/api/v1/chat/completions",
                "models_endpoint": "https://routerai.ru/api/v1/models",
                "api_key_env": "ROUTERAI_KEY",
                "requires_api_key": True,
                "pricing_mode": "auto",
                "default": True,
                "verify_ssl": True,
                "ca_bundle": "",
                "extra_headers": {},
            },
            "openrouter": {
                "enabled": True,
                "display_name": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1/chat/completions",
                "models_endpoint": "https://openrouter.ai/api/v1/models",
                "api_key_env": "OPENROUTER_API_KEY",
                "requires_api_key": True,
                "pricing_mode": "auto",
                "default": False,
                "verify_ssl": True,
                "ca_bundle": "",
                "extra_headers": {},
            },
            "ollama": {
                "enabled": True,
                "display_name": "Ollama (local)",
                "base_url": "http://localhost:11434/v1/chat/completions",
                "models_endpoint": "http://localhost:11434/api/tags",
                "api_key_env": "",
                "requires_api_key": False,
                "pricing_mode": "free",
                "default": False,
                "verify_ssl": True,
                "ca_bundle": "",
                "extra_headers": {},
            },
        }
    )
    router.state.default_provider = "routerai"
    return router.state.providers


@pytest.fixture
def disable_provider(clean_providers):
    """Выключает провайдера по имени (enabled=false)."""

    def _disable(name: str):
        assert name in clean_providers, f"Unknown provider: {name}"
        clean_providers[name]["enabled"] = False
        return clean_providers[name]

    return _disable


@pytest.fixture
def mock_env_file(tmp_path, monkeypatch):
    """
    Перенаправляет .env проекта в tmp-файл.

    router.py вычисляет путь к .env как ``Path(__file__).parent / ".env"``
    в рантайме (set_env_key, delete_provider_key). Подмена router.__file__
    заставляет писать в tmp — реальный .env проекта не затрагивается.
    """
    env_file = tmp_path / ".env"
    monkeypatch.setattr(router, "__file__", str(tmp_path / "router.py"))
    return env_file


@pytest.fixture
def bare_catalog():
    """
    Каталог моделей для F1/F5: модель есть ТОЛЬКО у openrouter.

    default_provider = routerai, ``allow_cross_provider_bare_id`` не задан →
    false (fail-closed).
    """
    router.state.default_provider = "routerai"
    router.state.models_by_provider = {
        "routerai": ["deepseek/deepseek-v4-flash"],
        "openrouter": ["qwen/qwen3-coder-next"],
    }
    router.state.available_models = {
        "routerai::deepseek/deepseek-v4-flash": {
            "id": "deepseek/deepseek-v4-flash",
            "provider": "routerai",
            "name": "Flash",
        },
        "openrouter::qwen/qwen3-coder-next": {
            "id": "qwen/qwen3-coder-next",
            "provider": "openrouter",
            "name": "Qwen Coder Next",
        },
    }
    return router.state.models_by_provider