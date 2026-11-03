"""
Phase 5 — регресс-тесты на 4 бага, найденных Coordinator'ом при ручном прогоне.

БАГ 1 — цена бралась у ЧУЖОГО провайдера (cross-provider price leak)
БАГ 2 — total_cost суммировал разные валюты без пересчёта в базовую (RUB)
БАГ 3 — POST /config затирал соседние роли (merge вместо replace)
БАГ 4 — двойной префикс в GET /v1/models (provider::provider::model_id)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


def _usd_rate() -> float:
    """Курс из config.yaml — тесты не хардкодят 90.0."""
    return float(router.cfg["currency"]["usd_rate"])


# ============================================================
# БАГ 1 — цена бралась у ЧУЖОГО провайдера
# ============================================================


class TestBug1CrossProviderPriceLeak:
    """
    БАГ 1: log_usage() искал цену по голому model_id, без привязки к провайдеру.
    Для 'openrouter::z-ai/glm-5.2' бралась запись routerai (8.1685 RUB)
    вместо openrouter (0.006 USD) — ошибка в 1136 раз.

    Исправление: шаг 3 — get_model_info(bare_id, provider) с явным указанием провайдера.
    """

    def _setup_glm_catalog(self):
        """z-ai/glm-5.2 у двух провайдеров с разными ценами и валютами."""
        router.state.available_models = {
            "routerai::z-ai/glm-5.2": {
                "id": "z-ai/glm-5.2",
                "provider": "routerai",
                "input_price_1m": 8.1685,
                "output_price_1m": 16.337,
                "currency": "RUB",
                "price_source": "api",
            },
            "openrouter::z-ai/glm-5.2": {
                "id": "z-ai/glm-5.2",
                "provider": "openrouter",
                "input_price_1m": 0.006,
                "output_price_1m": 0.024,
                "currency": "USD",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {
            "routerai": ["z-ai/glm-5.2"],
            "openrouter": ["z-ai/glm-5.2"],
        }

    def _reset_stats(self):
        router.state.stats = {
            "requests": 0,
            "total_input": 0,
            "total_output": 0,
            "total_cost": 0.0,
            "currency": router.cfg["currency"]["base"],
            "usd_rate": _usd_rate(),
            "by_currency": {},
            "usd_equivalent": 0.0,
            "by_model": {},
            "routed_count": 0,
            "not_routed_count": 0,
            "fallback_count": 0,
            "started_at": 0,
        }

    def test_openrouter_glm_uses_openrouter_catalog(self):
        """
        openrouter::z-ai/glm-5.2 → цена из каталога openrouter (USD),
        а НЕ из каталога routerai (RUB).

        На старом коде: get_model_info('z-ai/glm-5.2') без провайдера →
        искал по всем провайдерам, находил routerai (default_provider) →
        8.1685 RUB вместо 0.006 USD.
        """
        self._setup_glm_catalog()
        self._reset_stats()

        router.log_usage("openrouter::z-ai/glm-5.2", 1_000_000, 500_000)

        # cost = (1M*0.006 + 0.5M*0.024) / 1M = 0.006 + 0.012 = 0.018 USD
        expected_cost_usd = 0.018
        by_currency = router.state.stats["by_currency"]
        assert by_currency.get("USD", 0) == pytest.approx(expected_cost_usd, rel=1e-6), (
            f"Expected USD cost {expected_cost_usd}, got {by_currency}"
        )
        # total_cost в RUB: native USD * usd_rate (90 ₽ за 1 USD), НЕ / usd_rate
        expected_total_rub = expected_cost_usd * _usd_rate()
        assert router.state.stats["total_cost"] == pytest.approx(expected_total_rub, rel=1e-6)
        # В by_currency НЕ ДОЛЖНО быть RUB (цена не из routerai)
        assert "RUB" not in by_currency, (
            f"RUB should not be in by_currency: {by_currency}"
        )

    def test_manual_price_overrides_catalog(self):
        """
        Случай A: есть ручная цена в PRICES → она побеждает каталог.

        Ручная цена инжектится в PRICES прямо в тесте, поэтому тест
        не зависит от содержимого config.yaml. После проверки PRICES
        восстанавливается в исходное состояние.

        log_usage() не сохраняет price_source в stats (это локальная
        переменная), поэтому «manual» проверяем по наблюдаемому контракту:
        ключ присутствует в PRICES, а cost посчитан по ручным числам,
        которые заведомо отличаются от каталога.
        """
        self._setup_glm_catalog()
        self._reset_stats()

        key = "routerai::z-ai/glm-5.2"
        manual_input = 999.0
        manual_output = 1999.0
        manual_price = {
            "input": manual_input,
            "output": manual_output,
            "provider": "RouterAI",
            "emoji": "🧪",
            "role": "Coordinator",
            "currency": "RUB",
        }

        sentinel = object()
        orig_price = router.PRICES.get(key, sentinel)
        router.PRICES[key] = manual_price
        try:
            router.log_usage(key, 1_000_000, 500_000)

            # cost = (1M*999 + 0.5M*1999) / 1M = 999 + 999.5 = 1998.5 RUB
            expected_cost_rub = (
                1_000_000 * manual_input + 500_000 * manual_output
            ) / 1_000_000
            by_currency = router.state.stats["by_currency"]
            assert by_currency.get("RUB", 0) == pytest.approx(
                expected_cost_rub, rel=1e-6
            ), f"Expected RUB cost {expected_cost_rub}, got {by_currency}"
            # total_cost в RUB (factor=1.0)
            assert router.state.stats["total_cost"] == pytest.approx(
                expected_cost_rub, rel=1e-6
            )
            assert "USD" not in by_currency

            # Ручная цена действительно отличается от каталога — значит
            # победил именно PRICES, а не каталог провайдера.
            catalog = router.state.get_model_info("z-ai/glm-5.2", "routerai")
            assert catalog is not None
            assert catalog["input_price_1m"] != manual_input
            assert catalog["output_price_1m"] != manual_output
        finally:
            if orig_price is sentinel:
                router.PRICES.pop(key, None)
            else:
                router.PRICES[key] = orig_price

    def test_without_manual_price_uses_provider_catalog(self):
        """
        Случай B: нет ручной цены → цена берётся из каталога провайдера.

        Значения не хардкодятся — берутся из state.get_model_info(),
        поэтому тест стабилен при изменении цен провайдером.
        """
        self._setup_glm_catalog()
        self._reset_stats()

        key = "routerai::z-ai/glm-5.2"
        # Ручной цены нет — источником должен стать каталог.
        assert key not in router.PRICES

        catalog = router.state.get_model_info("z-ai/glm-5.2", "routerai")
        assert catalog is not None
        assert catalog["price_source"] == "api"

        router.log_usage(key, 1_000_000, 500_000)

        # cost = (1M*input_price_1m + 0.5M*output_price_1m) / 1M
        expected_cost_rub = (
            1_000_000 * catalog["input_price_1m"]
            + 500_000 * catalog["output_price_1m"]
        ) / 1_000_000
        by_currency = router.state.stats["by_currency"]
        assert by_currency.get("RUB", 0) == pytest.approx(
            expected_cost_rub, rel=1e-6
        ), f"Expected RUB cost {expected_cost_rub}, got {by_currency}"
        # total_cost в RUB (factor=1.0)
        assert router.state.stats["total_cost"] == pytest.approx(
            expected_cost_rub, rel=1e-6
        )
        assert "USD" not in by_currency

    def test_openrouter_deepseek_pro_uses_openrouter_catalog(self):
        """
        openrouter::deepseek/deepseek-v4-pro → цена из каталога openrouter (USD),
        а НЕ из каталога routerai (default_provider).
        """
        router.state.available_models = {
            "openrouter::deepseek/deepseek-v4-pro": {
                "id": "deepseek/deepseek-v4-pro",
                "provider": "openrouter",
                "input_price_1m": 1.6,
                "output_price_1m": 4.8,
                "currency": "USD",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {
            "openrouter": ["deepseek/deepseek-v4-pro"],
        }
        self._reset_stats()

        router.log_usage("openrouter::deepseek/deepseek-v4-pro", 1_000_000, 500_000)

        # cost = (1M*1.6 + 0.5M*4.8) / 1M = 1.6 + 2.4 = 4.0 USD
        expected_cost_usd = 4.0
        by_currency = router.state.stats["by_currency"]
        assert by_currency.get("USD", 0) == pytest.approx(expected_cost_usd, rel=1e-6)
        # total_cost = 4.0 * usd_rate = 360.0 RUB (НЕ 4.0 / usd_rate)
        assert router.state.stats["total_cost"] == pytest.approx(
            expected_cost_usd * _usd_rate(), rel=1e-6
        )
        assert "RUB" not in by_currency


# ============================================================
# БАГ 2 — total_cost суммировал разные валюты без пересчёта
# ============================================================


class TestBug2TotalCostConversion:
    """
    БАГ 2: by_currency копился в native-валюте (правильно), а total_cost
    складывал сырые значения рублей и долларов — сумма была бессмысленной.

    Исправление: state.stats['total_cost'] += cost * factor,
    где factor = _to_base_factor(currency) — сколько RUB стоит 1 единица
    валюты (RUB→1.0, USD→usd_rate, NONE→1.0).
    """

    def _reset_stats(self):
        router.state.stats = {
            "requests": 0,
            "total_input": 0,
            "total_output": 0,
            "total_cost": 0.0,
            "currency": router.cfg["currency"]["base"],
            "usd_rate": _usd_rate(),
            "by_currency": {},
            "usd_equivalent": 0.0,
            "by_model": {},
            "routed_count": 0,
            "not_routed_count": 0,
            "fallback_count": 0,
            "started_at": 0,
        }

    def test_usd_total_cost_converted_to_rub(self):
        """USD-модель: total_cost += cost * usd_rate (в RUB), by_currency[USD] = cost (native)."""
        router.state.available_models = {
            "test::usd-model": {
                "id": "usd-model",
                "provider": "test",
                "input_price_1m": 2.0,
                "output_price_1m": 4.0,
                "currency": "USD",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {"test": ["usd-model"]}
        self._reset_stats()

        router.log_usage("test::usd-model", 1_000_000, 500_000)

        # cost = (1M*2 + 0.5M*4) / 1M = 4.0 USD
        cost = 4.0
        assert router.state.stats["by_currency"].get("USD", 0) == pytest.approx(cost, rel=1e-6)
        # total_cost = 4.0 * usd_rate = 360.0 RUB
        assert router.state.stats["total_cost"] == pytest.approx(
            cost * _usd_rate(), rel=1e-6
        )
        # usd_equivalent = cost (USD не конвертируется)
        assert router.state.stats["usd_equivalent"] == pytest.approx(cost, rel=1e-6)

    def test_rub_total_cost_no_conversion(self):
        """RUB-модель: total_cost += cost * 1.0, by_currency[RUB] = cost (native)."""
        router.state.available_models = {
            "test::rub-model": {
                "id": "rub-model",
                "provider": "test",
                "input_price_1m": 10.0,
                "output_price_1m": 20.0,
                "currency": "RUB",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {"test": ["rub-model"]}
        self._reset_stats()

        router.log_usage("test::rub-model", 1_000_000, 500_000)

        # cost = (1M*10 + 0.5M*20) / 1M = 20.0 RUB
        cost = 20.0
        assert router.state.stats["by_currency"].get("RUB", 0) == pytest.approx(cost, rel=1e-6)
        assert router.state.stats["total_cost"] == pytest.approx(cost, rel=1e-6)  # factor=1.0
        # usd_equivalent = cost / usd_rate
        assert router.state.stats["usd_equivalent"] == pytest.approx(
            cost / _usd_rate(), rel=1e-6
        )

    def test_none_currency_zero_cost(self):
        """
        NONE-валюта (бесплатная): не создаёт запись в by_currency,
        total_cost и usd_equivalent не меняются.
        """
        router.state.available_models = {
            "ollama::free-model": {
                "id": "free-model",
                "provider": "ollama",
                "input_price_1m": 0.0,
                "output_price_1m": 0.0,
                "currency": "NONE",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {"ollama": ["free-model"]}
        self._reset_stats()

        router.log_usage("ollama::free-model", 1_000_000, 500_000)

        # Бесплатная модель не должна создавать запись в by_currency
        assert "NONE" not in router.state.stats["by_currency"]
        # total_cost и usd_equivalent не меняются
        assert router.state.stats["total_cost"] == 0.0
        assert router.state.stats["usd_equivalent"] == 0.0

    def test_mixed_currencies_total_cost(self):
        """
        Две модели в разных валютах: total_cost суммируется корректно
        (RUB * 1.0 + USD * usd_rate), а by_currency раздельно.
        """
        router.state.available_models = {
            "test::rub-m": {
                "id": "rub-m",
                "provider": "test",
                "input_price_1m": 10.0,
                "output_price_1m": 20.0,
                "currency": "RUB",
                "price_source": "api",
            },
            "test::usd-m": {
                "id": "usd-m",
                "provider": "test",
                "input_price_1m": 2.0,
                "output_price_1m": 4.0,
                "currency": "USD",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {"test": ["rub-m", "usd-m"]}
        self._reset_stats()

        router.log_usage("test::rub-m", 1_000_000, 500_000)  # cost_rub = 20.0
        router.log_usage("test::usd-m", 1_000_000, 500_000)  # cost_usd = 4.0

        # total_cost = 20.0 * 1.0 + 4.0 * usd_rate = 380.0 RUB
        expected_total = 20.0 + 4.0 * _usd_rate()
        assert router.state.stats["total_cost"] == pytest.approx(expected_total, rel=1e-6)
        assert router.state.stats["by_currency"]["RUB"] == pytest.approx(20.0, rel=1e-6)
        assert router.state.stats["by_currency"]["USD"] == pytest.approx(4.0, rel=1e-6)


# ============================================================
# БАГ 3 — POST /config затирал соседние роли
# ============================================================


class TestBug3ConfigMerge:
    """
    БАГ 3: save_config делал self.config.update(new_config) →
    словари заменялись целиком. POST /config {'role_models': {'worker_default': 'x'}}
    убивал coordinator и worker_img.

    Исправление: _merge_config — merge на один уровень вглубь
    (если и старое, и новое — dict → {**old, **new}, иначе новое заменяет старое).
    """

    def test_merge_config_preserves_sibling_roles(self):
        """save_config с одной ролью → остальные роли сохранены."""
        # isolate_config установил state.config с role_models
        original = dict(router.state.config.get("role_models", {}))
        assert "coordinator" in original
        assert "worker_img" in original
        assert "worker_default" in original

        import asyncio
        asyncio.run(
            router.state.save_config({"role_models": {"worker_default": "ollama::x"}})
        )

        assert router.state.config["role_models"]["coordinator"] == original["coordinator"]
        assert router.state.config["role_models"]["worker_img"] == original["worker_img"]
        assert router.state.config["role_models"]["worker_default"] == "ollama::x"

    def test_merge_config_none_value(self):
        """save_config с None → роль становится None, остальные целы."""
        original = dict(router.state.config.get("role_models", {}))

        import asyncio
        asyncio.run(
            router.state.save_config({"role_models": {"coordinator": None}})
        )

        assert router.state.config["role_models"]["coordinator"] is None
        assert router.state.config["role_models"]["worker_default"] == original["worker_default"]
        assert router.state.config["role_models"]["worker_img"] == original["worker_img"]

    def test_merge_config_scalar_replacement(self):
        """save_config со скалярным значением → полная замена (не dict-merge)."""
        import asyncio
        asyncio.run(
            router.state.save_config({"enable_auto_routing": False})
        )

        assert router.state.config["enable_auto_routing"] is False
        # role_models не тронуты
        assert "role_models" in router.state.config

    def test_merge_config_static_method(self):
        """_merge_config: unit-тест логики слияния."""
        from router import RouterState

        # dict + dict → вложенный merge
        result = RouterState._merge_config(
            {"a": {"x": 1, "y": 2}, "b": 3},
            {"a": {"y": 99, "z": 100}},
        )
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

        # scalar → replace
        result = RouterState._merge_config({"a": 1}, {"a": 2})
        assert result == {"a": 2}

        # None → replace (даже если old — dict)
        result = RouterState._merge_config({"a": {"x": 1}}, {"a": None})
        assert result == {"a": None}

        # новый ключ → добавить
        result = RouterState._merge_config({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    async def test_post_config_preserves_roles_via_http(self, client):
        """POST /config с одной ролью → остальные роли сохранены (через HTTP)."""
        original = dict(router.state.config.get("role_models", {}))

        resp = await client.post("/config", json={
            "role_models": {"worker_default": "ollama::y"},
        })
        assert resp.status_code == 200, f"POST /config failed: {resp.text}"

        assert router.state.config["role_models"]["coordinator"] == original["coordinator"]
        assert router.state.config["role_models"]["worker_img"] == original["worker_img"]
        assert router.state.config["role_models"]["worker_default"] == "ollama::y"


# ============================================================
# БАГ 4 — двойной префикс в GET /v1/models
# ============================================================


class TestBug4DoublePrefix:
    """
    БАГ 4: config.yaml models: содержит ключи вида 'routerai::model'.
    Старый код делал f'{{default_provider}}::{model_name}' →
    'routerai::routerai::model'. Двойной префикс.

    Исправление: _split_config_model_key() разделяет по первому ::,
    и composite_id строится из provider + model_id по отдельности.
    """

    def test_split_bare_key(self):
        """_split_config_model_key('a/b') → (None, 'a/b')."""
        provider, model_id = router._split_config_model_key("a/b")
        assert provider is None
        assert model_id == "a/b"

    def test_split_composite_key(self):
        """_split_config_model_key('routerai::a/b') → ('routerai', 'a/b')."""
        provider, model_id = router._split_config_model_key("routerai::a/b")
        assert provider == "routerai"
        assert model_id == "a/b"

    def test_split_double_colon_in_model_id(self):
        """_split_config_model_key('a::b::c') → ('a', 'b::c') — split по ПЕРВОМУ ::."""
        provider, model_id = router._split_config_model_key("a::b::c")
        assert provider == "a"
        assert model_id == "b::c"

    async def test_v1_models_no_double_prefix(self, client):
        """GET /v1/models → ни одного ID с двумя ::."""
        # Добавляем модель в кеш, чтобы проверить обе ветки list_models
        router.state.available_models = {
            "openrouter::some/test-model": {
                "id": "some/test-model",
                "provider": "openrouter",
                "input_price_1m": 1.0,
                "output_price_1m": 2.0,
                "currency": "USD",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {"openrouter": ["some/test-model"]}

        resp = await client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) > 0, "GET /v1/models вернул пустой список"

        for model in data["data"]:
            mid = model["id"]
            assert mid.count("::") == 1, (
                f"ID содержит {mid.count('::')} :: (должен быть 1): {mid}"
            )


# ============================================================
# БАГ 5 — курс валюты был инвертирован
# ============================================================


class TestBug5InvertedCurrencyRate:
    """
    БАГ 5: курс валюты был инвертирован.

    В config.yaml лежало rates: {USD: 0.011111} (= 1/90, «USD за 1 ₽»),
    а код умножал native-стоимость на этот коэффициент. Для USD-моделей
    total_cost занижался в 8100 раз (0.0000044 вместо 0.036 ₽).

    Исправление: _to_base_factor(currency) — сколько RUB стоит 1 единица
    валюты: RUB → 1.0, USD → usd_rate (90.0), NONE → 1.0.
    """

    def _reset_stats(self):
        router.state.stats = {
            "requests": 0,
            "total_input": 0,
            "total_output": 0,
            "total_cost": 0.0,
            "currency": router.cfg["currency"]["base"],
            "usd_rate": _usd_rate(),
            "by_currency": {},
            "usd_equivalent": 0.0,
            "by_model": {},
            "routed_count": 0,
            "not_routed_count": 0,
            "fallback_count": 0,
            "started_at": 0,
        }

    def _setup_usd_model(self):
        router.state.available_models = {
            "test::usd-model": {
                "id": "usd-model",
                "provider": "test",
                "input_price_1m": 2.0,
                "output_price_1m": 4.0,
                "currency": "USD",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {"test": ["usd-model"]}

    def _setup_rub_model(self):
        router.state.available_models = {
            "test::rub-model": {
                "id": "rub-model",
                "provider": "test",
                "input_price_1m": 10.0,
                "output_price_1m": 20.0,
                "currency": "RUB",
                "price_source": "api",
            },
        }
        router.state.models_by_provider = {"test": ["rub-model"]}

    def test_usd_total_cost_multiplies_by_usd_rate(self):
        """USD: total_cost == by_currency['USD'] * usd_rate (а НЕ / usd_rate)."""
        self._setup_usd_model()
        self._reset_stats()

        router.log_usage("test::usd-model", 1_000_000, 500_000)

        # cost = (1M*2 + 0.5M*4) / 1M = 4.0 USD
        usd_rate = _usd_rate()
        stats = router.state.stats
        native_usd = stats["by_currency"]["USD"]
        assert native_usd == pytest.approx(4.0, rel=1e-6)

        # Правильное направление: RUB за 1 USD
        assert stats["total_cost"] == pytest.approx(native_usd * usd_rate, rel=1e-6)
        # Инвертированный курс (1/90) дал бы 0.044444 — такого быть не должно
        assert stats["total_cost"] != pytest.approx(native_usd / usd_rate)

        # usd_equivalent для USD-модели == native-стоимость
        assert stats["usd_equivalent"] == pytest.approx(native_usd, rel=1e-6)

    def test_rub_total_cost_uses_factor_one(self):
        """RUB: total_cost == by_currency['RUB'] (фактор 1.0)."""
        self._setup_rub_model()
        self._reset_stats()

        router.log_usage("test::rub-model", 1_000_000, 500_000)

        # cost = (1M*10 + 0.5M*20) / 1M = 20.0 RUB
        usd_rate = _usd_rate()
        stats = router.state.stats
        native_rub = stats["by_currency"]["RUB"]
        assert native_rub == pytest.approx(20.0, rel=1e-6)

        assert stats["total_cost"] == pytest.approx(native_rub, rel=1e-6)
        # usd_equivalent для RUB-модели == native / usd_rate
        assert stats["usd_equivalent"] == pytest.approx(native_rub / usd_rate, rel=1e-6)

    def test_total_cost_equals_usd_equivalent_times_usd_rate(self):
        """Связка: total_cost (в базовой валюте) == usd_equivalent * usd_rate."""
        self._setup_rub_model()
        router.state.available_models["test::usd-model"] = {
            "id": "usd-model",
            "provider": "test",
            "input_price_1m": 2.0,
            "output_price_1m": 4.0,
            "currency": "USD",
            "price_source": "api",
        }
        router.state.models_by_provider = {"test": ["rub-model", "usd-model"]}
        self._reset_stats()

        router.log_usage("test::rub-model", 1_000_000, 500_000)  # 20.0 RUB
        router.log_usage("test::usd-model", 1_000_000, 500_000)  # 4.0 USD

        usd_rate = _usd_rate()
        stats = router.state.stats

        # total_cost = 20.0 + 4.0 * usd_rate = 380.0 RUB
        assert stats["total_cost"] == pytest.approx(20.0 + 4.0 * usd_rate, rel=1e-6)
        # usd_equivalent = 20.0 / usd_rate + 4.0
        assert stats["usd_equivalent"] == pytest.approx(20.0 / usd_rate + 4.0, rel=1e-6)
        # Связка между базовой суммой и USD-эквивалентом
        assert stats["total_cost"] == pytest.approx(
            stats["usd_equivalent"] * usd_rate, rel=1e-6
        )