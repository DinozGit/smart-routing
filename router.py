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
        "emoji": model_cfg.get("emoji", "🤖"),
        "role": model_cfg.get("role", "Worker"),
    }

# Пороги из конфига
ROUTING_CFG = cfg.get("routing", {})
MIN_FINGERPRINT_SCORE = ROUTING_CFG.get("min_fingerprint_score", 10)
MIN_SCOPE_SCORE = ROUTING_CFG.get("min_scope_score", 8)
COORDINATOR_PROMPT_THRESHOLD = ROUTING_CFG.get("coordinator_prompt_threshold", 3000)
HEURISTIC_THRESHOLD = ROUTING_CFG.get("heuristic_threshold", 2)

# Логи
MAX_LOG_ENTRIES = cfg.get("logging", {}).get("max_entries", 500)

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
    Если fallback_model указан в config.yaml — использует его.
    Иначе вычисляет автоматически по правилу:
      coordinator    -> worker_default.default_model
      worker_default -> coordinator.default_model
      worker_img     -> worker_default.default_model
    """
    role = get_role_config(role_name)
    explicit = role.get("fallback_model")
    if explicit:
        return explicit
    auto_map = {
        "coordinator": "worker_default",
        "worker_default": "coordinator",
        "worker_img": "worker_default",
    }
    fallback_role = auto_map.get(role_name)
    if fallback_role:
        return get_role_default_model(fallback_role)
    return None


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
        self._active_provider = self._determine_active_provider()
        # Кеш моделей из провайдера (RouterAI API)
        self.available_models: Dict[str, dict] = {}  # model_id → info
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

    def get_active_provider_url(self) -> str:
        """Возвращает base_url активного провайдера."""
        provider = self.providers.get(self._active_provider, {})
        return provider.get("base_url", "https://routerai.ru/api/v1/chat/completions")

    def get_active_provider_key_env(self) -> str:
        """Возвращает имя env-переменной с API-ключом."""
        provider = self.providers.get(self._active_provider, {})
        return provider.get("api_key_env", "ROUTERAI_KEY")

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
                self._init_default_config()
                migrated = True
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

    def _load_models_cache(self):
        """Загружает кеш моделей из models_cache.json."""
        if self.models_cache_file.exists():
            try:
                with open(self.models_cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.available_models = {}
                for m in data.get("models", []):
                    self.available_models[m["id"]] = m
                self._models_last_sync = data.get("last_sync")
                logger.info(
                    f"📦 Загружено {len(self.available_models)} моделей из кеша"
                )
            except Exception as e:
                logger.error(f"Ошибка загрузки models_cache.json: {e}")
                self.available_models = {}

    def get_model_info(self, model_id: str) -> dict | None:
        """Возвращает информацию о модели из кеша или None."""
        return self.available_models.get(model_id)

    def get_all_available_models(self) -> list:
        """Возвращает список всех моделей из кеша."""
        return sorted(
            self.available_models.values(),
            key=lambda m: m.get("name", m["id"]),
        )

    async def sync_models_from_provider(self) -> dict:
        """Синхронизирует список моделей из RouterAI API."""
        provider = self.providers.get("routerai", {})
        endpoint = provider.get("models_endpoint", "")
        if not endpoint:
            raise ValueError("models_endpoint не настроен для routerai")

        async with self.models_lock:
            try:
                client = get_provider_client("routerai")
                resp = await client.get(endpoint, timeout=30.0)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Ошибка синхронизации моделей с RouterAI: {e}")
                raise

            raw_models = data.get("data", [])
            self.available_models = {}
            for m in raw_models:
                pricing = m.get("pricing", {})
                # RouterAI: ₽ за 1 токен → ₽ за 1M токенов
                inp = round(pricing.get("prompt", 0) * 1_000_000, 4)
                out = round(pricing.get("completion", 0) * 1_000_000, 4)
                self.available_models[m["id"]] = {
                    "id": m["id"],
                    "name": m.get("name", m["id"]),
                    "description": m.get("description", ""),
                    "context_length": m.get("context_length", 0),
                    "input_price_1m": inp,
                    "output_price_1m": out,
                    "supported_parameters": m.get("supported_parameters", []),
                    "input_modalities": m.get("architecture", {}).get(
                        "input_modalities", ["text"]
                    ),
                    "output_modalities": m.get("architecture", {}).get(
                        "output_modalities", ["text"]
                    ),
                }

            now = time.time()
            self._models_last_sync = now
            cache_data = {
                "models": list(self.available_models.values()),
                "last_sync": now,
                "provider": "routerai",
            }
            await asyncio.to_thread(
                lambda: self.models_cache_file.write_text(
                    json.dumps(cache_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            )
            logger.info(
                f"🔄 Синхронизировано {len(self.available_models)} моделей из RouterAI"
            )
            return {
                "synced": len(self.available_models),
                "last_sync": now,
            }

    async def save_config(self, new_config: dict):
        async with self.config_lock:
            self.config.update(new_config)
            await asyncio.to_thread(
                self._sync_write_config, self.config_file, self.config
            )

    async def save_config_yaml(self):
        """Сохраняет config.yaml с обновлёнными провайдерами."""
        cfg_copy = dict(cfg)  # загруженный при старте
        cfg_copy["providers"] = self.providers
        async with self.config_lock:
            await asyncio.to_thread(
                lambda: Path(CONFIG_FILE).write_text(
                    yaml.dump(cfg_copy, default_flow_style=False, allow_unicode=True),
                    encoding="utf-8",
                )
            )
        logger.info(f"✅ config.yaml обновлён с провайдерами")

    @staticmethod
    def _sync_write_config(path: Path, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


state = RouterState()

# ============================================================
# 🧠 ПРЕДКОМПИЛИРОВАННЫЕ РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ (ОПТИМИЗАЦИЯ)
# ============================================================
SPAWN_AGENT_PATTERN = re.compile(r'spawn_agent\s*\(\s*["\'](\w+)["\']', re.IGNORECASE)

# Паттерн для явного тега агента в user-сообщении: [AGENT:name]
AGENT_TAG_PATTERN = re.compile(r"\[AGENT:(\w+)\]", re.IGNORECASE)

# Fingerprint-паттерны для определения агента по system prompt.
# Каждый агент CalorIt имеет уникальные маркеры (из AGENTS.md):
# название роли, write scope, ключевые технологии.
# Формат: {agent_name: [(regex, weight), ...]}
AGENT_FINGERPRINTS = {
    "database": [
        (re.compile(r"CalorIt\s+Database", re.IGNORECASE), 10),
        (re.compile(r"SQLAlchemy\s+models", re.IGNORECASE), 8),
        (re.compile(r"alembic.*migration", re.IGNORECASE), 8),
        (re.compile(r"CRUD\s+operations", re.IGNORECASE), 6),
        (re.compile(r"database/\*\.py", re.IGNORECASE), 5),
    ],
    "tests": [
        (re.compile(r"CalorIt\s+Tests", re.IGNORECASE), 10),
        (re.compile(r"Pytest\s+unit.*integration", re.IGNORECASE), 8),
        (re.compile(r"Write\s+scope.*tests/", re.IGNORECASE), 8),
        (re.compile(r"\bpytest\b.*\btests?/\b", re.IGNORECASE), 6),
    ],
    "bot": [
        (re.compile(r"CalorIt\s+Telegram\s+Bot", re.IGNORECASE), 10),
        (re.compile(r"aiogram\s+handlers", re.IGNORECASE), 8),
        (re.compile(r"FSM\s+states", re.IGNORECASE), 8),
        (re.compile(r"inline\s+keyboards", re.IGNORECASE), 6),
        (re.compile(r"handlers/\*\.py", re.IGNORECASE), 5),
    ],
    "devops": [
        (re.compile(r"CalorIt\s+DevOps", re.IGNORECASE), 10),
        (re.compile(r"Docker.*CI/CD.*Nginx", re.IGNORECASE), 8),
        (re.compile(r"docker-compose.*\.yml", re.IGNORECASE), 8),
        (re.compile(r"SSL.*deployment", re.IGNORECASE), 6),
    ],
    "api": [
        (re.compile(r"CalorIt\s+API\s+Layer", re.IGNORECASE), 10),
        (re.compile(r"FastAPI\s+endpoints", re.IGNORECASE), 8),
        (re.compile(r"Pydantic\s+schemas", re.IGNORECASE), 8),
        (re.compile(r"JWT\s+middleware", re.IGNORECASE), 6),
        (re.compile(r"api/\*\.py", re.IGNORECASE), 5),
    ],
    "services": [
        (re.compile(r"CalorIt\s+Services", re.IGNORECASE), 10),
        (re.compile(r"AI\s+service.*OpenRouter", re.IGNORECASE), 8),
        (re.compile(r"cache\s+merge", re.IGNORECASE), 6),
        (
            re.compile(
                r"nutrition_service|reminder_service|APScheduler", re.IGNORECASE
            ),
            8,
        ),
        (re.compile(r"services/\*\.py", re.IGNORECASE), 5),
    ],
    "frontend": [
        (re.compile(r"CalorIt\s+Frontend", re.IGNORECASE), 10),
        (re.compile(r"Next\.?js.*dashboard", re.IGNORECASE), 8),
        (re.compile(r"Telegram\s+Login\s+Widget", re.IGNORECASE), 6),
        (re.compile(r"frontend/\*\*/\*", re.IGNORECASE), 5),
        (re.compile(r"\bReact\b.*components", re.IGNORECASE), 6),
    ],
    "mobile": [
        (re.compile(r"CalorIt\s+Mobile", re.IGNORECASE), 10),
        (re.compile(r"Flutter.*Dart", re.IGNORECASE), 8),
        (re.compile(r"calorit_app", re.IGNORECASE), 8),
        (re.compile(r"mobile/\*\*/\*", re.IGNORECASE), 5),
        (re.compile(r"Android.*iOS|push.уведомлени", re.IGNORECASE), 6),
    ],
    "design": [
        (re.compile(r"CalorIt\s+Design", re.IGNORECASE), 10),
        (re.compile(r"design\s+tokens", re.IGNORECASE), 8),
        (re.compile(r"Material\s*3", re.IGNORECASE), 6),
        (re.compile(r"Figma.*экспорт", re.IGNORECASE), 6),
        (re.compile(r"design/\*\*/\*", re.IGNORECASE), 5),
    ],
    "coordinator": [
        (re.compile(r"Coordinator.*главный\s+агент", re.IGNORECASE), 10),
        (re.compile(r"SYSTEM_CONTEXT\.md", re.IGNORECASE), 8),
        (re.compile(r"декомпозици.*фаз", re.IGNORECASE), 8),
        (re.compile(r"spawn_agent.*распределение", re.IGNORECASE), 6),
        (re.compile(r"Деплой\s+на\s+VPS\s+через\s+SSH", re.IGNORECASE), 6),
    ],
}

# Компилируем эвристические паттерны один раз при старте
COMPILED_PATTERNS = {
    "flash": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"\balembic\b",
            r"\bmigrations?\b",
            r"\bpytest\b",
            r"\btest_[a-z_]+\b",
            r"\bdocker[- ]?compose\s+up\b",
            r"\b@router\.(get|post|put|delete|patch)\b",
        ]
    ],
    "qwen": [
        re.compile(p, re.IGNORECASE)
        for p in [
            r"\b\.tsx\b",
            r"\b\.jsx\b",
            r"\buseState\b",
            r"\buseEffect\b",
            r"\bNext\.?js\b",
            r"\btailwind\b",
        ]
    ],
}


# ============================================================
# 🛠 УТИЛИТЫ
# ============================================================
def sanitize_ascii(value: str) -> str:
    return re.sub(r"[^\x00-\x7F]+", "", str(value))


def log_usage(model: str, input_tokens: int, output_tokens: int):
    """Обновляет статистику и логирует"""
    state.stats["requests"] += 1
    state.stats["total_input"] += input_tokens
    state.stats["total_output"] += output_tokens

    price_info = PRICES.get(model)
    if not price_info:
        cm = state.get_model_info(model)
        if cm:
            price_info = {
                "input": cm["input_price_1m"],
                "output": cm["output_price_1m"],
                "role": "Unknown",
            }
    if not price_info:
        price_info = {"input": 0.50, "output": 1.50, "role": "Unknown"}
    cost = (
        input_tokens * price_info["input"] + output_tokens * price_info["output"]
    ) / 1_000_000
    state.stats["total_cost"] += cost

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
        f"💰 {model}: In {input_tokens} | Out {output_tokens} | Cost ${cost:.6f}"
    )


# ============================================================
# 🧠 УМНАЯ МАРШРУТИЗАЦИЯ
# ============================================================
def fingerprint_system_prompt(system_prompt: str) -> Tuple[str, int] | None:
    """
    Определяет роль агента CalorIt по содержимому system prompt.
    Возвращает (agent_name, score) или None, если агент не определён.
    """
    if not system_prompt:
        return None

    best_agent = None
    best_score = 0

    for agent, patterns in AGENT_FINGERPRINTS.items():
        score = 0
        for pattern, weight in patterns:
            if pattern.search(system_prompt):
                score += weight
        if score > best_score:
            best_score = score
            best_agent = agent

    if best_score >= MIN_FINGERPRINT_SCORE:
        return (best_agent, best_score)
    return None


# ============================================================
# 🔍 USER MESSAGE FINGERPRINTING
# ============================================================
# Паттерны для определения агента по содержимому user-сообщений.
# Sub-agents Zed не получают AGENTS.md в system prompt, но получают
# задачи от Coordinator с write scope, файлами и responsibilities.
AGENT_SCOPE_PATTERNS = {
    "database": [
        # Технические маркеры
        (re.compile(r"database/\*\.py", re.IGNORECASE), 12),
        (re.compile(r"SQLAlchemy", re.IGNORECASE), 8),
        (re.compile(r"alembic/versions?/\*\.py", re.IGNORECASE), 10),
        (re.compile(r"CRUD", re.IGNORECASE), 8),
        (re.compile(r"alembic\.ini", re.IGNORECASE), 6),
        (re.compile(r"migrations", re.IGNORECASE), 5),
        # Естественный язык
        (re.compile(r"миграц|migration", re.IGNORECASE), 8),
        (re.compile(r"таблиц|CREATE\s+TABLE", re.IGNORECASE), 7),
        (re.compile(r"модел[ьиыо]", re.IGNORECASE), 6),
        (re.compile(r"\bSQL\b|\bORM\b", re.IGNORECASE), 5),
    ],
    "tests": [
        # Технические маркеры
        (re.compile(r"tests?/\*\.py", re.IGNORECASE), 12),
        (re.compile(r"Pytest\s+unit.*integration", re.IGNORECASE), 10),
        (re.compile(r"Write\s+scope.*tests?/", re.IGNORECASE), 10),
        (re.compile(r"\bpytest\b", re.IGNORECASE), 6),
        (re.compile(r"unit.*integration.*tests?", re.IGNORECASE), 6),
        # Естественный язык
        (re.compile(r"напиши\s+тест|write\s+test", re.IGNORECASE), 9),
        (re.compile(r"покрыт|coverage", re.IGNORECASE), 8),
        (re.compile(r"\bassert\b|\bmock\b", re.IGNORECASE), 5),
    ],
    "bot": [
        # Технические маркеры
        (re.compile(r"handlers/\*\.py", re.IGNORECASE), 12),
        (re.compile(r"aiogram\s+handlers", re.IGNORECASE), 10),
        (re.compile(r"FSM\s+states", re.IGNORECASE), 8),
        (re.compile(r"inline\s+keyboards", re.IGNORECASE), 8),
        (re.compile(r"keyboards?\.py", re.IGNORECASE), 7),
        # Естественный язык
        (re.compile(r"\bбот[а-я]*|\btelegram\b", re.IGNORECASE), 8),
        (re.compile(r"handler|обработчик", re.IGNORECASE), 6),
        (re.compile(r"клавиатур|keyboard", re.IGNORECASE), 7),
        (re.compile(r"\baiogram\b", re.IGNORECASE), 7),
        (re.compile(r"\binline\b", re.IGNORECASE), 6),
    ],
    "devops": [
        # Технические маркеры
        (re.compile(r"Dockerfile", re.IGNORECASE), 12),
        (re.compile(r"docker-compose.*\.yml", re.IGNORECASE), 10),
        (re.compile(r"nginx.*\.conf", re.IGNORECASE), 10),
        (re.compile(r"\.github/workflows?", re.IGNORECASE), 10),
        (re.compile(r"CI/CD.*Nginx.*SSL", re.IGNORECASE), 8),
        # Естественный язык
        (re.compile(r"деплой|deploy", re.IGNORECASE), 7),
        (re.compile(r"контейнер|docker", re.IGNORECASE), 6),
        (re.compile(r"сертификат|certbot|SSL", re.IGNORECASE), 6),
        (re.compile(r"\bnginx\b", re.IGNORECASE), 8),
    ],
    "api": [
        # Технические маркеры
        (re.compile(r"api/\*\.py", re.IGNORECASE), 12),
        (re.compile(r"schemas?\.py", re.IGNORECASE), 10),
        (re.compile(r"middleware\.py", re.IGNORECASE), 8),
        (re.compile(r"FastAPI\s+endpoints", re.IGNORECASE), 10),
        (re.compile(r"Pydantic\s+schemas", re.IGNORECASE), 8),
        (re.compile(r"JWT\s+middleware", re.IGNORECASE), 6),
        # Естественный язык
        (re.compile(r"эндпоинт|endpoint", re.IGNORECASE), 8),
        (re.compile(r"роут|route|@app\.", re.IGNORECASE), 7),
        (re.compile(r"\bfastapi\b", re.IGNORECASE), 7),
        (re.compile(r"\bpydantic\b", re.IGNORECASE), 8),
    ],
    "services": [
        # Технические маркеры
        (re.compile(r"services?/\*\.py", re.IGNORECASE), 12),
        (re.compile(r"nutrition_service|reminder_service", re.IGNORECASE), 10),
        (re.compile(r"APScheduler", re.IGNORECASE), 8),
        (re.compile(r"AI\s+service.*OpenRouter", re.IGNORECASE), 8),
        (re.compile(r"cache\s+merge", re.IGNORECASE), 6),
        # Естественный язык
        (re.compile(r"сервис|service", re.IGNORECASE), 6),
        (re.compile(r"калори|calor|nutrition", re.IGNORECASE), 7),
        (re.compile(r"расчет|calculate|BMI|BMR", re.IGNORECASE), 6),
    ],
    "frontend": [
        # Технические маркеры
        (re.compile(r"frontend/\*\*/\*", re.IGNORECASE), 12),
        (re.compile(r"Next\.?js", re.IGNORECASE), 10),
        (re.compile(r"\bReact\b", re.IGNORECASE), 8),
        (re.compile(r"Telegram\s+Login\s+Widget", re.IGNORECASE), 6),
        (re.compile(r"\.tsx\b|\.jsx\b", re.IGNORECASE), 6),
        # Естественный язык
        (re.compile(r"компонент|component", re.IGNORECASE), 7),
        (re.compile(r"страниц|page|landing", re.IGNORECASE), 6),
        (re.compile(r"\buse(state|effect)\b", re.IGNORECASE), 6),
        (re.compile(r"вёрстка|layout|dashboard", re.IGNORECASE), 6),
    ],
    "mobile": [
        # Технические маркеры
        (re.compile(r"mobile/\*\*/\*", re.IGNORECASE), 12),
        (re.compile(r"Flutter.*Dart", re.IGNORECASE), 10),
        (re.compile(r"calorit_app", re.IGNORECASE), 8),
        (re.compile(r"MOBILE_APP_PLAN\.md", re.IGNORECASE), 6),
        # Естественный язык
        (re.compile(r"\bflutter\b|\bdart\b", re.IGNORECASE), 8),
        (re.compile(r"экран|screen", re.IGNORECASE), 6),
        (re.compile(r"виджет|widget", re.IGNORECASE), 6),
        (re.compile(r"\bandroid\b|\bios\b", re.IGNORECASE), 5),
    ],
    "design": [
        # Технические маркеры
        (re.compile(r"design/\*\*/\*", re.IGNORECASE), 12),
        (re.compile(r"design\s+tokens", re.IGNORECASE), 10),
        (re.compile(r"Material\s*3", re.IGNORECASE), 8),
        (re.compile(r"Figma", re.IGNORECASE), 6),
        (re.compile(r"design/context", re.IGNORECASE), 6),
        # Естественный язык
        (re.compile(r"дизайн|design", re.IGNORECASE), 7),
        (re.compile(r"цвет|color|palette", re.IGNORECASE), 6),
        (re.compile(r"тема|theme|dark.*light", re.IGNORECASE), 6),
        (re.compile(r"\bиконк|icon|лого\b", re.IGNORECASE), 5),
    ],
    "coordinator": [
        # Технические маркеры
        (re.compile(r"SYSTEM_CONTEXT\.md", re.IGNORECASE), 12),
        (re.compile(r"Coordinator.*главный\s+агент", re.IGNORECASE), 10),
        (re.compile(r"декомпозици.*фаз", re.IGNORECASE), 8),
        (re.compile(r"Деплой\s+на\s+VPS\s+через\s+SSH", re.IGNORECASE), 6),
        # Естественный язык
        (re.compile(r"архитектур|architecture", re.IGNORECASE), 7),
        (re.compile(r"разбей\s+задач|декомпозиц", re.IGNORECASE), 8),
        (re.compile(r"код.ревью|code.review", re.IGNORECASE), 6),
        (re.compile(r"\bплан\b", re.IGNORECASE), 6),
        (re.compile(r"\bфаз[а-я]*", re.IGNORECASE), 6),
    ],
}


def fingerprint_user_messages(messages: list) -> Tuple[str, int] | None:
    """
    Определяет роль агента CalorIt по содержимому ВСЕХ user-сообщений.
    Решает проблему sub-agents в Zed, которые не получают AGENTS.md
    в свой system prompt, но получают задачи с write scope и файлами.
    Возвращает (agent_name, score) или None, если агент не определён.
    """
    # Собираем весь текст из user-сообщений
    all_user_content = ""
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            all_user_content += content + "\n"
        elif isinstance(content, list):
            # content может быть массивом parts
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if text:
                        all_user_content += text + "\n"

    if not all_user_content.strip():
        return None

    best_agent = None
    best_score = 0

    for agent, patterns in AGENT_SCOPE_PATTERNS.items():
        score = 0
        for pattern, weight in patterns:
            if pattern.search(all_user_content):
                score += weight
        if score > best_score:
            best_score = score
            best_agent = agent

    if best_score >= MIN_SCOPE_SCORE:
        logger.info(f"🔍 UserMsg fingerprint: {best_agent} (score={best_score})")
        return (best_agent, best_score)
    return None


def smart_route_model(
    requested_model: str, body: Dict[str, Any]
) -> Tuple[str, str, str]:
    """
    Умная маршрутизация запроса.
    Возвращает (model, role, reason):
      - model: целевая модель для провайдера
      - role: имя роли (coordinator / worker_default / worker_img) или ""
      - reason: человекочитаемое объяснение
    """
    # 1. Явная модель — если уже содержит flash или qwen, не трогаем
    if any(m in requested_model.lower() for m in ["flash", "qwen"]):
        return requested_model, "", "Без изменений (уже дешевая)"

    messages = body.get("messages", [])
    if not messages:
        coord_model = (
            state.config.get("role_models", {}).get("coordinator")
            or get_role_default_model("coordinator")
            or requested_model
        )
        return coord_model, "coordinator", "Нет сообщений -> coordinator"

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
            return (model, role, f"{mech}: {agent}")
        role = get_role_for_agent(agent)
        if role:
            model = state.config.get("role_models", {}).get(
                role
            ) or get_role_default_model(role)
            if model:
                return (model, role, f"{mech}: {agent} (auto -> {role} default)")
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
        return coord_model, "coordinator", "Пустой user prompt -> coordinator"

    # 8. Default — ничего не распознано → Coordinator
    coord_model = (
        state.config.get("role_models", {}).get("coordinator")
        or get_role_default_model("coordinator")
        or state.config.get("default_worker", requested_model)
    )
    return coord_model, "coordinator", "Unknown → coordinator default"


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
    """OpenAI-compatible model list (требуется Zed при подключении)."""
    models_list = []
    seen = set()
    # 1. Модели из config.yaml (baseline)
    for model_name, model_cfg in cfg.get("models", {}).items():
        seen.add(model_name)
        models_list.append(
            {
                "id": model_name,
                "object": "model",
                "created": 1700000000,
                "owned_by": model_cfg.get("provider", "SmartRouter"),
            }
        )
    # 2. Модели из кеша RouterAI (дополнение, без дубликатов)
    for m in state.get_all_available_models():
        if m["id"] not in seen:
            models_list.append(
                {
                    "id": m["id"],
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "RouterAI",
                }
            )
    return {"object": "list", "data": models_list}


@app.get("/models/available")
async def get_available_models(refresh: bool = Query(False)):
    if refresh:
        await state.sync_models_from_provider()
    return {
        "models": state.get_all_available_models(),
        "last_sync": state._models_last_sync,
    }


@app.post("/models/sync")
async def sync_models():
    try:
        result = await state.sync_models_from_provider()
        return {"status": "ok", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Sync failed: {e}")


@app.get("/health")
async def health():
    return {"status": "ok", "cost": f"${state.stats['total_cost']:.4f}"}


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
        "active_provider": state._active_provider,
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
        state._active_provider = name

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
        "active": name == state._active_provider,
    }


async def set_env_key(key_env: str, value: str):
    """Записывает/обновляет API-ключ в .env файл."""
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
            env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"\n{key_env}={value}\n")
    else:
        env_file.write_text(f"{key_env}={value}\n", encoding="utf-8")
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
    if name == state._active_provider:
        state._active_provider = next(iter(state.providers.keys()))
        state.providers[state._active_provider]["default"] = True

    await state.save_config_yaml()
    logger.info(f"🔌 Провайдер '{name}' удалён")
    return {"status": "ok", "active_provider": state._active_provider}


@app.post("/v1/chat/completions")
async def proxy(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    original_model = body.get("model", "")

    if any(b in original_model.lower() for b in BLACKLIST):
        raise HTTPException(status_code=400, detail=f"Устаревшее API: {original_model}")

    # Умная маршрутизация
    actual_model, role, reason = smart_route_model(original_model, body)
    body["model"] = actual_model

    if actual_model != original_model:
        state.stats["routed_count"] += 1
        logger.info(f"🔄 Маршрутизация: {original_model} -> {actual_model} ({reason})")
    else:
        state.stats["not_routed_count"] += 1

    # ============================================================
    # 🎚️ Применение Fine Tuning для роли
    # ============================================================
    if role:
        tuning = state.config.get("role_tuning", {}).get(role, {})

        # 1. Default-параметры: только если Zed/клиент их НЕ указал
        for param in ["temperature", "top_p", "presence_penalty", "frequency_penalty"]:
            if param not in body and tuning.get(param) is not None:
                body[param] = tuning[param]

        # 2. Auto max_tokens cap — динамический, из context_length модели
        model_info = state.get_model_info(actual_model)
        if model_info:
            context_limit = model_info.get("context_length", 0)
            client_max = body.get("max_tokens", 0)
            if context_limit > 0 and client_max:
                # Безопасный cap: не больше 60% от контекста модели.
                # Input токены считает провайдер — мы не можем их точно оценить
                # без токенизатора. 60% — консервативный запас.
                max_allowed = int(context_limit * 0.6)
                capped = min(client_max, max(max_allowed, 4096))
                if capped < client_max:
                    logger.info(
                        f"🛡️ Capped max_tokens {client_max} → {capped} "
                        f"({actual_model}: 60% of {context_limit})"
                    )
                    body["max_tokens"] = capped

        # 3. System prompt prefix — препендим перед тем, что прислал клиент
        prefix = tuning.get("system_prompt_prefix", "")
        if prefix and isinstance(prefix, str) and prefix.strip():
            messages = body.get("messages", [])
            if messages and messages[0].get("role") == "system":
                messages[0]["content"] = prefix + "\n\n" + messages[0]["content"]
            elif messages:
                messages.insert(0, {"role": "system", "content": prefix})
            body["messages"] = messages

    # Используем динамический URL из state (активный провайдер)
    target_url = state.get_active_provider_url()
    key_env = state.get_active_provider_key_env()
    api_key = os.getenv(key_env, "")
    if not api_key:
        logger.error(
            f"API-ключ для провайдера '{state._active_provider}' не найден в ${key_env}"
        )
        raise HTTPException(status_code=502, detail=f"Missing API key: {key_env}")

    headers = {
        "Authorization": f"Bearer {sanitize_ascii(api_key)}",
        "Content-Type": "application/json",
    }

    is_stream = body.get("stream", False)

    # Клиент с учётом SSL-настроек провайдера (ca_bundle / verify_ssl)
    client = get_provider_client(state._active_provider)

    if is_stream:

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
                                f"{error_text.decode('utf-8', errors='ignore')} → {target_url}"
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
                                            actual_model,
                                            usage.get("prompt_tokens", 0),
                                            usage.get("completion_tokens", 0),
                                        )
                                        usage_found = True
                                except json.JSONDecodeError:
                                    pass

                            # Если aiter_lines(), нужно возвращать с двойным переносом для SSE
                            if chunk:
                                sent_any = True
                                yield chunk + "\n\n"

                        if not usage_found:
                            log_usage(actual_model, 0, 0)
                        return
                except RETRYABLE_ERRORS as e:
                    attempt += 1
                    # Повторяем только если клиент ещё не получил ни одного байта
                    if not sent_any and attempt < RETRY_ATTEMPTS:
                        delay = RETRY_BACKOFF * (2 ** (attempt - 1))
                        logger.warning(
                            f"🔄 Streaming: повтор {attempt}/{RETRY_ATTEMPTS} через "
                            f"{delay:.1f}s — {type(e).__name__}: {e} → {target_url}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error(
                        f"Ошибка streaming ({type(e).__name__}): {e} → {target_url}"
                    )
                    yield (
                        "data: "
                        + json.dumps({"error": f"{type(e).__name__}: {e}"})
                        + "\n\n"
                    )
                    return
                except Exception as e:
                    logger.error(
                        f"Ошибка streaming ({type(e).__name__}): {e} → {target_url}"
                    )
                    yield (
                        "data: "
                        + json.dumps({"error": f"{type(e).__name__}: {e}"})
                        + "\n\n"
                    )
                    return

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        # Non-streaming with fallback chain (Step 2.2)
        # Chain: primary model → fallback_model (from role config)
        fallback_model = get_role_fallback_model(role) if role else None
        chain = [actual_model]
        if fallback_model and fallback_model != actual_model:
            chain.append(fallback_model)

        last_error: Exception | None = None
        for i, model in enumerate(chain):
            is_last = i == len(chain) - 1
            try:
                body["model"] = model
                resp = await post_with_retry(
                    client, target_url, body, headers, label=f"(model={model})"
                )
                resp.raise_for_status()
                result = resp.json()

                usage = result.get("usage", {})
                log_usage(
                    model,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )
                if i > 0:
                    logger.info(f"✅ Fallback successful: {model}")
                return JSONResponse(result)
            except httpx.HTTPStatusError as e:
                last_error = e
                # 4xx — client error, fallback не имеет смысла
                if e.response.status_code < 500:
                    logger.error(f"HTTP {e.response.status_code}: {e}")
                    raise HTTPException(
                        status_code=e.response.status_code,
                        detail=f"Provider error: {e.response.status_code}",
                    )
                # 5xx — try next in chain
                if not is_last:
                    state.stats["fallback_count"] = (
                        state.stats.get("fallback_count", 0) + 1
                    )
                    logger.warning(
                        f"⚠️ Fallback: {chain[i]} → {chain[i + 1]} "
                        f"(HTTP {e.response.status_code})"
                    )
                else:
                    logger.error(
                        f"❌ All models failed. Last: {model} "
                        f"({e.response.status_code})"
                    )
            except httpx.TimeoutException as e:
                last_error = e
                if not is_last:
                    state.stats["fallback_count"] = (
                        state.stats.get("fallback_count", 0) + 1
                    )
                    logger.warning(f"⚠️ Fallback (timeout): {chain[i]} → {chain[i + 1]}")
                else:
                    logger.error(f"❌ Timeout on last model: {model}")
            except httpx.HTTPError as e:
                last_error = e
                if not is_last:
                    state.stats["fallback_count"] = (
                        state.stats.get("fallback_count", 0) + 1
                    )
                    logger.warning(
                        f"⚠️ Fallback (HTTP error): {chain[i]} → {chain[i + 1]}"
                    )
                else:
                    logger.error(f"❌ HTTP error on last model: {model}: {e}")

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
