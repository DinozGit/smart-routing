"""
SmartRouter — общие фикстуры для тестов.
"""

import json
import sys
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

# Добавляем корень проекта в sys.path, чтобы router мог импортироваться
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True, scope="function")
def fresh_http_client():
    """
    Пересоздаёт глобальный httpx.AsyncClient перед каждым тестом.
    Решает проблему 'Event loop is closed' на Windows при совместном
    запуске тестов с моками и без.
    """
    import router

    router.http_client = httpx.AsyncClient(timeout=180.0)
    yield
    # Не закрываем — event loop уже может быть закрыт,
    # сборщик мусора разберётся


@pytest.fixture(autouse=True, scope="function")
def isolate_config(tmp_path):
    """
    Изолирует routing.json и models_cache.json от продакшен-файлов.
    Подменяет state.config_file и state.models_cache_file на временные,
    чтобы тесты не портили реальные файлы.
    """
    import router

    # Сохраняем оригиналы
    orig_config_file = router.state.config_file
    orig_models_cache_file = router.state.models_cache_file
    orig_config = dict(router.state.config)
    orig_available_models = dict(router.state.available_models)

    # Берём модели из config.yaml (не хардкодим!)
    coord_model = (
        router.get_role_default_model("coordinator") or "deepseek/deepseek-v4-pro"
    )
    worker_model = (
        router.get_role_default_model("worker_default") or "deepseek/deepseek-v4-flash"
    )
    img_model = router.get_role_default_model("worker_img") or "qwen/qwen3-coder-next"

    # Создаём временный routing.json
    tmp_routing = tmp_path / "routing.json"
    routing_data = {
        "agent_to_worker_mapping": {
            "database": worker_model,
            "frontend": img_model,
            "coordinator": coord_model,
        },
        "default_worker": worker_model,
        "enable_auto_routing": True,
    }
    tmp_routing.write_text(
        json.dumps(routing_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Создаём пустой models_cache.json
    tmp_models = tmp_path / "models_cache.json"
    tmp_models.write_text(
        json.dumps({"models": [], "last_sync": None, "provider": "routerai"}),
        encoding="utf-8",
    )

    # Подменяем пути и перезагружаем
    router.state.config_file = tmp_routing
    router.state.models_cache_file = tmp_models
    router.state.config = dict(routing_data)
    router.state.available_models = {}

    yield

    # Восстанавливаем
    router.state.config_file = orig_config_file
    router.state.models_cache_file = orig_models_cache_file
    router.state.config = orig_config
    router.state.available_models = orig_available_models


@pytest.fixture(scope="session")
def app():
    """Импортируем FastAPI-приложение router'а (один раз на сессию)."""
    from router import app as router_app

    return router_app


@pytest.fixture(scope="function")
async def client(app):
    """
    ASGI-клиент без запуска отдельного порта.
    scope=function — чтобы не конфликтовать с event loop между тестами.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as ac:
        yield ac


@pytest.fixture
def sample_coordinator_prompt() -> str:
    return (
        "You are the Zed coding agent running inside the Zed editor.\n"
        "You have AGENTS.md with multi-agent configuration.\n"
        "SYSTEM_CONTEXT.md is the single source of truth.\n"
        "Coordinator (главный агент в этом чате).\n"
        "Декомпозиция фаз на подзадачи, распределение между spawn_agent.\n"
        "Деплой на VPS через SSH (ключ в ~/.ssh/authorized_keys).\n"
        "Your job is to synthesize results, code review.\n"
    )


@pytest.fixture
def sample_bot_prompt() -> str:
    return (
        "You are CalorIt Telegram Bot.\n"
        "Files: app/handlers/*.py, app/keyboards.py\n"
        "Responsibility: aiogram handlers, FSM states, inline keyboards, bot commands.\n"
        "Write scope: handlers/*.py, keyboards.py\n"
        "Read scope: app/services/*.py, app/database/crud.py, app/config.py"
    )


@pytest.fixture
def sample_messages(sample_coordinator_prompt) -> list:
    """Типовой запрос от Coordinator'а."""
    return [
        {"role": "system", "content": sample_coordinator_prompt},
        {"role": "user", "content": "Сделай код-ревью текущих изменений"},
    ]
