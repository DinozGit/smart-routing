# 🧠 SmartRouter — Smart Model Router for Zed & Multi-Agent Coding

Прокси-сервер с умной маршрутизацией запросов между AI-моделями для многоагентной разработки в [Zed.dev](https://zed.dev) и других IDE.

## 🎯 Для чего нужен

При использовании multi-agent подхода в Zed каждый агент (Coordinator, Worker, Frontend и т.д.) требует свою модель. SmartRouter автоматически подменяет модель на оптимальную по стоимости и специализации:

| Агент | Модель | Стоимость (1M токенов) |
|-------|--------|------------------------|
| 🧠 Coordinator | `deepseek/deepseek-v4-pro` | $0.50 / $1.50 |
| ⚡ Worker | `deepseek/deepseek-v4-flash` | $0.05 / $0.20 |
| 💻 Frontend | `qwen/qwen3-coder-next` | $0.11 / $0.84 |

**Экономия до 30x** на worker-задачах.

## 🚀 Быстрый старт

### Установка

```bash
git clone https://github.com/DinozGit/smart-routing.git
cd smart-routing
python -m venv venv
source venv/bin/activate  # или venv\Scripts\activate на Windows
pip install -r requirements.txt
```

### Настройка

```bash
# Создай .env файл с ключом RouterAI
echo "ROUTERAI_KEY=sk-ra-твой_ключ" > .env
```

### Запуск

```bash
python router.py
# → http://localhost:8765
```

### Подключение в Zed

В конфигурации Zed (`settings.json` или AI-провайдер):

```json
{
  "language_models": {
    "openai_compatible": {
      "smart-router": {
        "api_url": "http://localhost:8765/v1",
        "available_models": [
          {
            "name": "deepseek/deepseek-v4-pro",
            "display_name": "SmartRouter (Auto)"
          }
        ]
      }
    }
  }
}
```

## 🧠 Как работает умная маршрутизация

```
┌──────────┐    Request     ┌──────────────┐    Routed     ┌──────────┐
│ Zed.dev  │ ──────────────→ │ SmartRouter  │ ────────────→ │ RouterAI │
│ Agents   │ ←────────────── │ (port :8765) │ ←──────────── │   .ru    │
└──────────┘    Response     └──────────────┘    Response    └──────────┘
                                  │
                                  ├── Анализ system prompt (fingerprinting)
                                  ├── Поиск spawn_agent()
                                  ├── Эвристики по паттернам
                                  └── Подмена модели
```

### Приоритет маршрутизации:

1. **Явная модель** — если запрос уже содержит `flash` или `qwen` → пропускаем
2. **System prompt fingerprint** — определяем роль агента по содержимому system-prompt
3. **`spawn_agent()`** — если Coordinator вызывает агента → маппим по `routing.json`
4. **Эвристики** — паттерны кода (pytest → flash, tsx → qwen)
5. **Default** — Coordinator остаётся на Pro

## 📊 API эндпоинты

| Метод | Путь | Назначение |
|-------|------|------------|
| `GET` | `/health` | Health-check + базовая статистика |
| `GET` | `/stats` | Полная статистика сессии |
| `GET` | `/config` | Текущая конфигурация маршрутизации |
| `POST` | `/config` | Обновление конфигурации |
| `POST` | `/v1/chat/completions` | Основной прокси (OpenAI-совместимый) |

## ⚙️ Конфигурация агентов (`routing.json`)

```json
{
  "agent_to_worker_mapping": {
    "database": "deepseek/deepseek-v4-flash",
    "tests": "deepseek/deepseek-v4-flash",
    "bot": "deepseek/deepseek-v4-flash",
    "devops": "deepseek/deepseek-v4-flash",
    "api": "deepseek/deepseek-v4-flash",
    "services": "deepseek/deepseek-v4-flash",
    "frontend": "qwen/qwen3-coder-next",
    "coordinator": "deepseek/deepseek-v4-pro"
  },
  "default_worker": "deepseek/deepseek-v4-flash",
  "enable_auto_routing": true
}
```

## 🏗️ Архитектура проекта

```
smart-routing/
├── router.py              # Основной роутер
├── routing.json           # Конфиг: агент → модель
├── requirements.txt       # Зависимости
├── .env                   # API ключи (НЕ коммитить!)
├── AGENTS.md              # Схема агентов CalorIt
└── README.md              # Этот файл
```

## 🔧 Зависимости

- `fastapi` — веб-фреймворк
- `uvicorn` — ASGI сервер
- `httpx` — асинхронный HTTP клиент
- `python-dotenv` — загрузка .env

## 📈 Мониторинг

```bash
# Текущая статистика
curl http://localhost:8765/stats | jq

# Health
curl http://localhost:8765/health
```

## 🛣️ Roadmap

- [x] Переименование в SmartRouter
- [ ] System prompt fingerprinting (агентная маршрутизация)
- [ ] Virtual model names (Coordinator/Worker/Frontend)
- [ ] Поддержка нескольких провайдеров (RouterAI, OpenRouter, Together)
- [ ] Статическая админ-панель
- [ ] Rate limiting
- [ ] Автообновление цен моделей
- [ ] Тесты (pytest)
- [ ] Docker-образ
- [ ] Smart Router v2 (полноценный agent framework)

## 📝 Лицензия

MIT
