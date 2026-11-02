"""
Phase 4 — тесты атомарной записи конфигов в RouterState.

Проверяем:
- _atomic_write: файл создаётся, перезаписывается целиком, .tmp не остаётся
- _sync_write_config: валидный JSON (indent=2), перезапись, без .tmp
- _backup_broken_file: битый файл сохраняется как *.broken, повторный вызов безопасен
- _load_config: битый routing.json НЕ перезаписывается дефолтами (главный баг)
- _load_models_cache: битый models_cache.json → available_models = {}, не падает
- save_config (async): файл остаётся валидным JSON, .tmp не остаётся

Тесты используют tmp_path (через autouse-фикстуру isolate_config из conftest.py),
реальные routing.json / config.yaml / models_cache.json не трогаются.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router  # noqa: E402


class TestAtomicWrite:
    """RouterState._atomic_write: tmp-файл + os.replace."""

    def test_creates_file_with_content(self, tmp_path):
        """Файл создан и содержит ровно то, что записали."""
        target = tmp_path / "routing.json"
        content = '{"role_models": {"coordinator": "deepseek/deepseek-v4-pro"}}'

        router.RouterState._atomic_write(target, content)

        assert target.exists()
        assert target.read_text(encoding="utf-8") == content

    def test_overwrites_content_not_appends(self, tmp_path):
        """Повторная запись перезаписывает содержимое целиком (не дописывает)."""
        target = tmp_path / "routing.json"
        router.RouterState._atomic_write(target, "first-content")
        # Новая запись короче старой — при дописывании (append-режим) хвост бы остался
        router.RouterState._atomic_write(target, "new")

        assert target.read_text(encoding="utf-8") == "new"
        assert "first" not in target.read_text(encoding="utf-8")

    def test_no_tmp_leftover(self, tmp_path):
        """
        Временный .tmp файл не остаётся в директории после успешной записи.

        Если бы реализация писала в tmp, но не делала os.replace (или оставляла
        tmp-файл на диске), этот тест упал бы: в директории появился бы *.tmp.
        """
        target = tmp_path / "routing.json"

        router.RouterState._atomic_write(target, "data")

        assert list(tmp_path.glob("*.tmp")) == []

    def test_large_content_identical(self, tmp_path):
        """Запись ~200 КБ: прочитанное содержимое идентично записанному."""
        target = tmp_path / "big.json"
        content = json.dumps({"payload": "x" * (200 * 1024)}, ensure_ascii=False)
        assert len(content) >= 200 * 1024  # гарантируем размер

        router.RouterState._atomic_write(target, content)

        assert target.read_text(encoding="utf-8") == content


class TestSyncWriteConfig:
    """RouterState._sync_write_config: атомарная запись JSON-конфига."""

    def test_writes_valid_json_indent2(self, tmp_path):
        """Записывает валидный JSON с indent=2 и ensure_ascii=False."""
        target = tmp_path / "routing.json"
        data = {"default_worker": "deepseek/deepseek-v4-flash", "поле": "значение"}

        router.RouterState._sync_write_config(target, data)

        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == data
        # indent=2: каждая строка начинается пробелами
        assert "  \"default_worker\"" in target.read_text(encoding="utf-8")


    def test_overwrites_existing_file(self, tmp_path):
        """Перезаписывает существующий файл — старый контент не остаётся."""
        target = tmp_path / "routing.json"
        target.write_text('{"old": "content"}', encoding="utf-8")
        data = {"new": "value", "another": 42}

        router.RouterState._sync_write_config(target, data)

        assert json.loads(target.read_text(encoding="utf-8")) == data
        assert "old" not in target.read_text(encoding="utf-8")

    def test_no_tmp_leftover(self, tmp_path):
        """После _sync_write_config *.tmp в директории не остаётся."""
        target = tmp_path / "routing.json"

        router.RouterState._sync_write_config(target, {"a": 1})

        assert list(tmp_path.glob("*.tmp")) == []


class TestBackupBrokenFile:
    """RouterState._backup_broken_file: сохранение битого файла как *.broken."""

    def test_renames_to_broken_with_content(self, tmp_path):
        """Исходный файл переименован в *.broken, содержимое сохранено."""
        target = tmp_path / "routing.json"
        broken_content = "{ this is not valid json"
        target.write_text(broken_content, encoding="utf-8")

        router.RouterState._backup_broken_file(target)

        backup = target.with_suffix(target.suffix + ".broken")
        assert not target.exists()
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == broken_content

    def test_second_call_no_duplicates(self, tmp_path):
        """Повторный вызов с новым битым контентом: старый *.broken заменяется."""
        target = tmp_path / "routing.json"
        backup = target.with_suffix(target.suffix + ".broken")

        target.write_text("broken v1", encoding="utf-8")
        router.RouterState._backup_broken_file(target)
        assert backup.read_text(encoding="utf-8") == "broken v1"

        # Файл снова битый — повторный backup не падает и не дублирует мусор
        target.write_text("broken v2", encoding="utf-8")
        router.RouterState._backup_broken_file(target)

        assert not target.exists()
        assert backup.read_text(encoding="utf-8") == "broken v2"
        assert len(list(tmp_path.glob("*.broken"))) == 1


class TestSafeConfigLoad:
    """Главный баг: битый routing.json не перезаписывается дефолтами."""

    def test_broken_json_not_overwritten(self, isolate_config):
        """
        Битый routing.json НЕ перезаписан дефолтами — сохранён как *.broken.

        Старая реализация после JSONDecodeError вызывала _sync_write_config()
        с дефолтами — routing.json молча затирался, теряя настройки ролей.
        Тот тест упал бы: config_file продолжал бы существовать с валидными
        дефолтами, а *.broken не появился бы вовсе.
        """
        import router

        config_file = router.state.config_file  # tmp_path/routing.json от фикстуры
        broken_content = "{ this is not valid json"
        config_file.write_text(broken_content, encoding="utf-8")

        router.state._load_config()

        # Файл не перезаписан дефолтами: он перемещён в *.broken, а не залит заново
        assert not config_file.exists(), (
            "routing.json перезаписан дефолтами — настройки ролей потеряны"
        )
        backup = config_file.with_suffix(config_file.suffix + ".broken")
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == broken_content

    def test_broken_json_defaults_loaded(self, isolate_config):
        """state.config после битого файла содержит дефолтные role_models."""
        import router

        config_file = router.state.config_file
        config_file.write_text("{ broken json", encoding="utf-8")

        router.state._load_config()

        # Роутер продолжает работать с дефолтами ролей
        role_models = router.state.config.get("role_models", {})
        assert "coordinator" in role_models
        assert "worker_default" in role_models
        assert "worker_img" in role_models
        assert role_models["coordinator"]
        assert router.state.config.get("enable_auto_routing") is True


class TestModelsCacheBroken:
    """Битый models_cache.json не роняет роутер."""

    def test_broken_cache_backed_up_and_empty(self, isolate_config):
        """Битый models_cache.json → *.broken, available_models == {}."""
        import router

        cache_file = router.state.models_cache_file  # tmp_path/models_cache.json
        broken_content = "{ not a json"
        cache_file.write_text(broken_content, encoding="utf-8")

        router.state._load_models_cache()

        backup = cache_file.with_suffix(cache_file.suffix + ".broken")
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == broken_content
        assert router.state.available_models == {}


class TestSaveConfigRegression:
    """save_config (async): routing.json остаётся валидным, без .tmp."""

    async def test_save_config_valid_json_no_tmp(self, isolate_config):
        """После save_config файл — валидный JSON с сохранёнными значениями."""
        import router

        config_file = router.state.config_file

        await router.state.save_config({"default_worker": "test/model-saved"})

        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data["default_worker"] == "test/model-saved"
        # Остальной конфиг не потерян — сохранён целиком, а не частично
        assert "role_models" in data
        # Временный файл не остаётся
        assert list(config_file.parent.glob("*.tmp")) == []