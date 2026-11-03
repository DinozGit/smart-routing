"""
Phase 6 — F5: INFO-лог выбора провайдера.

Контракт: docs/PROVIDER_CONTRACT.md, раздел F5, тест 15.

Голый ID доступен только у не-default провайдера при
allow_cross_provider_bare_id=false → INFO-запись про использование default
с упоминанием флага. Логи пишутся модульным logger → ловим через caplog.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestF5ProviderChoiceLog:
    """F5: лог обоснования выбора провайдера."""

    def test_log_records_provider_choice(self, caplog, clean_providers):
        """Голый ID только у openrouter → INFO-лог про default (fail-closed)."""
        router.state.default_provider = "routerai"
        router.state.models_by_provider = {
            "routerai": ["deepseek/deepseek-v4-flash"],
            "openrouter": ["qwen/qwen3-coder-next"],
        }

        with caplog.at_level(logging.INFO, logger=router.logger.name):
            prov, _ = router.resolve_model_spec("qwen/qwen3-coder-next", "client")

        assert prov == "routerai"
        assert any(
            "allow_cross_provider_bare_id=false" in rec.getMessage()
            for rec in caplog.records
        ), "Нет INFO-лога F5 о выборе default провайдера"