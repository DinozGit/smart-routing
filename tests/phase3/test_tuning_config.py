"""
Phase 3 — тесты конфигурации Fine Tuning (role_tuning).

Проверяем:
- _init_default_config создаёт role_tuning с корректными значениями
- _load_config мигрирует: добавляет role_tuning если отсутствует
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from router import state


class TestRoleTuningDefaults:
    """state.config содержит role_tuning после _init_default_config."""

    def test_config_has_role_tuning(self):
        """state.config содержит role_tuning."""
        state._init_default_config()
        assert "role_tuning" in state.config

    def test_role_tuning_has_all_roles(self):
        """Все 3 роли присутствуют в role_tuning."""
        state._init_default_config()
        tuning = state.config["role_tuning"]
        assert "coordinator" in tuning
        assert "worker_default" in tuning
        assert "worker_img" in tuning

    def test_role_tuning_coordinator_defaults(self):
        """Coordinator temperature = 0.7."""
        state._init_default_config()
        assert state.config["role_tuning"]["coordinator"]["temperature"] == 0.7

    def test_role_tuning_worker_default_defaults(self):
        """Worker_default temperature = 0.3."""
        state._init_default_config()
        assert state.config["role_tuning"]["worker_default"]["temperature"] == 0.3

    def test_role_tuning_worker_img_defaults(self):
        """Worker_img temperature = 0.5."""
        state._init_default_config()
        assert state.config["role_tuning"]["worker_img"]["temperature"] == 0.5

    def test_role_tuning_top_p_default(self):
        """У всех ролей top_p = 0.9."""
        state._init_default_config()
        for role_name, tuning in state.config["role_tuning"].items():
            assert tuning["top_p"] == 0.9, f"{role_name} top_p != 0.9"

    def test_role_tuning_has_system_prompt_prefix(self):
        """Поле system_prompt_prefix присутствует у всех ролей (str)."""
        state._init_default_config()
        for role_name, tuning in state.config["role_tuning"].items():
            assert "system_prompt_prefix" in tuning, f"{role_name} missing prefix"
            assert isinstance(tuning["system_prompt_prefix"], str)

    def test_migration_adds_tuning_to_existing_config(self):
        """Если в routing.json нет role_tuning, он добавляется при _load_config."""
        # Убираем role_tuning из config (имитируем старый файл)
        if "role_tuning" in state.config:
            del state.config["role_tuning"]
        state._load_config()
        assert "role_tuning" in state.config
        # Проверяем, что дефолты корректны
        tuning = state.config["role_tuning"]
        assert tuning["coordinator"]["temperature"] == 0.7
        assert tuning["worker_default"]["temperature"] == 0.3
        assert tuning["worker_img"]["temperature"] == 0.5
