import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Tuple

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

# ============================================================
# 🔧 ИНИЦИАЛИЗАЦИЯ И НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SmartRouter")

# Загружаем переменные окружения из .env
load_dotenv()
ROUTERAI_KEY = os.getenv("ROUTERAI_KEY", "")

if not ROUTERAI_KEY:
    logger.critical(
        "ROUTERAI_KEY не найден! Создай файл .env: ROUTERAI_KEY=sk-ra-ТВОЙ_КЛЮЧ"
    )
    exit(1)

# ============================================================
# 🚫 КОНСТАНТЫ И КОНФИГУРАЦИИ
# ============================================================
BLACKLIST = {
    "gpt-3.5",
    "gpt-3.5-turbo",
    "claude-2",
    "claude-2.0",
    "claude-2.1",
    "gemini-pro",
    "gpt-4-turbo-preview",
    "gpt-4-32k",
    "text-davinci",
}

PRICES = {
    "deepseek/deepseek-v4-pro": {
        "input": 0.50,
        "output": 1.50,
        "provider": "RouterAI",
        "emoji": "🧠",
        "role": "Coordinator",
    },
    "deepseek/deepseek-v4-flash": {
        "input": 0.05,
        "output": 0.20,
        "provider": "RouterAI",
        "emoji": "⚡",
        "role": "Worker",
    },
    "qwen/qwen3-coder-next": {
        "input": 0.11,
        "output": 0.84,
        "provider": "RouterAI",
        "emoji": "💻",
        "role": "Frontend",
    },
}


# ============================================================
# 📋 СОСТОЯНИЕ (STATE)
# ============================================================
class RouterState:
    def __init__(self):
        self.config_file = Path(__file__).parent / "routing.json"
        self.config = {
            "agent_to_worker_mapping": {
                "database": "deepseek/deepseek-v4-flash",
                "frontend": "qwen/qwen3-coder-next",
                "coordinator": "deepseek/deepseek-v4-pro",
            },
            "default_worker": "deepseek/deepseek-v4-flash",
            "enable_auto_routing": True,
        }
        self.stats = {
            "requests": 0,
            "total_input": 0,
            "total_output": 0,
            "total_cost": 0.0,
            "by_model": {},
            "routed_count": 0,
            "not_routed_count": 0,
            "started_at": time.time(),
        }
        self.quota = {"last_check": 0, "is_ok": True}
        self.config_lock = asyncio.Lock()  # Защита от конкурентной записи файла

        self._load_config()

    def _load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self.config.update(json.load(f))
                logger.info(f"✅ Загружена конфигурация из {self.config_file}")
            except Exception as e:
                logger.error(f"Ошибка загрузки {self.config_file}: {e}")

    async def save_config(self, new_config: dict):
        async with self.config_lock:
            self.config.update(new_config)
            # Выполняем запись файла в отдельном потоке, чтобы не блокировать Event Loop
            await asyncio.to_thread(
                self._sync_write_config, self.config_file, self.config
            )

    @staticmethod
    def _sync_write_config(path: Path, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


state = RouterState()

# ============================================================
# 🧠 ПРЕДКОМПИЛИРОВАННЫЕ РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ (ОПТИМИЗАЦИЯ)
# ============================================================
SPAWN_AGENT_PATTERN = re.compile(r'spawn_agent\s*\(\s*["\'](\w+)["\']', re.IGNORECASE)

# Компилируем паттерны один раз при старте
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

    price_info = PRICES.get(model, {"input": 0.50, "output": 1.50, "role": "Unknown"})
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
def smart_route_model(requested_model: str, body: Dict[str, Any]) -> Tuple[str, str]:
    if any(m in requested_model.lower() for m in ["flash", "qwen"]):
        return requested_model, "Без изменений (уже дешевая)"

    messages = body.get("messages", [])
    if not messages:
        return requested_model, "Нет сообщений"

    # Ищем системный промпт и последнее сообщение пользователя
    system_prompt = ""
    last_user_msg = ""

    for msg in reversed(messages):
        role = msg.get("role")
        content = msg.get("content", "")
        if isinstance(content, str):
            if role == "user" and not last_user_msg:
                last_user_msg = content
            elif role == "system" and not system_prompt:
                system_prompt = content

    # Проверка на Coordinator
    if len(system_prompt) > 3000:
        return requested_model, "Coordinator (Большой system prompt)"

    if not last_user_msg:
        return requested_model, "Пустой user prompt"

    # 1. Проверка явного spawn_agent
    spawn_match = SPAWN_AGENT_PATTERN.search(last_user_msg)
    if spawn_match:
        agent = spawn_match.group(1).lower()
        mapping = state.config.get("agent_to_worker_mapping", {})
        if agent in mapping:
            return mapping[agent], f"spawn_agent: {agent}"
        if state.config.get("enable_auto_routing"):
            return state.config["default_worker"], f"spawn_agent (default fallback)"

    # 2. Эвристический анализ (если включено)
    if state.config.get("enable_auto_routing"):
        scores = {"flash": 0, "qwen": 0}
        for category, patterns in COMPILED_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(last_user_msg):
                    scores[category] += 1

        if scores["flash"] >= 2 and scores["qwen"] == 0:
            return (
                "deepseek/deepseek-v4-flash",
                f"Авто-маршрутизация (flash: {scores['flash']})",
            )
        if scores["qwen"] >= 2 and scores["flash"] == 0:
            return (
                "qwen/qwen3-coder-next",
                f"Авто-маршрутизация (qwen: {scores['qwen']})",
            )

    return requested_model, "Не найдено паттернов"


# ============================================================
# 🚀 FASTAPI ПРИЛОЖЕНИЕ
# ============================================================
app = FastAPI(title="SmartRouter")

# Глобальный HTTP клиент для переиспользования соединений (Connection Pooling)
http_client = httpx.AsyncClient(timeout=180.0)


@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()


@app.get("/health")
async def health():
    return {"status": "ok", "cost": f"${state.stats['total_cost']:.4f}"}


@app.get("/stats")
async def get_stats():
    return state.stats


@app.post("/config")
async def update_config(request: Request):
    try:
        new_config = await request.json()
        await state.save_config(new_config)
        return {"status": "ok", "config": state.config}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    actual_model, reason = smart_route_model(original_model, body)
    body["model"] = actual_model

    if actual_model != original_model:
        state.stats["routed_count"] += 1
        logger.info(f"🔄 Маршрутизация: {original_model} -> {actual_model} ({reason})")
    else:
        state.stats["not_routed_count"] += 1

    target_url = "https://routerai.ru/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {sanitize_ascii(ROUTERAI_KEY)}",
        "Content-Type": "application/json",
    }

    is_stream = body.get("stream", False)

    if is_stream:

        async def stream_generator():
            try:
                async with http_client.stream(
                    "POST", target_url, json=body, headers=headers
                ) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        logger.error(
                            f"Провайдер вернул {resp.status_code}: {error_text.decode('utf-8', errors='ignore')}"
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
                            yield chunk + "\n\n"

                    if not usage_found:
                        log_usage(actual_model, 0, 0)
            except Exception as e:
                logger.error(f"Ошибка streaming: {e}")
                yield f'data: {{"error": "Internal Proxy Error"}}\n\n'

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    else:
        try:
            resp = await http_client.post(target_url, json=body, headers=headers)
            resp.raise_for_status()
            result = resp.json()

            usage = result.get("usage", {})
            log_usage(
                actual_model,
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )

            return JSONResponse(result)
        except httpx.HTTPError as e:
            logger.error(f"HTTP ошибка от провайдера: {e}")
            raise HTTPException(status_code=502, detail="Bad Gateway from Provider")
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            raise HTTPException(status_code=500, detail="Internal Server Error")


if __name__ == "__main__":
    logger.info("🚀 SmartRouter запущен на http://localhost:8765")
    uvicorn.run("router:app", host="127.0.0.1", port=8765, reload=False)
