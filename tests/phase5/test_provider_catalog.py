"""
Phase 5 — тесты каталога провайдеров: get_model_info, миграция v1→v2,
фильтрация моделей, parse_pricing, Ollama-формат.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import router


# ============================================================
# get_model_info — 4 шага поиска
# ============================================================


class TestGetModelInfo:
    """get_model_info: 4 шага поиска."""

    def test_exact_composite_key(self):
        """Шаг 1: точное совпадение 'provider::model_id'."""
        router.state.available_models = {
            "routerai::deepseek/deepseek-v4-pro": {
                "id": "deepseek/deepseek-v4-pro",
                "name": "Pro",
            },
        }
        router.state.models_by_provider = {"routerai": ["deepseek/deepseek-v4-pro"]}

        info = router.state.get_model_info("deepseek/deepseek-v4-pro", provider="routerai")
        assert info is not None
        assert info["name"] == "Pro"

    def test_bc_flat_key(self):
        """Шаг 2: BC-fallback — плоский ключ (v1-совместимость)."""
        router.state.available_models = {
            "old-flat-model": {"id": "old-flat-model", "name": "Old Flat"},
        }

        info = router.state.get_model_info("old-flat-model")
        assert info is not None
        assert info["name"] == "Old Flat"

    def test_search_all_providers_default_first(self):
        """Шаг 3: поиск по всем провайдерам, приоритет у default_provider."""
        router.state.available_models = {
            "openrouter::shared-model": {
                "id": "shared-model", "name": "Shared OR", "provider": "openrouter",
            },
            "routerai::shared-model": {
                "id": "shared-model", "name": "Shared RA", "provider": "routerai",
            },
        }
        router.state.models_by_provider = {
            "openrouter": ["shared-model"],
            "routerai": ["shared-model"],
        }
        router.state.default_provider = "routerai"

        info = router.state.get_model_info("shared-model")
        assert info is not None
        assert info["name"] == "Shared RA"

    def test_search_all_providers_alphabetical(self):
        """Шаг 3: default_provider не среди кандидатов → первый по алфавиту."""
        router.state.available_models = {
            "alpha::shared-model": {"id": "shared-model", "name": "Alpha", "provider": "alpha"},
            "beta::shared-model": {"id": "shared-model", "name": "Beta", "provider": "beta"},
        }
        router.state.models_by_provider = {
            "alpha": ["shared-model"],
            "beta": ["shared-model"],
        }
        router.state.default_provider = "gamma"

        info = router.state.get_model_info("shared-model")
        assert info is not None
        assert info["name"] == "Alpha"

    def test_not_found_returns_none(self):
        """Шаг 4: не найдено → None."""
        router.state.available_models = {}
        router.state.models_by_provider = {}

        info = router.state.get_model_info("nonexistent/model")
        assert info is None


# ============================================================
# Миграция v1 → v2
# ============================================================


class TestV1ToV2Migration:
    """Миграция кеша с v1 в v2."""

    def test_v1_migration_sets_provider_and_currency(self, tmp_path):
        """v1 → модели под provider, ключи составные, проставлены provider/currency/price_source."""
        old_file = router.state.models_cache_file
        try:
            v1_data = {
                "models": [
                    {
                        "id": "deepseek/deepseek-v4-pro",
                        "name": "DeepSeek V4 Pro",
                        "context_length": 1048576,
                        "input_price_1m": 61.9626,
                        "output_price_1m": 123.9251,
                        "output_modalities": ["text"],
                    },
                    {
                        "id": "deepseek/deepseek-v4-flash",
                        "name": "DeepSeek V4 Flash",
                        "context_length": 65536,
                        "input_price_1m": 5.0,
                        "output_price_1m": 10.0,
                        "output_modalities": ["text"],
                    },
                ],
                "last_sync": 1789642911.0,
                "provider": "routerai",
            }
            cache_file = tmp_path / "models_cache.json"
            cache_file.write_text(
                json.dumps(v1_data, indent=2), encoding="utf-8"
            )
            router.state.models_cache_file = cache_file
            router.state._load_models_cache()

            # Все модели под "routerai", ключи составные
            assert "routerai::deepseek/deepseek-v4-pro" in router.state.available_models
            assert "routerai::deepseek/deepseek-v4-flash" in router.state.available_models
            assert router.state.models_by_provider == {
                "routerai": ["deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash"]
            }

            # provider, currency, price_source проставлены
            for key, info in router.state.available_models.items():
                assert info["provider"] == "routerai"
                assert info["currency"] == "RUB"
                assert info["price_source"] == "api"
        finally:
            router.state.models_cache_file = old_file

    def test_v1_migration_filters_non_text(self, tmp_path):
        """v1: output_modalities != ["text"] → отбрасывается."""
        old_file = router.state.models_cache_file
        try:
            v1_data = {
                "models": [
                    {
                        "id": "text-model",
                        "name": "Text Only",
                        "output_modalities": ["text"],
                    },
                    {
                        "id": "image-text-model",
                        "name": "Image+Text",
                        "output_modalities": ["image", "text"],
                    },
                    {
                        "id": "text-audio-model",
                        "name": "Text+Audio",
                        "output_modalities": ["text", "audio"],
                    },
                ],
                "last_sync": None,
                "provider": "routerai",
            }
            cache_file = tmp_path / "models_cache.json"
            cache_file.write_text(
                json.dumps(v1_data, indent=2), encoding="utf-8"
            )
            router.state.models_cache_file = cache_file
            router.state._load_models_cache()

            # Только text-модель прошла
            assert "routerai::text-model" in router.state.available_models
            assert "routerai::image-text-model" not in router.state.available_models
            assert "routerai::text-audio-model" not in router.state.available_models
        finally:
            router.state.models_cache_file = old_file


# ============================================================
# Фильтрация моделей (RouterAI / OpenRouter)
# ============================================================


class TestModelFiltering:
    """Фильтрация моделей из API провайдера."""

    def test_text_only_passes(self):
        """output_modalities == ["text"] → оставлена."""
        result = router.state._parse_model_entry(
            {
                "id": "test/text-model",
                "name": "Text Model",
                "architecture": {"output_modalities": ["text"]},
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
                "pricing_units": {"prompt": "token", "completion": "token"},
            },
            "routerai", "auto", False,
        )
        assert result is not None
        assert result["id"] == "test/text-model"

    def test_image_text_filtered(self):
        """output_modalities == ["image", "text"] → отброшена."""
        result = router.state._parse_model_entry(
            {
                "id": "test/img-text",
                "name": "Img+Text",
                "architecture": {"output_modalities": ["image", "text"]},
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
                "pricing_units": {"prompt": "token", "completion": "token"},
            },
            "routerai", "auto", False,
        )
        assert result is None

    def test_text_audio_filtered(self):
        """output_modalities == ["text", "audio"] → отброшена."""
        result = router.state._parse_model_entry(
            {
                "id": "test/text-audio",
                "name": "Text+Audio",
                "architecture": {"output_modalities": ["text", "audio"]},
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
                "pricing_units": {"prompt": "token", "completion": "token"},
            },
            "routerai", "auto", False,
        )
        assert result is None

    def test_pricing_units_not_token_filtered(self):
        """pricing_units.prompt == "image" → отброшена."""
        result = router.state._parse_model_entry(
            {
                "id": "test/image-pricing",
                "name": "Image Pricing",
                "architecture": {"output_modalities": ["text"]},
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
                "pricing_units": {"prompt": "image", "completion": "token"},
            },
            "routerai", "auto", False,
        )
        assert result is None

    def test_openrouter_style_passes(self):
        """OpenRouter: без pricing_units, цены-строки → оставлена."""
        result = router.state._parse_model_entry(
            {
                "id": "openrouter/test-model",
                "name": "OR Model",
                "architecture": {"output_modalities": ["text"]},
                "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            },
            "openrouter", "auto", False,
        )
        assert result is not None
        assert result["id"] == "openrouter/test-model"

    def test_pricing_request_non_zero_filtered(self):
        """pricing.request != 0 → отброшена."""
        result = router.state._parse_model_entry(
            {
                "id": "test/request-cost",
                "name": "Request Cost",
                "architecture": {"output_modalities": ["text"]},
                "pricing": {"prompt": "0.0000025", "completion": "0.00001", "request": 0.01},
            },
            "openrouter", "auto", False,
        )
        assert result is None


# ============================================================
# Ollama-формат
# ============================================================


class TestOllamaFormat:
    """Парсинг Ollama /api/tags."""

    def test_ollama_basic(self):
        """name → id, details.context_length → context_length."""
        result = router.state._parse_ollama_entry({
            "name": "llama3.2:latest",
            "model": "llama3.2:latest",
            "details": {"context_length": 8192},
            "capabilities": ["completion"],
        }, "ollama")
        assert result is not None
        assert result["id"] == "llama3.2:latest"
        assert result["context_length"] == 8192
        assert result["currency"] == "NONE"
        assert result["input_price_1m"] == 0.0
        assert result["output_price_1m"] == 0.0

    def test_ollama_embedding_filtered(self):
        """capabilities: ["embedding"] без "completion" → отброшена."""
        result = router.state._parse_ollama_entry({
            "name": "qwen3-embedding:4b",
            "model": "qwen3-embedding:4b",
            "capabilities": ["embedding"],
        }, "ollama")
        assert result is None

    def test_ollama_vision_supports_images(self):
        """capabilities: ["completion", "vision"] → supports_images: true."""
        result = router.state._parse_ollama_entry({
            "name": "llama3.2-vision:latest",
            "model": "llama3.2-vision:latest",
            "capabilities": ["completion", "vision"],
        }, "ollama")
        assert result is not None
        assert result["supports_images"] is True

    def test_ollama_no_completion_filtered(self):
        """capabilities без "completion" → отброшена."""
        result = router.state._parse_ollama_entry({
            "name": "some-model",
            "model": "some-model",
            "capabilities": ["vision"],
        }, "ollama")
        assert result is None


# ============================================================
# parse_pricing
# ============================================================


class TestParsePricing:
    """parse_pricing: все режимы."""

    def test_free(self):
        """free → (0, 0, 'NONE')."""
        inp, out, cur = router.state.parse_pricing(None, None, "free")
        assert inp == 0.0
        assert out == 0.0
        assert cur == "NONE"

    def test_free_no_pricing(self):
        """pricing=None при free → (0, 0, 'NONE')."""
        inp, out, cur = router.state.parse_pricing(None, None, "free")
        assert inp == 0.0
        assert out == 0.0
        assert cur == "NONE"

    def test_per_token_rub(self):
        """per_token_rub: число → RUB."""
        inp, out, cur = router.state.parse_pricing(
            {"prompt": 0.0001319528574, "completion": 0.0005278094296},
            None, "per_token_rub",
        )
        # 0.0001319528574 * 1e6 = 131.9529 (округление до 4 знаков)
        assert inp == 131.9529
        assert out == 527.8094
        assert cur == "RUB"

    def test_per_token_usd(self):
        """per_token_usd: строка → USD."""
        inp, out, cur = router.state.parse_pricing(
            {"prompt": "0.0000025", "completion": "0.00001"},
            None, "per_token_usd",
        )
        assert inp == 2.5
        assert out == 10.0
        assert cur == "USD"

    def test_auto_string_usd(self):
        """auto со строкой → USD."""
        inp, out, cur = router.state.parse_pricing(
            {"prompt": "0.0000025", "completion": "0.00001"},
            None, "auto",
        )
        assert inp == 2.5
        assert out == 10.0
        assert cur == "USD"

    def test_auto_number_rub(self):
        """auto с числом → RUB."""
        inp, out, cur = router.state.parse_pricing(
            {"prompt": 0.0001319528574, "completion": 0.0005278094296},
            None, "auto",
        )
        assert inp == 131.9529
        assert out == 527.8094
        assert cur == "RUB"

    def test_auto_no_pricing_none(self):
        """auto без pricing → NONE."""
        inp, out, cur = router.state.parse_pricing(None, None, "auto")
        assert inp == 0.0
        assert out == 0.0
        assert cur == "NONE"