from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import ssl
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

import httpx
import uvicorn
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

# ============================================================
# 🌍 ЗАГРУЗКА .env (API-ключи)
# ============================================================
load_dotenv()

# ============================================================
# 📦 ЗАГРУЗКА КОНФИГУРАЦИИ
# ============================================================
CONFIG_FILE = Path(__file__).parent / "config.yaml"
ADMIN_HTML_FILE = Path(__file__).parent / "admin.html"

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

# ============================================================
# 🔧 ИНИЦИАЛИЗАЦИЯ И НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SmartRouter")

# ============================================================
# 📝 КОЛЬЦЕВОЙ БУФЕР ЛОГОВ (для админки)
# ============================================================
MAX_LOG_ENTRIES = 500
log_buffer = deque(maxlen=MAX_LOG_ENTRIES)


class RingBufferHandler(logging.Handler):
    """Перехватывает логи в кольцевой буфер in-memory."""

    def emit(self, record: logging.LogRecord):
        log_entry = {
            "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        log_buffer.append(log_entry)


# Подключаем handler к корневому логгеру
ring_handler = RingBufferHandler(level=logging.INFO)
logging.getLogger().addHandler(ring_handler)

# ============================================================
# 🚫 КОНСТАНТЫ ИЗ КОНФИГА
# ============================================================
BLACKLIST = set(cfg.get("api_blacklist", []))

# Строим PRICES из config.yaml
PRICES = {}
for model_name, model_cfg in cfg.get("models", {}).items():
    PRICES[model_name] = {
        "input": model_cfg["input_price"],
        "output": model_cfg["output_price"],
        "provider": model_cfg.get("provider", "Unknown"),
        "emoji": model_cfg.get("emoji", "\U0001f916"),
        "role": model_cfg.get("role", "Worker"),
        "currency": model_cfg.get("currency", "RUB"),
    }

# ============================================================
# 🎭 РОЛИ (Coordinator / Worker / Worker Img)
# ============================================================
# Загружаем роли из config.yaml
ROLES_CFG = cfg.get("roles", {})

# Обратный маппинг: agent_name → role_name
# Строится из config: для каждой роли берём список её агентов
AGENT_TO_ROLE: Dict[str, str] = {}
for role_name, role_cfg in ROLES_CFG.items():
    for agent in role_cfg.get("agents", []):
        AGENT_TO_ROLE[agent] = role_name


def get_role_for_agent(agent: str) -> str | None:
    """Возвращает имя роли для агента или None."""
    return AGENT_TO_ROLE.get(agent)


def get_role_config(role_name: str) -> dict:
    """Возвращает конфиг роли или пустой dict если роли нет."""
    return ROLES_CFG.get(role_name, {})


def get_role_default_model(role_name: str) -> str | None:
    """
    Возвращает default_model роли.
    Приоритет: routing.json → config.yaml.
    """
    # 1. Сначала смотрим в runtime-конфиге (routing.json)
    role_models = state.config.get("role_models", {})
    if role_name in role_models and role_models[role_name] != "auto":
        return role_models[role_name]
    # 2. Fallback в config.yaml
    role = get_role_config(role_name)
    return role.get("default_model")


def get_role_fallback_model(role_name: str) -> str | None:
    """
    Возвращает fallback-модель для роли.
    Приоритет:
    1. role_fallbacks из runtime-конфига (routing.json)
    2. fallback_model из config.yaml
    3. Автоматическое правило:
      coordinator    -> worker_default.default_model
      worker_default -> coordinator.default_model
      worker_img     -> worker_default.default_model
    """
    # 1. role_fallbacks из routing.json
    role_fallbacks = state.config.get("role_fallbacks", {})
    if role_name in role_fallbacks:
        return role_fallbacks[role_name]

    # 2. fallback_model из config.yaml
    role = get_role_config(role_name)
    explicit = role.get("fallback_model")
    if explicit:
        return explicit

    # 3. Автоматическое правило
    auto_map = {
        "coordinator": "worker_default",
        "worker_default": "coordinator",
        "worker_img": "worker_default",
    }
    fallback_role = auto_map.get(role_name)
    if fallback_role:
        return get_role_default_model(fallback_role)
    return None


def _split_config_model_key(key: str) -> tuple[str | None, str]:
    """
    Разделяет ключ из config.yaml models: на (provider, model_id).

    - "deepseek/deepseek-v4-flash" → (None, "deepseek/deepseek-v4-flash")
    - "routerai::deepseek/deepseek-v4-flash" → ("routerai", "deepseek/deepseek-v4-flash")
    - "a::b::c" → ("a", "b::c")
    """
    if "::" in key:
        provider, model_id = key.split("::", 1)
        return provider, model_id
    return None, key


class RouterState:
    def __init__(self):
        self.config_file = Path(__file__).parent / "routing.json"
        self.models_cache_file = Path(__file__).parent / "models_cache.json"
        # ЕДИНСТВЕННЫЙ источник runtime-конфига — routing.json
        self.config = {}
        self.stats = {
            "requests": 0,
            "total_input": 0,
            "total_output": 0,
            "total_cost": 0.0,
            "currency": cfg.get("currency", {}).get("base", "RUB"),
            "usd_rate": float(cfg.get("currency", {}).get("usd_rate", 90.0)),
            "by_currency": {},
            "usd_equivalent": 0.0,
            "by_model": {},
            "routed_count": 0,
            "not_routed_count": 0,
            "fallback_count": 0,
            "started_at": time.time(),
        }
        self.quota = {"last_check": 0, "is_ok": True}
        self.config_lock = asyncio.Lock()  # Защита от конкурентной записи файла
        self.models_lock = asyncio.Lock()  # Защита models_cache.json
        # Провайдеры в runtime (из config.yaml)
        self.providers = cfg.get("providers", {})
        self.default_provider = self._determine_active_provider()
        # Кеш моделей из провайдера (составные ключи "provider::model_id")
        self.available_models: Dict[str, dict] = {}  # "provider::model_id" → info
        self.models_by_provider: Dict[str, list[str]] = {}  # provider → [model_id, ...]
        self.provider_last_sync: Dict[str, float] = {}  # provider → timestamp
        self._models_last_sync: float | None = None

        self._load_config()
        self._load_models_cache()

    def _determine_active_provider(self) -> str:
        """Определяет дефолтный провайдер из конфига."""
        for p_name, p_cfg in self.providers.items():
            if p_cfg.get("default", False):
                return p_name
        # Если ничего не default — первый
        first = next(iter(self.providers.keys()), "routerai")
        return first

    def get_provider_url(self, provider_name: str) -> str:
        """Возвращает base_url провайдера."""
        provider = self.providers.get(provider_name, {})
        return provider.get("base_url", "")

    def get_provider_key_env(self, provider_name: str) -> str:
        """Возвращает имя env-переменной с API-ключом провайдера."""
        provider = self.providers.get(provider_name, {})
        return provider.get("api_key_env", "")

    def get_active_provider_url(self) -> str:
        """Возвращает base_url активного провайдера (BC-обёртка)."""
        return self.get_provider_url(self.default_provider)

    def get_active_provider_key_env(self) -> str:
        """Возвращает имя env-переменной с API-ключом (BC-обёртка)."""
        return self.get_provider_key_env(self.default_provider)

    def _load_config(self):
        """
        Загружает runtime-конфиг из routing.json.
        Если файла нет — создаёт его с дефолтами из config.yaml.
        Автоматически мигрирует: добавляет role_tuning если отсутствует.
        """
        migrated = False
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.config = loaded
                logger.info(f"✅ Загружена конфигурация из {self.config_file}")
            except Exception as e:
                logger.error(f"Ошибка загрузки {self.config_file}: {e}")
                # НЕ перезаписываем файл: сначала сохраняем битую копию,
                # иначе пользователь потеряет настройки ролей безвозвратно.
                self._backup_broken_file(self.config_file)
                self._init_default_config()
                migrated = False
        else:
            self._init_default_config()
            migrated = True

        # Миграция: добавляем role_tuning если отсутствует
        if "role_tuning" not in self.config:
            default_tuning = {
                "coordinator": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "system_prompt_prefix": "",
                },
                "worker_default": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "system_prompt_prefix": "",
                },
                "worker_img": {
                    "temperature": 0.5,
                    "top_p": 0.9,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "system_prompt_prefix": "",
                },
            }
            self.config["role_tuning"] = default_tuning
            logger.info("🔄 Миграция: добавлен role_tuning с дефолтами")
            migrated = True

        if migrated:
            self._sync_write_config(self.config_file, self.config)
            logger.info(f"📝 Сохранён {self.config_file}")

    def _init_default_config(self):
        """Заполняет self.config дефолтами из config.yaml."""
        coord_model = (
            get_role_default_model("coordinator") or "deepseek/deepseek-v4-pro"
        )
        worker_model = (
            get_role_default_model("worker_default") or "deepseek/deepseek-v4-flash"
        )
        img_model = get_role_default_model("worker_img") or "qwen/qwen3-coder-next"
        self.config = {
            "role_models": {
                "coordinator": coord_model,
                "worker_default": worker_model,
                "worker_img": img_model,
            },
            "agent_to_worker_mapping": {
                "database": "auto",
                "tests": "auto",
                "bot": "auto",
                "api": "auto",
                "services": "auto",
                "devops": "auto",
                "frontend": "auto",
                "mobile": "auto",
                "design": "auto",
            },
            "default_worker": worker_model,
            "enable_auto_routing": True,
            "role_tuning": {
                "coordinator": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "system_prompt_prefix": "",
                },
                "worker_default": {
                    "temperature": 0.3,
                    "top_p": 0.9,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "system_prompt_prefix": "",
                },
                "worker_img": {
                    "temperature": 0.5,
                    "top_p": 0.9,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                    "system_prompt_prefix": "",
                },
            },
        }

    @staticmethod
    def _backup_broken_file(path: Path):
        """Переименовывает битый файл в *.broken — чтобы не потерять данные."""
        try:
            backup = path.with_suffix(path.suffix + ".broken")
            if backup.exists():
                backup.unlink()
            path.replace(backup)
            logger.warning(f"⚠️ Битый конфиг сохранён как {backup.name}")
        except Exception as e:
            logger.error(f"Не удалось сохранить битый конфиг: {e}")

    @staticmethod
    def _atomic_write(path: Path, content: str):
        """
        Атомарная запись файла.

        Пишем во временный файл рядом с целью и переименовываем через os.replace()
        — на Windows/Linux это атомарно. Без этого прерванная запись (Ctrl+C,
        падение, два процесса сразу) оставляла config.yaml/routing.json битыми,
        и роутер стартовал с дефолтами, молча затирая настройки ролей.
        """
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

    def _load_models_cache(self):
        """Загружает кеш моделей из models_cache.json (v1 или v2)."""
        if not self.models_cache_file.exists():
            self.available_models = {}
            self.models_by_provider = {}
            self.provider_last_sync = {}
            return

        try:
            with open(self.models_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки models_cache.json: {e}")
            self._backup_broken_file(self.models_cache_file)
            self.available_models = {}
            self.models_by_provider = {}
            self.provider_last_sync = {}
            return

        # v2 — новый формат
        if data.get("version") == 2:
            self.available_models = {}
            self.models_by_provider = {}
            self.provider_last_sync = {}
            providers = data.get("providers", {})
            for p_name, p_data in providers.items():
                p_models = p_data.get("models", {})
                model_ids = []
                for mid, minfo in p_models.items():
                    key = f"{p_name}::{mid}"
                    self.available_models[key] = minfo
                    model_ids.append(mid)
                self.models_by_provider[p_name] = model_ids
                self.provider_last_sync[p_name] = p_data.get("last_sync")

            syncs = [v for v in self.provider_last_sync.values() if v is not None]
            self._models_last_sync = max(syncs) if syncs else None
            logger.info(
                f"\U0001f4e6 Загружено {len(self.available_models)} моделей из кеша v2"
            )
            return

        # v1 — миграция
        provider_name = data.get("provider", "routerai")
        models_list = data.get("models", [])
        last_sync = data.get("last_sync")

        self.available_models = {}
        self.models_by_provider = {provider_name: []}
        self.provider_last_sync = {}
        if last_sync:
            self.provider_last_sync[provider_name] = last_sync
        self._models_last_sync = last_sync

        for m in models_list:
            mid = m["id"]
            # Фильтр: только text-выходящие
            out_mod = m.get("output_modalities", ["text"])
            if out_mod != ["text"]:
                continue
            # Проставляем provider и currency
            m["provider"] = provider_name
            m["currency"] = "RUB"  # v1 — только RouterAI
            m["price_source"] = "api"
            key = f"{provider_name}::{mid}"
            self.available_models[key] = m
            self.models_by_provider[provider_name].append(mid)

        logger.warning(
            f"\U0001f4e6 Кеш мигрирован с v1 ({len(self.available_models)} моделей), "
            f"выполните Sync для полной фильтрации"
        )

    def get_model_info(self, model_id: str, provider: str | None = None) -> dict | None:
        """
        Возвращает информацию о модели из кеша.

        Порядок поиска:
        1. Точное совпадение "provider::model_id" (если provider задан)
        2. BC-fallback: плоский ключ model_id (v1-совместимость)
        3. Поиск по всем провайдерам
        """
        # 1. Точный составной ключ
        if provider is not None:
            return self.available_models.get(f"{provider}::{model_id}")

        # 2. BC-fallback: плоский ключ (старые тесты / фикстуры)
        if model_id in self.available_models:
            return self.available_models[model_id]

        # 3. Поиск по всем провайдерам
        candidates = []
        for prov, ids in self.models_by_provider.items():
            if model_id in ids:
                candidates.append(prov)
        if candidates:
            if self.default_provider in candidates:
                return self.available_models.get(
                    f"{self.default_provider}::{model_id}"
                )
            candidates.sort()
            return self.available_models.get(f"{candidates[0]}::{model_id}")

        return None

    def get_all_available_models(self) -> list:
        """Возвращает список всех моделей из кеша."""
        return sorted(
            self.available_models.values(),
            key=lambda m: m.get("name", m["id"]),
        )

    async def sync_models_from_provider(self, provider_name: str | None = None) -> dict:
        """
        Синхронизирует список моделей из API провайдера(ов).

        provider_name=None → синк всех провайдеров (каждый в своём try/except).
        Возвращает:
            {"status": "ok"|"error",
             "results": {provider: {"status": "ok"|"error", "synced": N, "last_sync": ts, "error": str?}},
             "synced": N,      # сумма по успешным
             "last_sync": ts}  # максимум по успешным
        """
        if provider_name is None:
            return await self._sync_all_providers()

        provider = self.providers.get(provider_name, {})
        endpoint = provider.get("models_endpoint", "")
        if not endpoint:
            return {
                "status": "error",
                "results": {
                    provider_name: {
                        "status": "error", "synced": 0, "error": "models_endpoint не настроен"
                    }
                },
                "synced": 0,
                "last_sync": None,
            }

        # Проверка API-ключа
        if provider.get("requires_api_key", True):
            key_env = provider.get("api_key_env", "")
            api_key = os.getenv(key_env, "")
            if not api_key:
                return {
                    "status": "error",
                    "results": {
                        provider_name: {
                            "status": "error", "synced": 0, "error": f"Missing API key: {key_env}"
                        }
                    },
                    "synced": 0,
                    "last_sync": None,
                }

        async with self.models_lock:
            try:
                client = get_provider_client(provider_name)
                # Добавляем Authorization для провайдеров с API-ключом
                req_headers = {}
                key_env = provider.get("api_key_env", "")
                api_key_for_req = os.getenv(key_env, "")
                if api_key_for_req:
                    req_headers["Authorization"] = f"Bearer {api_key_for_req}"
                resp = await client.get(
                    endpoint, timeout=30.0, headers=req_headers or None
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Ошибка синхронизации моделей с '{provider_name}': {e}")
                return {
                    "status": "error",
                    "results": {
                        provider_name: {
                            "status": "error", "synced": 0, "error": str(e)
                        }
                    },
                    "synced": 0,
                    "last_sync": None,
                }

            pricing_mode = provider.get("pricing_mode", "auto")

            # Определяем формат ответа
            if "models" in data and "data" not in data:
                raw_models = data.get("models", [])
                is_ollama = True
            else:
                raw_models = data.get("data", [])
                is_ollama = False

            parsed = {}
            for m in raw_models:
                try:
                    info = self._parse_model_entry(
                        m, provider_name, pricing_mode, is_ollama
                    )
                    if info:
                        mid = info["id"]
                        key = f"{provider_name}::{mid}"
                        parsed[key] = info
                except Exception as e:
                    logger.warning(
                        f"Ошибка парсинга модели {m.get('id', m.get('name', '?'))}: {e}"
                    )
                    continue

            now = time.time()

            # Удаляем старые модели этого провайдера
            for key in list(self.available_models.keys()):
                if key.startswith(f"{provider_name}::"):
                    del self.available_models[key]

            self.available_models.update(parsed)
            self.models_by_provider[provider_name] = [
                v["id"] for v in parsed.values()
            ]
            self.provider_last_sync[provider_name] = now

            # Обновляем общий last_sync
            syncs = [
                v for v in self.provider_last_sync.values() if v is not None
            ]
            self._models_last_sync = max(syncs) if syncs else now

            # Пишем кеш v2
            cache_data = self._build_v2_cache()
            await asyncio.to_thread(
                self._atomic_write,
                self.models_cache_file,
                json.dumps(cache_data, indent=2, ensure_ascii=False),
            )

            logger.info(
                f"\U0001f504 Синхронизировано {len(parsed)} моделей из '{provider_name}'"
            )
            return {
                "status": "ok",
                "results": {
                    provider_name: {
                        "status": "ok", "synced": len(parsed), "last_sync": now
                    }
                },
                "synced": len(parsed),
                "last_sync": now,
            }

    async def _sync_all_providers(self) -> dict:
        """Синк всех провайдеров, каждый в своём try/except."""
        results = {}
        total_synced = 0
        max_sync = 0
        for p_name in self.providers:
            try:
                result = await self.sync_models_from_provider(p_name)
                results[p_name] = result.get("results", {}).get(p_name, result)
                if result.get("status") != "error":
                    total_synced += result.get("synced", 0)
                    ls = result.get("last_sync", 0)
                    if ls and ls > max_sync:
                        max_sync = ls
            except Exception as e:
                logger.error(f"Ошибка синка провайдера '{p_name}': {e}")
                results[p_name] = {
                    "status": "error", "synced": 0, "error": str(e)
                }

        return {
            "status": "ok",
            "results": results,
            "synced": total_synced,
            "last_sync": max_sync or time.time(),
        }

    @staticmethod
    def parse_pricing(
        pricing: dict | None, pricing_units: dict | None, mode: str
    ) -> tuple[float, float, str]:
        """
        Pricing-адаптер.

        mode: auto | per_token_rub | per_token_usd | free
        Возвращает (input_per_1m, output_per_1m, currency).
        """
        if mode == "free" or not pricing:
            return 0.0, 0.0, "NONE"

        prompt_val = pricing.get("prompt", 0)
        completion_val = pricing.get("completion", 0)

        if mode == "per_token_usd":
            inp = round(float(str(prompt_val)) * 1_000_000, 4)
            out = round(float(str(completion_val)) * 1_000_000, 4)
            return inp, out, "USD"

        if mode == "per_token_rub":
            inp = round(float(prompt_val) * 1_000_000, 4)
            out = round(float(completion_val) * 1_000_000, 4)
            return inp, out, "RUB"

        # auto — определяем по типу prompt
        if prompt_val is None:
            return 0.0, 0.0, "NONE"

        if isinstance(prompt_val, str):
            # OpenRouter: строки в USD
            inp = round(float(prompt_val) * 1_000_000, 4)
            out = round(float(str(completion_val)) * 1_000_000, 4)
            return inp, out, "USD"
        else:
            # RouterAI: числа в RUB
            inp = round(float(prompt_val) * 1_000_000, 4)
            out = round(float(completion_val) * 1_000_000, 4)
            return inp, out, "RUB"

    def _parse_model_entry(
        self, m: dict, provider_name: str, pricing_mode: str, is_ollama: bool
    ) -> dict | None:
        """Парсит одну запись модели из ответа API провайдера."""
        if is_ollama:
            return self._parse_ollama_entry(m, provider_name)

        # OpenAI-совместимый формат (RouterAI, OpenRouter)
        out_mod = m.get("architecture", {}).get("output_modalities", ["text"])
        if out_mod != ["text"]:
            return None

        pricing = m.get("pricing") or {}
        pricing_units = m.get("pricing_units")

        # Фильтр тарификации за токены
        if pricing_mode != "free":
            if pricing_units is not None:
                if (
                    pricing_units.get("prompt") != "token"
                    or pricing_units.get("completion") != "token"
                ):
                    return None
            else:
                # OpenRouter: pricing без pricing_units
                try:
                    float(str(pricing.get("prompt", "")))
                    float(str(pricing.get("completion", "")))
                except (ValueError, TypeError):
                    return None
                if pricing.get("request") is not None and pricing["request"] != 0:
                    return None

        inp_per_1m, out_per_1m, currency = self.parse_pricing(
            pricing, pricing_units, pricing_mode
        )

        input_mods = m.get("architecture", {}).get("input_modalities", ["text"])

        return {
            "id": m["id"],
            "provider": provider_name,
            "name": m.get("name", m["id"]),
            "description": m.get("description", ""),
            "context_length": m.get("context_length", 0),
            "input_price_1m": inp_per_1m,
            "output_price_1m": out_per_1m,
            "currency": currency,
            "price_source": "api",
            "supports_images": "image" in input_mods,
            "input_modalities": input_mods,
            "output_modalities": out_mod,
            "supported_parameters": m.get("supported_parameters", []),
            "pricing_units": pricing_units,
        }

    def _parse_ollama_entry(self, m: dict, provider_name: str) -> dict | None:
        """Парсит запись модели из Ollama /api/tags."""
        caps = m.get("capabilities", [])
        # Отбрасываем эмбеддинги без completion
        if "embedding" in caps and "completion" not in caps:
            return None
        if "completion" not in caps:
            return None

        return {
            "id": m.get("name", m.get("model", "")),
            "provider": provider_name,
            "name": m.get("name", m.get("model", "")),
            "description": "",
            "context_length": m.get("details", {}).get("context_length", 0),
            "input_price_1m": 0.0,
            "output_price_1m": 0.0,
            "currency": "NONE",
            "price_source": "api",
            "supports_images": "vision" in caps,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "supported_parameters": [],
            "pricing_units": None,
        }

    def _build_v2_cache(self) -> dict:
        """Строит структуру кеша v2 для записи."""
        providers = {}
        for p_name, model_ids in self.models_by_provider.items():
            models = {}
            for mid in model_ids:
                key = f"{p_name}::{mid}"
                if key in self.available_models:
                    models[mid] = self.available_models[key]
            providers[p_name] = {
                "last_sync": self.provider_last_sync.get(p_name),
                "models": models,
            }
        return {
            "version": 2,
            "providers": providers,
        }

    @staticmethod
    def _merge_config(old: dict, new: dict) -> dict:
        """
        Рекурсивный мерж new в old: словари на один уровень вглубь мержатся,
        остальные значения заменяются (включая None).
        """
        result = dict(old)
        for key, new_val in new.items():
            if key in result and isinstance(result[key], dict) and isinstance(new_val, dict):
                result[key] = {**result[key], **new_val}
            else:
                result[key] = new_val
        return result

    async def save_config(self, new_config: dict):
        async with self.config_lock:
            self.config = self._merge_config(self.config, new_config)
            await asyncio.to_thread(
                self._sync_write_config, self.config_file, self.config
            )

    async def save_config_yaml(self):
        """Сохраняет config.yaml с обновлёнными провайдерами."""
        cfg_copy = dict(cfg)  # загруженный при старте
        cfg_copy["providers"] = self.providers
        async with self.config_lock:
            await asyncio.to_thread(
                lambda: self._atomic_write(
                    Path(CONFIG_FILE),
                    yaml.dump(cfg_copy, default_flow_style=False, allow_unicode=True),
                )
            )
        logger.info(f"✅ config.yaml обновлён с провайдерами")

    @staticmethod
    def _sync_write_config(path: Path, data: dict):
        """Атомарная запись JSON-конфига (tmp + os.replace)."""
        RouterState._atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))


state = RouterState()

# ============================================================
# 🧠 ПРЕДКОМПИЛИРОВАННЫЕ РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ (ОПТИМИЗАЦИЯ)
# ============================================================
# Паттерн для явного тега агента в user-сообщении: [AGENT:name]
AGENT_TAG_PATTERN = re.compile(r"\[AGENT:(\w+)\]", re.IGNORECASE)


# ============================================================
# 🛠 УТИЛИТЫ
# ============================================================
def sanitize_ascii(value: str) -> str:
    return re.sub(r"[^\x00-\x7F]+", "", str(value))


def _to_base_factor(currency: str) -> float:
    """
    Сколько единиц базовой валюты стоит 1 единица `currency`.

    - Базовая валюта (RUB) → 1.0
    - USD → usd_rate (сколько RUB за 1 USD)
    - Опциональные валюты из rates: сколько RUB за 1 единицу
    - NONE → 1.0 (бесплатные модели, цена 0)
    """
    if currency == "NONE":
        return 1.0
    currency_cfg = cfg.get("currency", {})
    base = currency_cfg.get("base", "RUB")
    if currency == base:
        return 1.0
    if currency == "USD":
        return float(currency_cfg.get("usd_rate", 90.0))
    rates = currency_cfg.get("rates", {}) or {}
    if currency in rates:
        return float(rates[currency])
    logger.warning(
        f"\u26a0\ufe0f Неизвестная валюта '{currency}', коэффициент 1.0"
    )
    return 1.0


def log_usage(model: str, input_tokens: int, output_tokens: int):
    """Обновляет статистику и логирует (Phase 2 — per-provider)."""
    state.stats["requests"] += 1
    state.stats["total_input"] += input_tokens
    state.stats["total_output"] += output_tokens

    # Парсим спецификацию: разделяем по первому ::
    provider = None
    bare_id = model
    if "::" in model:
        parts = model.split("::", 1)
        provider = parts[0]
        bare_id = parts[1]

    # Поиск цены:
    # 1. PRICES по составному ключу (ручной override с привязкой к провайдеру)
    # 2. PRICES по голому ID (ручной override из config.yaml)
    price_info = PRICES.get(model) or PRICES.get(bare_id)
    price_source = "manual"
    currency = "RUB"
    inp_price = 0.0
    out_price = 0.0

    if price_info:
        inp_price = price_info["input"]
        out_price = price_info["output"]
        currency = price_info.get("currency", "RUB")
    else:
        # 3. Каталог именно этого провайдера (главный фикс)
        cm = None
        if provider:
            cm = state.get_model_info(bare_id, provider)
        # 4. Bare-фолбэк каталога (без провайдера)
        if not cm:
            cm = state.get_model_info(bare_id)
        if not cm:
            cm = state.get_model_info(model)
        if cm:
            inp_price = cm.get("input_price_1m", 0)
            out_price = cm.get("output_price_1m", 0)
            currency = cm.get("currency", "RUB")
            price_source = "api"
        else:
            price_source = "unknown"
            logger.warning(
                f"\u26a0\ufe0f Цена для модели '{model}' не найдена, используется 0"
            )

    cost = (
        input_tokens * inp_price + output_tokens * out_price
    ) / 1_000_000

    # Конвертация в базовую валюту через _to_base_factor
    factor = _to_base_factor(currency)
    state.stats["total_cost"] += cost * factor  # в базовой валюте

    # По-валютный учёт (в native-валюте)
    if currency not in state.stats["by_currency"]:
        state.stats["by_currency"][currency] = 0.0
    state.stats["by_currency"][currency] += cost

    # USD-эквивалент (из native-стоимости)
    usd_rate = state.stats.get("usd_rate", 90.0)
    if currency == "USD":
        state.stats["usd_equivalent"] += cost
    elif currency == "NONE":
        pass  # бесплатные модели не влияют на usd_equivalent
    else:
        state.stats["usd_equivalent"] += cost / usd_rate

    # by_model — ключ = составная спецификация
    if model not in state.stats["by_model"]:
        state.stats["by_model"][model] = {
            "count": 0,
            "input": 0,
            "output": 0,
            "cost": 0.0,
        }

    model_stat = state.stats["by_model"][model]
    model_stat["count"] += 1
    model_stat["input"] += input_tokens
    model_stat["output"] += output_tokens
    model_stat["cost"] += cost

    logger.info(
        f"\U0001f4b0 {model}: In {input_tokens} | Out {output_tokens} | Cost {cost:.6f} {currency}"
    )


# ============================================================
# 🧠 УМНАЯ МАРШРУТИЗАЦИЯ
# ============================================================


def resolve_model_spec(spec: str) -> tuple[str, str]:
    """
    Разбирает спецификацию модели и возвращает (provider, model_id).

    spec может быть:
    - "provider::model_id" — составной ключ
    - "model_id" — голый ID, ищется в каталоге

    Если провайдер не указан или не найден — используется default_provider.
    """
    if "::" in spec:
        parts = spec.split("::", 1)
        prov = parts[0]
        model_id = parts[1]
        if prov not in state.providers:
            logger.warning(
                f"\u26a0\ufe0f Неизвестный провайдер '{prov}' в спецификации "
                f"'{spec}', используется default '{state.default_provider}'"
            )
            return state.default_provider, model_id
        return prov, model_id

    # Голый model_id — поиск в каталоге
    if not state.models_by_provider:
        # Каталог ещё не загружен
        return state.default_provider, spec

    candidates = []
    for prov, ids in state.models_by_provider.items():
        if spec in ids:
            candidates.append(prov)

    if len(candidates) == 1:
        return candidates[0], spec
    elif len(candidates) > 1:
        logger.warning(
            f"\u26a0\ufe0f Модель '{spec}' у нескольких провайдеров: {candidates}, "
            f"используется default '{state.default_provider}'"
        )
    else:
        logger.warning(
            f"\u26a0\ufe0f Модель '{spec}' не найдена в каталоге, "
            f"используется default '{state.default_provider}'"
        )
    return state.default_provider, spec


def _normalize_to_composite(model_id: str) -> str:
    """Нормализует model_id в составную спецификацию provider::model_id."""
    if "::" in model_id:
        return model_id
    provider, _ = resolve_model_spec(model_id)
    return f"{provider}::{model_id}"


def smart_route_model(
    requested_model: str, body: Dict[str, Any]
) -> Tuple[str, str, str]:
    """
    Умная маршрутизация запроса.
    Возвращает (spec, role, reason):
      - spec: составная спецификация "provider::model_id"
      - role: имя роли (coordinator / worker_default / worker_img) или ""
      - reason: человекочитаемое объяснение
    """
    # 1. Явная модель — если уже содержит flash или qwen, резолвим в составной вид
    if any(m in requested_model.lower() for m in ["flash", "qwen"]):
        spec = _normalize_to_composite(requested_model)
        return spec, "", "Без изменений (уже дешевая)"

    messages = body.get("messages", [])
    if not messages:
        coord_model = (
            state.config.get("role_models", {}).get("coordinator")
            or get_role_default_model("coordinator")
            or requested_model
        )
        spec = _normalize_to_composite(coord_model)
        return spec, "coordinator", "Нет сообщений -> coordinator"

    # Ищем системный промпт и последнее сообщение пользователя
    system_prompt = ""
    last_user_msg = ""

    for msg in reversed(messages):
        role = msg.get("role")
        content = msg.get("content", "")
        # content может быть массивом (multimodal) — извлекаем текст
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            content = " ".join(text_parts)
        if isinstance(content, str):
            if role == "user" and not last_user_msg:
                last_user_msg = content
            elif role == "system" and not system_prompt:
                system_prompt = content

    mechanism = ""
    last_identified_agent = ""

    def _resolve_or_fallback(agent: str, mech: str) -> tuple | None:
        nonlocal last_identified_agent
        last_identified_agent = agent
        mapping = state.config.get("agent_to_worker_mapping", {})
        model = mapping.get(agent)
        if model and model != "auto":
            role = get_role_for_agent(agent) or ""
            spec = _normalize_to_composite(model)
            return (spec, role, f"{mech}: {agent}")
        role = get_role_for_agent(agent)
        if role:
            model = state.config.get("role_models", {}).get(
                role
            ) or get_role_default_model(role)
            if model:
                spec = _normalize_to_composite(model)
                return (spec, role, f"{mech}: {agent} (auto -> {role} default)")
        return None

    # 1.5 Agent tag [AGENT:name] — НАИВЫСШИЙ ПРИОРИТЕТ
    if last_user_msg:
        tag_match = AGENT_TAG_PATTERN.search(last_user_msg)
        if tag_match:
            agent = tag_match.group(1).lower()
            result = _resolve_or_fallback(agent, f"Agent tag: {agent}")
            if result:
                return result

    if not last_user_msg:
        coord_model = (
            state.config.get("role_models", {}).get("coordinator")
            or get_role_default_model("coordinator")
            or requested_model
        )
        spec = _normalize_to_composite(coord_model)
        return spec, "coordinator", "Пустой user prompt -> coordinator"

    # 8. Default — ничего не распознано → Coordinator
    coord_model = (
        state.config.get("role_models", {}).get("coordinator")
        or get_role_default_model("coordinator")
        or state.config.get("default_worker", requested_model)
    )
    spec = _normalize_to_composite(coord_model)
    return spec, "coordinator", "Unknown \u2192 coordinator default"


# ============================================================
# 🚀 FASTAPI ПРИЛОЖЕНИЕ
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Современный способ задать startup/shutdown (заменяет @app.on_event)."""
    yield
    # shutdown: закрываем HTTP-клиенты
    await http_client.aclose()
    for _client in list(_provider_clients.values()):
        await _client.aclose()
    _provider_clients.clear()


app = FastAPI(title="SmartRouter", lifespan=lifespan)


# ============================================================
# 🔌 ТРАНСПОРТ: таймауты, ретраи, SSL-контексты провайдеров
# ============================================================
# Общий таймаут запроса + отдельный таймаут установления соединения (TLS).
# Раньше connect-таймаута не было — «висящий» TLS handshake держал слот 180с.
REQUEST_TIMEOUT = float(os.getenv("ROUTER_REQUEST_TIMEOUT", "180"))
CONNECT_TIMEOUT = float(os.getenv("ROUTER_CONNECT_TIMEOUT", "20"))

# Повторы при сетевых ошибках (TLS handshake / connect / read timeout).
# Безопасно: при этих ошибках запрос ещё НЕ дошёл до провайдера.
RETRY_ATTEMPTS = int(os.getenv("ROUTER_RETRY_ATTEMPTS", "3"))
RETRY_BACKOFF = float(os.getenv("ROUTER_RETRY_BACKOFF", "0.7"))

# Глобальный HTTP клиент для переиспользования соединений (Connection Pooling)
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT)
)

# Ошибки, при которых запрос можно безопасно повторить
RETRYABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)

# Кэш отдельных клиентов для провайдеров с кастомными SSL-настройками
_provider_clients: Dict[str, httpx.AsyncClient] = {}


def get_provider_client(provider_name: str) -> httpx.AsyncClient:
    """
    Возвращает HTTP-клиент для провайдера.

    Провайдеры без кастомных SSL-настроек используют общий http_client
    (connection pool + keep-alive). Если в конфиге провайдера задан ca_bundle
    (корпоративный CA / self-signed) или verify_ssl: false — создаём отдельный
    клиент со своим SSL-контекстом.
    """
    provider = state.providers.get(provider_name, {})
    ca_bundle = provider.get("ca_bundle")
    verify_ssl = provider.get("verify_ssl", True)
    if verify_ssl and not ca_bundle:
        return http_client

    cache_key = f"{provider_name}|{ca_bundle}|{verify_ssl}"
    client = _provider_clients.get(cache_key)
    if client is not None:
        return client

    try:
        if verify_ssl:
            ctx = (
                ssl.create_default_context(cafile=ca_bundle)
                if ca_bundle
                else ssl.create_default_context()
            )
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    except Exception as e:
        logger.error(f"Ошибка создания SSL-контекста для '{provider_name}': {e}")
        return http_client

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=CONNECT_TIMEOUT), verify=ctx
    )
    _provider_clients[cache_key] = client
    logger.info(
        f"🔐 Отдельный SSL-клиент для провайдера '{provider_name}' "
        f"(verify={verify_ssl}, ca_bundle={ca_bundle or 'system'})"
    )
    return client


def invalidate_provider_clients(provider_name: str):
    """Сбрасывает кэш SSL-клиентов провайдера (после смены настроек SSL)."""
    stale = [k for k in _provider_clients if k.startswith(f"{provider_name}|")]
    for key in stale:
        client = _provider_clients.pop(key)
        try:
            # close() — синхронный сброс пула; lifespan закроет клиент при остановке
            client.close()
        except Exception:
            pass
    if stale:
        logger.info(f"🔄 Сброшен кэш SSL-клиентов для провайдера '{provider_name}'")


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
    headers: dict,
    label: str = "",
    attempts: int = RETRY_ATTEMPTS,
):
    """
    POST с повторами при сетевых/SSL-ошибках.

    Повторяем только ошибки уровня соединения (TLS handshake, connect, read timeout) —
    в этих случаях запрос точно не был отправлен провайдеру, поэтому повтор безопасен.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await client.post(url, json=body, headers=headers)
        except RETRYABLE_ERRORS as e:
            last_exc = e
            if attempt >= attempts:
                raise
            delay = RETRY_BACKOFF * (2 ** (attempt - 1))
            logger.warning(
                f"🔄 Повтор {attempt}/{attempts} через {delay:.1f}s — "
                f"{type(e).__name__}: {e} → {url} {label}"
            )
            await asyncio.sleep(delay)
    raise last_exc  # pragma: no cover — недостижимо


@app.get("/", include_in_schema=False)
async def root():
    """Корень → редирект на админку (иначе 404 при заходе на порт)."""
    return RedirectResponse(url="/admin")


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model list (Phase 2 — составные ID)."""
    models_list = []
    seen = set()
    # 1. Модели из config.yaml (override) — с составным ID
    for model_name, model_cfg in cfg.get("models", {}).items():
        provider, mid = _split_config_model_key(model_name)
        composite_id = f"{provider or state.default_provider}::{mid}"
        seen.add(composite_id)
        models_list.append(
            {
                "id": composite_id,
                "object": "model",
                "created": 1700000000,
                "owned_by": model_cfg.get("provider", "SmartRouter"),
            }
        )
    # 2. Модели из кеша — с составным ID (provider + model_id)
    for m in state.get_all_available_models():
        mid = m["id"]
        prov = m.get("provider", state.default_provider)
        composite_id = f"{prov}::{mid}"
        if composite_id not in seen:
            models_list.append(
                {
                    "id": composite_id,
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": prov,
                }
            )
            seen.add(composite_id)
    return {"object": "list", "data": models_list}


@app.get("/models/available")
async def get_available_models(refresh: bool = Query(False)):
    if refresh:
        try:
            await state.sync_models_from_provider()
        except Exception as e:
            logger.error(f"Ошибка синка при refresh: {e}")

    # Группировка по провайдерам
    providers_dict = {}
    for p_name, model_ids in state.models_by_provider.items():
        models_list = []
        for mid in model_ids:
            key = f"{p_name}::{mid}"
            if key in state.available_models:
                models_list.append(state.available_models[key])
        providers_dict[p_name] = {
            "last_sync": state.provider_last_sync.get(p_name),
            "count": len(models_list),
            "models": models_list,
        }

    # Плоский список (BC)
    flat = sorted(
        state.available_models.values(),
        key=lambda m: m.get("name", m["id"]),
    )

    return {
        "providers": providers_dict,
        "models": flat,
        "last_sync": state._models_last_sync,
    }


@app.post("/models/sync")
async def sync_models(request: Request):
    body = {}
    try:
        raw = await request.body()
        if raw:
            body = await request.json()
    except Exception:
        pass

    provider = body.get("provider") if isinstance(body, dict) else None

    try:
        result = await state.sync_models_from_provider(provider)
        # BC: результат может не содержать status/results
        payload = {"status": result.get("status", "ok"), **result}
        if payload["status"] == "error":
            raise HTTPException(status_code=502, detail=payload)
        return payload
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sync failed: {e}")


@app.get("/health")
async def health():
    base_currency = cfg.get("currency", {}).get("base", "RUB")
    return {
        "status": "ok",
        "cost": f"{state.stats['total_cost']:.4f}",
        "currency": base_currency,
    }


@app.get("/stats")
async def get_stats():
    return state.stats


@app.get("/logs")
async def get_logs(level: str = Query(None), limit: int = Query(50)):
    """Возвращает логи из кольцевого буфера."""
    logs = list(log_buffer)
    if level:
        logs = [l for l in logs if l["level"] == level.upper()]
    return logs[-limit:]


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Веб-страница админки: логи + управление агентами."""
    admin_html = (
        ADMIN_HTML_FILE.read_text(encoding="utf-8")
        if ADMIN_HTML_FILE.exists()
        else "<h1>admin.html not found</h1>"
    )
    return HTMLResponse(admin_html)


@app.get("/config")
async def get_config():
    """Возвращает текущую конфигурацию маршрутизации."""
    return state.config


@app.get("/roles")
async def get_roles():
    """Возвращает роли и их модели (default + fallback) из config.yaml."""
    roles = {}
    for role_name, role_cfg in ROLES_CFG.items():
        # Вычисляем context_limit из модели роли (models_cache.json)
        role_model = get_role_default_model(role_name)
        context_limit = None
        if role_model:
            info = state.get_model_info(role_model)
            if info:
                context_limit = info.get("context_length")
        roles[role_name] = {
            "name": role_cfg.get("name", role_name),
            "description": role_cfg.get("description", ""),
            "default_model": role_cfg.get("default_model", ""),
            "fallback_model": get_role_fallback_model(role_name) or "",
            "agents": role_cfg.get("agents", []),
            "capabilities": role_cfg.get("capabilities", {}),
            "context_limit": context_limit,
        }
    return {"roles": roles}


@app.get("/roles/tuning")
async def get_roles_tuning():
    """Возвращает все tuning-конфиги для ролей."""
    return state.config.get("role_tuning", {})


@app.get("/roles/{name}/tuning")
async def get_role_tuning(name: str):
    """Возвращает tuning-конфиг для конкретной роли."""
    tuning = state.config.get("role_tuning", {})
    if name not in tuning:
        raise HTTPException(
            status_code=404, detail=f"Role '{name}' not found in tuning"
        )
    # Добавляем context_limit из models_cache
    role_model = get_role_default_model(name)
    result = dict(tuning[name])
    result["context_limit"] = None
    if role_model:
        info = state.get_model_info(role_model)
        if info:
            result["context_limit"] = info.get("context_length")
    return result


@app.put("/roles/{name}/tuning")
async def update_role_tuning(name: str, request: Request):
    """Сохраняет tuning-конфиг для роли."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    tuning = state.config.get("role_tuning", {})
    if name not in tuning:
        raise HTTPException(
            status_code=404, detail=f"Role '{name}' not found in tuning"
        )

    # Валидируем и обновляем разрешённые поля
    allowed = {
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "system_prompt_prefix",
    }
    for key in allowed:
        if key in data:
            tuning[name][key] = data[key]

    state.config["role_tuning"] = tuning
    await state.save_config(state.config)
    logger.info(f"🎚️ Tuning updated for role '{name}'")
    return {"status": "ok", "tuning": tuning[name]}


@app.post("/config")
async def update_config(request: Request):
    try:
        new_config = await request.json()
        await state.save_config(new_config)
        return {"status": "ok", "config": state.config}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/providers")
async def get_providers():
    """Возвращает список провайдеров (без API-ключей)."""
    result = {}
    for name, p in state.providers.items():
        result[name] = {k: v for k, v in p.items() if k != "api_key"}
        # Показываем только маску ключа (первые 4 + последние 4 символа)
        key_env = p.get("api_key_env", "")
        api_key = os.getenv(key_env, "")
        if api_key:
            masked = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
            result[name]["api_key_masked"] = masked
        result[name]["has_api_key"] = bool(api_key)
    return {
        "providers": result,
        "active_provider": state.default_provider,
        "default_provider": state.default_provider,
    }


@app.post("/providers")
async def add_provider(request: Request):
    """Добавляет или обновляет провайдера."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    name = data.get("name", "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Provider name is required")
    if not re.match(r"^[a-z][a-z0-9_]{2,30}$", name):
        raise HTTPException(
            status_code=400, detail="Invalid provider name (3-30 chars, a-z0-9_)"
        )

    provider = {
        "display_name": data.get("display_name", name),
        "base_url": data.get("base_url", ""),
        "api_key_env": data.get("api_key_env", f"{name.upper()}_API_KEY"),
        "default": data.get("default", False),
        "models_endpoint": data.get("models_endpoint", ""),
        # SSL: verify_ssl=false — для self-signed; ca_bundle — путь к своему CA
        "verify_ssl": data.get("verify_ssl", True),
        "ca_bundle": data.get("ca_bundle", ""),
        # Новые поля Phase 1
        "requires_api_key": data.get("requires_api_key", True),
        "pricing_mode": data.get("pricing_mode", "auto"),
        "extra_headers": data.get("extra_headers", {}),
    }

    if not provider["base_url"]:
        raise HTTPException(status_code=400, detail="base_url is required")

    # Если провайдер уже существует — обновляем, сохраняя ключи
    old_provider = state.providers.get(name, {})
    for k in ["api_key", "api_key_masked", "has_api_key"]:
        if k in old_provider:
            del old_provider[k]

    state.providers[name] = provider

    # SSL-настройки могли измениться — сбрасываем кэш клиентов этого провайдера
    invalidate_provider_clients(name)

    # Если default — снимаем default с остальных
    if data.get("default", False):
        for p_name in state.providers:
            state.providers[p_name]["default"] = p_name == name
        state.default_provider = name

    # Сохраняем API-ключ, если передан
    api_key_value = data.get("api_key", "")
    if api_key_value:
        await set_env_key(provider["api_key_env"], api_key_value)

    # Сохраняем config.yaml
    await state.save_config_yaml()

    logger.info(f"🔌 Провайдер '{name}' сохранён")
    return {
        "status": "ok",
        "provider": provider,
        "active": name == state.default_provider,
    }


async def set_env_key(key_env: str, value: str):
    """Записывает/обновляет API-ключ в .env файл (атомарно)."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        if f"{key_env}=" in content:
            # Заменяем существующий ключ
            lines = []
            replaced = False
            for line in content.splitlines():
                if line.startswith(f"{key_env}="):
                    lines.append(f"{key_env}={value}")
                    replaced = True
                else:
                    lines.append(line)
            if not replaced:
                lines.append(f"{key_env}={value}")
            state._atomic_write(env_file, "\n".join(lines) + "\n")
        else:
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"\n{key_env}={value}\n")
    else:
        state._atomic_write(env_file, f"{key_env}={value}\n")
    # Обновляем в runtime
    load_dotenv(override=True)
    logger.info(f"🔑 API-ключ {key_env} обновлён в .env")


@app.delete("/providers/{name}")
async def delete_provider(name: str):
    """Удаляет провайдера."""
    if name not in state.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")
    if len(state.providers) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last provider")

    del state.providers[name]
    invalidate_provider_clients(name)

    # Если удалили активного — назначаем первого
    if name == state.default_provider:
        state.default_provider = next(iter(state.providers.keys()))
        state.providers[state.default_provider]["default"] = True

    await state.save_config_yaml()
    logger.info(f"\U0001f50c Провайдер '{name}' удалён")
    return {"status": "ok", "active_provider": state.default_provider, "default_provider": state.default_provider}


@app.post("/v1/chat/completions")
async def proxy(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    original_model = body.get("model", "")

    if any(b in original_model.lower() for b in BLACKLIST):
        raise HTTPException(status_code=400, detail=f"Устаревшее API: {original_model}")

    # Умная маршрутизация — возвращает составную спецификацию
    spec, role, reason = smart_route_model(original_model, body)
    provider, model_id = resolve_model_spec(spec)
    body["model"] = model_id  # ← БЕЗ префикса "provider::"

    if spec != original_model and "::" not in original_model:
        state.stats["routed_count"] += 1
        logger.info(f"\U0001f504 Маршрутизация: {original_model} -> {spec} ({reason})")
    else:
        state.stats["not_routed_count"] += 1

    # ============================================================
    # \ud83c\udfa1\ufe0f Применение Fine Tuning для роли
    # ============================================================
    if role:
        tuning = state.config.get("role_tuning", {}).get(role, {})

        # 1. Default-параметры: только если Zed/клиент их НЕ указал
        for param in ["temperature", "top_p", "presence_penalty", "frequency_penalty"]:
            if param not in body and tuning.get(param) is not None:
                body[param] = tuning[param]

        # 2. Auto max_tokens cap — динамический, из context_length модели
        model_info = state.get_model_info(spec)
        if model_info:
            context_limit = model_info.get("context_length", 0)
            client_max = body.get("max_tokens", 0)
            if context_limit > 0 and client_max:
                max_allowed = int(context_limit * 0.6)
                capped = min(client_max, max(max_allowed, 4096))
                if capped < client_max:
                    logger.info(
                        f"\U0001f6e1\ufe0f Capped max_tokens {client_max} \u2192 {capped} "
                        f"({spec}: 60% of {context_limit})"
                    )
                    body["max_tokens"] = capped

        # 3. System prompt prefix
        prefix = tuning.get("system_prompt_prefix", "")
        if prefix and isinstance(prefix, str) and prefix.strip():
            messages = body.get("messages", [])
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = prefix + "\n\n" + messages[0]["content"]
            elif messages:
                messages.insert(0, {"role": "system", "content": prefix})
            body["messages"] = messages

    def _build_provider_headers(prov: str) -> dict:
        """Строит заголовки для запроса к провайдеру."""
        p_cfg = state.providers.get(prov, {})
        hdrs = {"Content-Type": "application/json"}
        key_env = p_cfg.get("api_key_env", "")
        api_key = os.getenv(key_env, "")
        if api_key:
            hdrs["Authorization"] = f"Bearer {sanitize_ascii(api_key)}"
        # extra_headers провайдера
        extra = p_cfg.get("extra_headers", {})
        if extra and isinstance(extra, dict):
            hdrs.update(extra)
        return hdrs

    def _check_provider_key(prov: str) -> str | None:
        """Проверяет наличие API-ключа. Возвращает ошибку или None."""
        p_cfg = state.providers.get(prov, {})
        if not p_cfg.get("requires_api_key", True):
            return None  # Ollama — без ключа
        key_env = p_cfg.get("api_key_env", "")
        api_key = os.getenv(key_env, "")
        if not api_key:
            return f"Missing API key: {key_env}"
        return None

    def _check_provider_url(prov: str) -> str | None:
        """Проверяет наличие base_url у провайдера. Возвращает ошибку или None."""
        url = state.get_provider_url(prov)
        if not url:
            return f"base_url не настроен для провайдера '{prov}'"
        return None

    is_stream = body.get("stream", False)

    if is_stream:
        # Streaming — fallback невозможен, используем primary provider
        key_error = _check_provider_key(provider)
        if key_error:
            raise HTTPException(status_code=502, detail=key_error)
        url_error = _check_provider_url(provider)
        if url_error:
            raise HTTPException(status_code=502, detail=url_error)

        target_url = state.get_provider_url(provider)
        headers = _build_provider_headers(provider)
        client = get_provider_client(provider)

        async def stream_generator():
            attempt = 0
            sent_any = False
            while True:
                try:
                    async with client.stream(
                        "POST", target_url, json=body, headers=headers
                    ) as resp:
                        if resp.status_code != 200:
                            error_text = await resp.aread()
                            logger.error(
                                f"Провайдер вернул {resp.status_code}: "
                                f"{error_text.decode('utf-8', errors='ignore')} \u2192 {target_url}"
                            )
                            yield f'data: {{"error": "Provider error {resp.status_code}"}}\n\n'
                            return

                        usage_found = False
                        async for chunk in resp.aiter_lines():
                            if chunk.startswith("data: "):
                                try:
                                    data = json.loads(chunk[6:])
                                    if "usage" in data and data["usage"]:
                                        usage = data["usage"]
                                        log_usage(
                                            spec,
                                            usage.get("prompt_tokens", 0),
                                            usage.get("completion_tokens", 0),
                                        )
                                        usage_found = True
                                except json.JSONDecodeError:
                                    pass

                            if chunk:
                                sent_any = True
                                yield chunk + "\n\n"

                        if not usage_found:
                            log_usage(spec, 0, 0)
                        return
                except RETRYABLE_ERRORS as e:
                    attempt += 1
                    if not sent_any and attempt < RETRY_ATTEMPTS:
                        delay = RETRY_BACKOFF * (2 ** (attempt - 1))
                        logger.warning(
                            f"\U0001f504 Streaming: \u043f\u043e\u0432\u0442\u043e\u0440 {attempt}/{RETRY_ATTEMPTS} \u0447\u0435\u0440\u0435\u0437 "
                            f"{delay:.1f}s \u2014 {type(e).__name__}: {e} \u2192 {target_url}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(
                        f"\u041e\u0448\u0438\u0431\u043a\u0430 streaming ({type(e).__name__}): {e} \u2192 {target_url}"
                    )
                    yield (
                        "data: "
                        + json.dumps({"error": f"{type(e).__name__}: {e}"})
                        + "\n\n"
                    )
                    return
                except Exception as e:
                    logger.error(
                        f"\u041e\u0448\u0438\u0431\u043a\u0430 streaming ({type(e).__name__}): {e} \u2192 {target_url}"
                    )
                    yield (
                        "data: "
                        + json.dumps({"error": f"{type(e).__name__}: {e}"})
                        + "\n\n"
                    )
                    return

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        # Non-streaming with fallback chain (per-provider)
        fallback_spec = get_role_fallback_model(role) if role else None
        chain = [spec]
        if fallback_spec and fallback_spec != spec:
            chain.append(fallback_spec)

        last_error: Exception | None = None
        for i, chain_spec in enumerate(chain):
            is_last = i == len(chain) - 1
            chain_provider, chain_model_id = resolve_model_spec(chain_spec)

            key_error = _check_provider_key(chain_provider)
            if key_error:
                if is_last:
                    raise HTTPException(status_code=502, detail=key_error)
                logger.warning(f"\u26a0\ufe0f Fallback skip (no key): {chain_spec}")
                continue

            url_error = _check_provider_url(chain_provider)
            if url_error:
                if is_last:
                    raise HTTPException(status_code=502, detail=url_error)
                logger.warning(f"\u26a0\ufe0f Fallback skip (no url): {chain_spec}")
                continue

            target_url = state.get_provider_url(chain_provider)
            headers = _build_provider_headers(chain_provider)
            client = get_provider_client(chain_provider)

            try:
                body["model"] = chain_model_id
                resp = await post_with_retry(
                    client, target_url, body, headers, label=f"(model={chain_spec})"
                )
                resp.raise_for_status()
                result = resp.json()

                usage = result.get("usage", {})
                log_usage(
                    chain_spec,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
                if i > 0:
                    logger.info(f"\u2705 Fallback successful: {chain_spec}")
                return JSONResponse(result)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code < 500:
                    logger.error(f"HTTP {e.response.status_code}: {e}")
                    raise HTTPException(
                        status_code=e.response.status_code,
                        detail=f"Provider error: {e.response.status_code}",
                    )
                if not is_last:
                    state.stats["fallback_count"] = (
                        state.stats.get("fallback_count", 0) + 1
                    )
                    logger.warning(
                        f"\u26a0\ufe0f Fallback: {chain_spec} \u2192 {chain[i + 1]} "
                        f"(HTTP {e.response.status_code})"
                    )
                else:
                    logger.error(
                        f"\u274c All models failed. Last: {chain_spec} "
                        f"({e.response.status_code})"
                    )
            except httpx.TimeoutException as e:
                last_error = e
                if not is_last:
                    state.stats["fallback_count"] = (
                        state.stats.get("fallback_count", 0) + 1
                    )
                    logger.warning(
                        f"\u26a0\ufe0f Fallback (timeout): {chain_spec} \u2192 {chain[i + 1]}"
                    )
                else:
                    logger.error(f"\u274c Timeout on last model: {chain_spec}")
            except httpx.HTTPError as e:
                last_error = e
                if not is_last:
                    state.stats["fallback_count"] = (
                        state.stats.get("fallback_count", 0) + 1
                    )
                    logger.warning(
                        f"\u26a0\ufe0f Fallback (HTTP error): {chain_spec} \u2192 {chain[i + 1]}"
                    )
                else:
                    logger.error(f"\u274c HTTP error on last model: {chain_spec}: {e}")

        # All models in chain failed
        if isinstance(last_error, httpx.TimeoutException):
            raise HTTPException(
                status_code=504, detail="Gateway Timeout (all models failed)"
            )
        raise HTTPException(status_code=502, detail="Bad Gateway (all models failed)")


# ============================================================
# 🚀 ЗАПУСК СЕРВЕРА
# ============================================================
SERVER_CFG = cfg.get("server", {})
ROUTER_PORT = int(SERVER_CFG.get("router_port", 8765))
ADMIN_PORT = int(SERVER_CFG.get("admin_port", 8766))
ADMIN_HOST = str(SERVER_CFG.get("admin_host", "127.0.0.1"))
SINGLE_PORT = bool(SERVER_CFG.get("single_port", True))


def _run_single_port():
    """Single-port mode: everything on router_port (default)."""
    logger.info(
        f"🚀 SmartRouter запущен на http://{ADMIN_HOST}:{ROUTER_PORT} "
        f"(single-port: router + admin)"
    )
    # Передаём объект app, а не строку "router:app" — иначе uvicorn
    # импортирует модуль второй раз (двойной state и дубли логов).
    uvicorn.run(
        app,
        host=ADMIN_HOST,
        port=ROUTER_PORT,
        reload=False,
    )


def _run_dual_port():
    """Dual-port mode: router on router_port, admin on admin_port."""
    import asyncio
    import threading

    def run_admin():
        """Runs admin server in a separate thread."""
        admin_config = uvicorn.Config(
            app=app,
            host=ADMIN_HOST,
            port=ADMIN_PORT,
            reload=False,
            log_level="warning",
        )
        admin_server = uvicorn.Server(admin_config)
        asyncio.run(admin_server.serve())

    admin_thread = threading.Thread(target=run_admin, daemon=True)
    admin_thread.start()
    logger.info(
        f"🚀 SmartRouter: router on http://{ADMIN_HOST}:{ROUTER_PORT}, "
        f"admin on http://{ADMIN_HOST}:{ADMIN_PORT}"
    )
    uvicorn.run(
        app,
        host=ADMIN_HOST,
        port=ROUTER_PORT,
        reload=False,
    )


if __name__ == "__main__":
    if SINGLE_PORT:
        _run_single_port()
    else:
        _run_dual_port()
