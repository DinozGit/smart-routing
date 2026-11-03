"""
Phase 6 — F1: запрет неявного кросс-провайдерного резолва голого model_id.

Контракт: docs/PROVIDER_CONTRACT.md, раздел F1, тесты 1–4.

- source="client", allow_cross_provider_bare_id=false (default) → голый ID
  ищется только в каталоге default_provider; есть только у другого
  провайдера → default_provider (не утечка на чужой провайдер).
- флаг=true → старое поведение (поиск по всем провайдерам).
- source="config" → всегда старое поведение (операторский конфиг не ломаем).
- Явная спецификация provider::model → не зависит от флага.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


class TestF1BareIdResolution:
    """F1: резолв голого model_id в resolve_model_spec."""

    def test_bare_id_stays_in_default_provider(self, bare_catalog):
        """Голый ID есть только у openrouter → default_provider, НЕ openrouter."""
        prov, mid = router.resolve_model_spec("qwen/qwen3-coder-next", "client")
        assert prov == "routerai", f"Запрос утёк на чужой провайдер: {prov}"
        assert mid == "qwen/qwen3-coder-next"

    def test_bare_id_flag_enables_cross_provider(self, bare_catalog):
        """allow_cross_provider_bare_id=true → старое поведение: openrouter."""
        router.state.config["allow_cross_provider_bare_id"] = True
        prov, mid = router.resolve_model_spec("qwen/qwen3-coder-next", "client")
        assert prov == "openrouter"
        assert mid == "qwen/qwen3-coder-next"

    def test_config_source_keeps_old_behaviour(self, bare_catalog):
        """source="config" → поиск по всем провайдерам при любом флаге."""
        router.state.config["allow_cross_provider_bare_id"] = False
        prov, mid = router.resolve_model_spec("qwen/qwen3-coder-next", "config")
        assert prov == "openrouter"
        assert mid == "qwen/qwen3-coder-next"

    def test_explicit_spec_unaffected(self, clean_providers, bare_catalog):
        """openrouter::model → openrouter при allow_cross_provider_bare_id=false и true."""
        router.state.config["allow_cross_provider_bare_id"] = False
        prov, mid = router.resolve_model_spec("openrouter::qwen/qwen3-coder-next", "client")
        assert prov == "openrouter"
        assert mid == "qwen/qwen3-coder-next"

        router.state.config["allow_cross_provider_bare_id"] = True
        prov, mid = router.resolve_model_spec("openrouter::qwen/qwen3-coder-next", "client")
        assert prov == "openrouter"
        assert mid == "qwen/qwen3-coder-next"