"""
Phase 5 — семантика ручных цен в config.yaml.

Секция ``models:`` теперь содержит только метаданные (emoji/provider/role)
и НЕ содержит input_price/output_price. Цена таких моделей берётся из
живого каталога провайдера. Записи с ценами остаются ручным override'ом
(свой прокси, self-hosted, спец-цены) и попадают в ``router.PRICES``.

Проверяем:
- запись без input_price/output_price не попадает в PRICES;
- запись с ценами попадает в PRICES с ожидаемыми значениями;
- импорт роутера не ломается при наличии «метаданных без цен».
"""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestPricesFromCurrentConfig:
    """Контракт PRICES на реальном config.yaml."""

    def test_prices_matches_config_contract(self):
        """
        Для каждой записи cfg['models']:
        - есть оба поля цены → ключ есть в PRICES и значения совпадают;
        - нет цены → ключа в PRICES нет.
        """
        models_cfg = router.cfg.get("models", {})
        assert isinstance(models_cfg, dict)

        for key, model_cfg in models_cfg.items():
            has_prices = (
                "input_price" in model_cfg and "output_price" in model_cfg
            )
            if has_prices:
                assert key in router.PRICES, (
                    f"{key}: цена задана в config.yaml, но отсутствует в PRICES"
                )
                assert router.PRICES[key]["input"] == model_cfg["input_price"]
                assert router.PRICES[key]["output"] == model_cfg["output_price"]
            else:
                assert key not in router.PRICES, (
                    f"{key}: запись без цены не должна попадать в PRICES"
                )

    def test_metadata_only_entries_not_in_prices(self):
        """Явная проверка: все записи без input_price отсутствуют в PRICES."""
        for key, model_cfg in router.cfg.get("models", {}).items():
            if "input_price" not in model_cfg:
                assert key not in router.PRICES
            if "output_price" not in model_cfg:
                assert key not in router.PRICES

    def test_prices_entries_have_required_fields(self):
        """Каждая запись PRICES содержит input/output/currency."""
        for key, price in router.PRICES.items():
            assert "input" in price, f"{key}: нет input"
            assert "output" in price, f"{key}: нет output"
            assert "currency" in price, f"{key}: нет currency"


class TestSyntheticConfig:
    """
    Синтетический config.yaml в изолированном процессе.

    Реальный config.yaml не трогаем: копируем router.py во временную
    директорию и подкладываем туда свой config.yaml, затем импортируем
    копию в subprocess и смотрим на построенный PRICES.
    """

    def _run_router_import(self, tmp_path, models_cfg):
        """Копирует router.py + синтетический config.yaml и импортирует его."""
        shutil.copy(Path(router.__file__), tmp_path / "router.py")

        synth = copy.deepcopy(router.cfg)
        synth["models"] = models_cfg
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump(synth, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        # routing.json обязателен: иначе _init_default_config() обращается
        # к ещё не созданному глобальному state (см. router.py).
        (tmp_path / "routing.json").write_text(
            json.dumps(
                {
                    "role_models": {
                        "coordinator": "test::with-price",
                        "worker_default": "test::no-price",
                        "worker_img": "test::no-price",
                    },
                    "agent_to_worker_mapping": {},
                    "default_worker": "test::no-price",
                    "enable_auto_routing": True,
                }
            ),
            encoding="utf-8",
        )

        code = "import json, router; print(json.dumps(router.PRICES))"
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, (
            "Импорт router.py с синтетическим config.yaml упал:\n"
            f"{proc.stderr}"
        )
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_entry_with_price_goes_to_prices(self, tmp_path):
        """Запись с input_price/output_price попадает в PRICES."""
        prices = self._run_router_import(
            tmp_path,
            {
                "test::with-price": {
                    "emoji": "💎",
                    "provider": "Test",
                    "role": "Worker",
                    "input_price": 12.5,
                    "output_price": 50.0,
                    "currency": "RUB",
                },
            },
        )

        assert "test::with-price" in prices
        assert prices["test::with-price"]["input"] == 12.5
        assert prices["test::with-price"]["output"] == 50.0
        assert prices["test::with-price"]["currency"] == "RUB"

    def test_entry_without_price_skipped(self, tmp_path):
        """Запись без цен не попадает в PRICES и не ломает импорт."""
        prices = self._run_router_import(
            tmp_path,
            {
                "test::no-price": {
                    "emoji": "🤖",
                    "provider": "Test",
                    "role": "Worker",
                },
            },
        )

        assert "test::no-price" not in prices
        assert prices == {}

    def test_mixed_entries(self, tmp_path):
        """В одном config.yaml: с ценой → в PRICES, без цены → нет."""
        prices = self._run_router_import(
            tmp_path,
            {
                "test::with-price": {
                    "emoji": "💎",
                    "provider": "Test",
                    "role": "Worker",
                    "input_price": 1.0,
                    "output_price": 2.0,
                    "currency": "USD",
                },
                "test::no-price": {
                    "emoji": "🤖",
                    "provider": "Test",
                    "role": "Worker",
                },
            },
        )

        assert set(prices) == {"test::with-price"}
        assert prices["test::with-price"]["currency"] == "USD"

    def test_partial_price_skipped(self, tmp_path):
        """Только input_price без output_price → запись пропускается."""
        prices = self._run_router_import(
            tmp_path,
            {
                "test::partial": {
                    "emoji": "🤖",
                    "provider": "Test",
                    "role": "Worker",
                    "input_price": 3.0,
                },
            },
        )

        assert "test::partial" not in prices
        assert prices == {}
