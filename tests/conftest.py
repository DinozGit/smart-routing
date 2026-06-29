"""
SmartRouter — общие фикстуры для тестов.
"""

import json
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Добавляем корень проекта в sys.path, чтобы router мог импортироваться
sys.path.insert(0, str(Path(__file__).parent.parent))


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
        "Your job is to decompose phases into sub-tasks, "
        "distribute between spawn_agent, synthesize results, code review.\n"
        "Deploy on VPS via SSH key in ~/.ssh/authorized_keys."
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


@pytest.fixture
def tmp_config(tmp_path) -> Path:
    """Временная копия routing.json для тестов, не трогает реальный файл."""
    src = Path(__file__).parent.parent / "routing.json"
    if src.exists():
        data = json.loads(src.read_text(encoding="utf-8"))
    else:
        data = {
            "agent_to_worker_mapping": {
                "coordinator": "z-ai/glm-5.2",
                "default_worker": "deepseek/deepseek-v4-flash",
            },
            "enable_auto_routing": True,
        }
    dst = tmp_path / "routing.json"
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return dst
