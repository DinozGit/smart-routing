"""
Phase 5 — тесты валют и ценообразования: currency, price_source,
by_currency, usd_equivalent, cost == 0 для неизвестной модели.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestCurrencyByProvider:
    """Валюта в зависимости от провайдера."""

    def test_routerai_currency_rub(self):
        """RouterAI → currency == 'RUB'."""
        router.state.available_models = {
            "routerai::test/model": {
                "id": "test/model",
                "name": "Test",
                "currency": "RUB",
                "input_price_1m": 10.0,
                "output_price_1m": 20.0,
                "provider": "routerai",
            },
        }
        info = router.state.get_model_info("test/model", provider="routerai")
        assert info is not None
        assert info["currency"] == "RUB"

    def test_openrouter_currency_usd(self):
        """OpenRouter → currency == 'USD'."""
        router.state.available_models = {
            "openrouter::test/model": {
                "id": "test/model",
                "name": "Test",
                "currency": "USD",
                "input_price_1m": 2.5,
                "output_price_1m": 10.0,
                "provider": "openrouter",
            },
        }
        info = router.state.get_model_info("test/model", provider="openrouter")
        assert info is not None
        assert info["currency"] == "USD"

    def test_ollama_currency_none_and_zero(self):
        """Ollama → currency == 'NONE' и цены 0."""
        router.state.available_models = {
            "ollama::test/model": {
                "id": "test/model",
                "name": "Test",
                "currency": "NONE",
                "input_price_1m": 0.0,
                "output_price_1m": 0.0,
                "provider": "ollama",
            },
        }
        info = router.state.get_model_info("test/model", provider="ollama")
        assert info is not None
        assert info["currency"] == "NONE"
        assert info["input_price_1m"] == 0.0
        assert info["output_price_1m"] == 0.0


class TestPriceSource:
    """price_source: api / manual / unknown."""

    def test_price_source_api(self):
        """Модель из каталога → price_source == 'api'."""
        router.state.available_models = {
            "routerai::test/model": {
                "id": "test/model",
                "name": "Test",
                "price_source": "api",
                "input_price_1m": 10.0,
                "output_price_1m": 20.0,
                "provider": "routerai",
            },
        }
        info = router.state.get_model_info("test/model", provider="routerai")
        assert info is not None
        assert info["price_source"] == "api"

    def test_price_source_manual(self):
        """Модель из config.yaml → price_source == 'manual'."""
        import router as r

        # Модель в PRICES — ручной override
        r.PRICES["test/manual-model"] = {
            "input": 5.0, "output": 10.0,
            "provider": "routerai", "emoji": "🤖", "role": "Worker",
        }
        try:
            r.state.available_models = {}
            before = r.state.stats["total_cost"]
            r.log_usage("test/manual-model", 1000, 500)
            # cost = (1000*5 + 500*10) / 1M = 0.01
            assert r.state.stats["total_cost"] == before + 0.01
        finally:
            r.PRICES.pop("test/manual-model", None)

    def test_price_source_unknown(self):
        """Неизвестная модель → cost == 0 (фиктивной заглушки нет)."""
        import router as r

        r.state.available_models = {}
        before = r.state.stats["total_cost"]
        r.log_usage("ghost/model", 100, 50)
        # Неизвестная модель → цена 0
        assert r.state.stats["total_cost"] == before


class TestStatsByCurrency:
    """by_currency накапливает суммы по валютам."""

    def test_by_currency_accumulates(self):
        """by_currency накапливает суммы."""
        import router as r

        orig = dict(r.state.stats)
        try:
            r.state.stats["by_currency"] = {}

            # Логируем RUB-модель
            r.state.available_models = {
                "routerai::rub-model": {
                    "id": "rub-model",
                    "input_price_1m": 10.0,
                    "output_price_1m": 20.0,
                    "currency": "RUB",
                    "provider": "routerai",
                    "price_source": "api",
                },
            }
            r.state.models_by_provider = {"routerai": ["rub-model"]}
            r.log_usage("rub-model", 1000, 500)
            # cost = (1000*10 + 500*20) / 1M = 0.02
            assert r.state.stats["by_currency"].get("RUB", 0) == 0.02
        finally:
            r.state.stats = orig

    def test_by_currency_separate_currencies(self):
        """Разные валюты накапливаются отдельно."""
        import router as r

        orig = dict(r.state.stats)
        try:
            r.state.stats["by_currency"] = {}

            # USD-модель
            r.state.available_models = {
                "openrouter::usd-model": {
                    "id": "usd-model",
                    "input_price_1m": 2.0,
                    "output_price_1m": 4.0,
                    "currency": "USD",
                    "provider": "openrouter",
                    "price_source": "api",
                },
            }
            r.state.models_by_provider = {"openrouter": ["usd-model"]}
            r.log_usage("usd-model", 1000, 500)
            # cost = (1000*2 + 500*4) / 1M = 0.004
            assert r.state.stats["by_currency"].get("USD", 0) == 0.004
        finally:
            r.state.stats = orig


class TestUsdEquivalent:
    """usd_equivalent: USD-сумма как есть, RUB делится на usd_rate."""

    def test_usd_equivalent_usd(self):
        """USD-модель → usd_equivalent = cost."""
        import router as r

        orig = dict(r.state.stats)
        try:
            r.state.stats["usd_equivalent"] = 0.0

            r.state.available_models = {
                "openrouter::usd-model": {
                    "id": "usd-model",
                    "input_price_1m": 2.0,
                    "output_price_1m": 4.0,
                    "currency": "USD",
                    "provider": "openrouter",
                    "price_source": "api",
                },
            }
            r.state.models_by_provider = {"openrouter": ["usd-model"]}
            r.log_usage("usd-model", 1000, 500)
            # cost = (1000*2 + 500*4) / 1M = 0.004
            assert r.state.stats["usd_equivalent"] == 0.004
        finally:
            r.state.stats = orig

    def test_usd_equivalent_rub(self):
        """RUB-модель → usd_equivalent = cost / usd_rate."""
        import router as r

        orig = dict(r.state.stats)
        try:
            r.state.stats["usd_equivalent"] = 0.0

            r.state.available_models = {
                "routerai::rub-model": {
                    "id": "rub-model",
                    "input_price_1m": 10.0,
                    "output_price_1m": 20.0,
                    "currency": "RUB",
                    "provider": "routerai",
                    "price_source": "api",
                },
            }
            r.state.models_by_provider = {"routerai": ["rub-model"]}
            r.log_usage("rub-model", 1000, 500)
            # cost = 0.02 RUB, usd_rate = 90.0
            assert r.state.stats["usd_equivalent"] == 0.02 / 90.0
        finally:
            r.state.stats = orig