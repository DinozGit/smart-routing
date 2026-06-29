"""
Phase 1 — тесты естественно-языковых паттернов fingerprint_user_messages.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from router import MIN_SCOPE_SCORE, fingerprint_user_messages


class TestNaturalLanguageFingerprint:
    """Естественно-языковые паттерны должны определять агента по обычным задачам."""

    @pytest.mark.parametrize(
        "user_msg,expected_agent",
        [
            # database
            ("Создай миграцию для таблицы users", "database"),
            ("Добавь SQLAlchemy модель для User", "database"),
            ("Напиши CRUD операции для заказов", "database"),
            # tests
            ("Напиши тест для функции auth", "tests"),
            ("Проверь покрытие кода тестами", "tests"),
            # bot
            ("Добавь команду /start в бота", "bot"),
            ("Создай inline клавиатуру для меню", "bot"),
            # devops
            ("Настрой деплой через docker compose", "devops"),
            ("Обнови nginx конфигурацию", "devops"),
            # api
            ("Напиши эндпоинт /users/me на fastapi", "api"),
            ("Создай pydantic схему для регистрации", "api"),
            # services
            ("Добавь расчёт калорий в nutrition service", "services"),
            # frontend
            ("Создай компонент LoginForm на React", "frontend"),
            ("Добавь страницу dashboard на Next.js", "frontend"),
            # mobile
            ("Создай экран профиля на Flutter", "mobile"),
            ("Добавь виджет навигации в calorit_app", "mobile"),
            # design
            ("Обнови design tokens для тёмной темы", "design"),
            ("Создай цветовую палитру в Figma", "design"),
            # coordinator
            ("Сделай код-ревью архитектуры проекта", "coordinator"),
            ("Разбей задачу на фазы и сделай план", "coordinator"),
        ],
    )
    def test_natural_language_detection(self, user_msg, expected_agent):
        """Фраза естественным языком → правильный агент."""
        messages = [{"role": "user", "content": user_msg}]
        result = fingerprint_user_messages(messages)
        assert result is not None, f"Agent not detected for: {user_msg}"
        agent, score = result
        assert agent == expected_agent, (
            f"Expected '{expected_agent}', got '{agent}' (score={score}) for: {user_msg}"
        )
        assert score >= MIN_SCOPE_SCORE, (
            f"Score {score} < {MIN_SCOPE_SCORE} for: {user_msg}"
        )

    def test_unknown_message_returns_none(self):
        """Нераспознанное сообщение → None."""
        messages = [{"role": "user", "content": "hello world"}]
        result = fingerprint_user_messages(messages)
        assert result is None

    def test_empty_messages_returns_none(self):
        """Пустой список → None."""
        result = fingerprint_user_messages([])
        assert result is None

    def test_no_user_messages_returns_none(self):
        """Только system сообщения → None."""
        messages = [{"role": "system", "content": "You are a helpful assistant."}]
        result = fingerprint_user_messages(messages)
        assert result is None

    def test_multiple_messages_aggregated(self):
        """Несколько user-сообщений — текст агрегируется."""
        messages = [
            {"role": "user", "content": "Помоги с проектом"},
            {"role": "assistant", "content": "Что нужно сделать?"},
            {"role": "user", "content": "Создай миграцию для таблицы users"},
        ]
        result = fingerprint_user_messages(messages)
        assert result is not None
        assert result[0] == "database"

    def test_russian_and_english_mix(self):
        """Смешанный русско-английский текст."""
        messages = [
            {
                "role": "user",
                "content": "Create a migration для users table через alembic",
            },
        ]
        result = fingerprint_user_messages(messages)
        assert result is not None
        assert result[0] == "database"
