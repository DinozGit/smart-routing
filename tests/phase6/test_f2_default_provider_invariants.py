"""
Phase 6 — F2 (регресс): инвариант «default_provider всегда включён».

Дыры, закрытые этими тестами:

1. ``POST /providers`` с ``{"default": true, "enabled": false}`` для провайдера,
   который НЕ являлся default'ом, проскакивал мимо защиты (проверка смотрела на
   ``name != state.default_provider``) → блок ``if data.get("default", False)``
   делал его ``state.default_provider`` → default_provider становился выключенным
   → все запросы упирались в 400 "Provider 'X' is disabled".

2. ``DELETE /providers/{name}`` при удалении активного провайдера назначал
   новым default'ом ПЕРВЫЙ ключ словаря (``next(iter(state.providers))``) —
   он мог быть выключенным → та же поломка.

Файлы проекта не трогаем: ``save_config_yaml()`` пишет по модульной
константе ``router.CONFIG_FILE`` → подменяем её на tmp-путь.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestF2DefaultProviderInvariants:
    """Инвариант: default_provider всегда включён."""

    async def test_cannot_make_disabled_provider_default(
        self, client, clean_providers, monkeypatch, tmp_path
    ):
        """
        POST /providers {default: true, enabled: false} для НЕ-default
        провайдера → 400, state.default_provider не изменился.
        """
        # config.yaml не трогаем (save_config_yaml пишет по router.CONFIG_FILE)
        monkeypatch.setattr(router, "CONFIG_FILE", tmp_path / "config.yaml")

        assert router.state.default_provider == "routerai"
        assert router.state.providers["openrouter"]["default"] is False

        resp = await client.post(
            "/providers",
            json={
                "name": "openrouter",
                "display_name": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1/chat/completions",
                "api_key_env": "OPENROUTER_API_KEY",
                "models_endpoint": "https://openrouter.ai/api/v1/models",
                "enabled": False,
                "default": True,
            },
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot disable default provider 'openrouter'"

        # Инвариант: default_provider не изменился и остался включённым
        assert router.state.default_provider == "routerai"
        assert router.state.is_provider_enabled(router.state.default_provider)

        # Провайдер не переписан: остался включённым и не-default'ным
        assert router.state.providers["openrouter"]["enabled"] is True
        assert router.state.providers["openrouter"]["default"] is False

    async def test_delete_default_provider_selects_enabled_provider(
        self, client, clean_providers, disable_provider, monkeypatch, tmp_path
    ):
        """
        Удаление default_provider, когда среди остальных есть выключенный:
        новым default'ом становится ВКЛЮЧЁННЫЙ провайдер.
        """
        monkeypatch.setattr(router, "CONFIG_FILE", tmp_path / "config.yaml")

        # Порядок ключей в state.providers: routerai, openrouter, ollama.
        # Выключаем openrouter — именно он первым окажется в порядке обхода
        # после удаления routerai (старый код выбрал бы его).
        disable_provider("openrouter")
        assert router.state.default_provider == "routerai"

        resp = await client.delete("/providers/routerai")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        # Новый default — включённый провайдер, а не выключенный openrouter
        assert data["default_provider"] == "ollama"
        assert router.state.default_provider == "ollama"
        assert router.state.is_provider_enabled(router.state.default_provider)
        assert router.state.providers["ollama"]["default"] is True

        # Выключенный провайдер остался на месте и остался выключенным
        assert "openrouter" in router.state.providers
        assert router.state.providers["openrouter"]["enabled"] is False

    async def test_cannot_delete_last_enabled_provider(
        self, client, clean_providers, disable_provider, monkeypatch, tmp_path
    ):
        """
        Удаление последнего включённого провайдера (он же default) → 400,
        состояние не меняется: провайдер на месте, default_provider прежний.
        """
        monkeypatch.setattr(router, "CONFIG_FILE", tmp_path / "config.yaml")

        disable_provider("openrouter")
        disable_provider("ollama")
        assert router.state.default_provider == "routerai"
        assert router.state.is_provider_enabled("routerai")

        resp = await client.delete("/providers/routerai")

        assert resp.status_code == 400
        assert resp.json()["detail"] == "Cannot delete the last enabled provider"

        # Провайдер НЕ удалён, default_provider не сломан
        assert "routerai" in router.state.providers
        assert router.state.default_provider == "routerai"
        assert router.state.is_provider_enabled(router.state.default_provider)
