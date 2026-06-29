# 🧠 SmartRouter — Smart Model Router for Zed & Multi-Agent Coding

## 🎯 Для чего нужен

SmartRouter — это легковесный прокси-сервер, который:
1. Принимает запросы в OpenAI-compatible формате от Zed (и других IDE)
2. Определяет **какой агент** отправил запрос (Coordinator, database, frontend, ...)
3. **Автоматически подменяет дорогую модель** (DeepSeek Pro) на дешёвую (DeepSeek Flash / Qwen Coder) для worker-агентов
4. Экономит до **90% затрат на AI-токены**
5. Предоставляет **веб-админку** для управления моделями, агентами и провайдерами

## 🚀 Быстрый старт

### Установка

```bash
cd smart-routing
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### Настройка

Создайте `.env` файл:
```env
ROUTERAI_KEY=sk-ra-your-key-here
```

### Запуск

```bash
python router.py
```

Откроется на `http://localhost:8765` (API) + админка `http://localhost:8765/admin`.

### Подключение в Zed

В `settings.json`:
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

---

## 🧠 Как работает умная маршрутизация

### Приоритет маршрутизации (8 уровней):

| # | Механизм | Описание | Пример |
|---|----------|----------|--------|
| 1 | Явная модель | Если модель уже Flash/Qwen — не трогаем | `flash` в имени |
| 2 | System prompt fingerprint | Ищем "CalorIt Database", "FastAPI endpoints" в system prompt | Coordinator: 20 очков |
| 3 | Тег `[AGENT:name]` | Явный префикс в user-сообщении | `[AGENT:database] Создай...` |
| 4 | Coordinator heuristic | System prompt > 3000 символов → Coordinator | AGENTS.md у Coordinator |
| 5 | User message fingerprint | Файлы, скоупы, responsibilities во всех user-messages | `database/*.py`, `CRUD operations` |
| 6 | `spawn_agent()` pattern | Ловим вызов `spawn_agent("database", ...)` | `spawn_agent("🗄️", ...)` |
| 7 | Code heuristics | `.tsx` → Qwen, `@router.get` → Flash | Фронтенд vs бэкенд |
| 8 | Default fallback | Coordinator mapping или Pro | Когда ничего не сработало |

---

## 📊 API эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/v1/chat/completions` | Основной прокси (OpenAI-compatible) |
| `GET` | `/health` | Health check |
| `GET` | `/stats` | Статистика использования |
| `GET` | `/logs?level=INFO&limit=200` | Логи |
| `GET` | `/admin` | Админ-панель |
| `GET/POST` | `/config` | Конфигурация агентов |
| `GET/POST/DELETE` | `/providers[/{name}]` | Управление провайдерами |

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
    "mobile": "qwen/qwen3-coder-next",
    "design": "deepseek/deepseek-v4-flash",
    "coordinator": "deepseek/deepseek-v4-pro"
  },
  "default_worker": "deepseek/deepseek-v4-flash",
  "enable_auto_routing": true
}
```

Значение `"auto"` включает fingerprinting для агента (модель определяется динамически).

---

## 🏗️ Архитектура проекта

```
smart-routing/
├── router.py          # Основной сервер (FastAPI + маршрутизация)
├── admin.html         # SPA админ-панель (vanilla JS, без бандлера)
├── config.yaml        # Провайдеры, модели, цены, пороги
├── routing.json       # Agent → Model mapping (runtime-конфиг)
├── .env               # API-ключи
├── requirements.txt   # Зависимости
├── AGENTS.md          # Конфигурация агентов CalorIt
└── README.md          # Документация
```

## 🔧 Зависимости

- `fastapi` — веб-фреймворк
- `uvicorn` — ASGI-сервер
- `httpx` — async HTTP клиент (проксирование)
- `python-dotenv` — загрузка .env
- `pyyaml` — парсинг config.yaml

Всего **5 зависимостей**, <50MB RAM в idle.

---

## 📈 Мониторинг

- **Web**: `http://localhost:8765/admin` → вкладка Logs (real-time, filter by level)
- **API**: `GET /stats` → JSON с requests, routed, costs по моделям
- **Health**: `GET /health` → `{"status": "ok", "cost": "$0.1234"}`

---

# 🔬 Code Review — 2026-06-29 (Обновлённый)

## ✅ Сильные стороны

| Аспект | Оценка | Комментарий |
|--------|--------|------------|
| Архитектура | ⭐⭐⭐⭐⭐ | Однофайловый прокси, 5 зависимостей, минимум сложности |
| Приоритет маршрутизации | ⭐⭐⭐⭐⭐ | 8-уровневый каскад с fingerprinting + эвристиками |
| Fingerprinting | ⭐⭐⭐⭐ | 10 агентов, компилированные regex, хорошие веса |
| Streaming (SSE) | ⭐⭐⭐⭐ | Корректная обработка chunk'ов, извлечение usage |
| Admin panel | ⭐⭐⭐⭐ | SPA без бандлера, логи + агенты + провайдеры, работает |
| Кольцевой буфер логов | ⭐⭐⭐⭐⭐ | In-memory, 500 записей, через logging.Handler |
| Graceful shutdown | ⭐⭐⭐⭐ | httpx.AsyncClient корректно закрывается |
| Сохранение .env из админки | ⭐⭐⭐⭐ | Динамическое обновление ключей + `load_dotenv(override=True)` |

## ⚠️ Проблемы (приоритетные)

### 🔴 P0 — Критические

| # | Проблема | Где | Суть |
|---|----------|-----|------|
| **1** | **Sub-agents не маршрутизируются — всегда идут через Pro** | `router.py:480-598` | System prompt sub-agent'а — generic (Zed `SystemPromptTemplate`), не содержит "CalorIt Database" и т.д. `[AGENT:name]` префикс полагается на Coordinator (LLM нестабилен). `fingerprint_user_messages()` паттерны слишком узкие (ищут "database/\*.py" и "SQLAlchemy models", а задача от Coordinator'а — просто "создай миграцию") |
| **2** | **Coordinator имеет жёсткую привязку — не гибко** | `router.py:594-597` | Неизвестные запросы всегда fallback'ятся к `coordinator` в mapping → к Pro. Coordinator нельзя просто сменить на другую модель через админку без изменения fallback-логики |
| **3** | **Admin port из config.yaml не используется** | `router.py:889` + `config.yaml:46-48` | В config.yaml указаны отдельные порты (8765/8766), но uvicorn стартует жёстко на 8765. Всё на одном порту. |

### 🟠 P1 — Высокие

| # | Проблема | Где | Суть |
|---|----------|-----|------|
| **4** | **Модели в админке захардкожены** | `admin.html:863-868` | `availableModels = ["auto", "deepseek/...", "qwen/..."]` — не подгружаются из config.yaml или API провайдера |
| **5** | **Нет автосписка моделей из провайдеров** | `config.yaml:39` | `models_endpoint` задан, но не используется для `GET /models` |
| **6** | **Prices не обновляются динамически** | `router.py:68-76` | PRICES загружается при старте из config.yaml, админка не позволяет менять цены |
| **7** | **Нет fallback-провайдера** | `router.py:114-126` | Если RouterAI упал — нет автоматического переключения на OpenRouter |
| **8** | **Нет тестов** | — | Полное отсутствие pytest. Невозможно гарантировать, что fingerprinting работает после изменений |

### 🟡 P2 — Средние

| # | Проблема | Где | Суть |
|---|----------|-----|------|
| **9** | **Models endpoint не реализован** | `router.py` | Zed требует `GET /v1/models` для списка моделей — SmartRouter не отдаёт |
| **10** | **Нет rate limiting** | — | Нет защиты от перерасхода токенов |
| **11** | **Logger не структурированный** | `router.py:31-36` | Обычный text logger, нет JSON-формата для парсинга |
| **12** | **Нет CORS middleware** | `router.py:604` | Админка работает т.к. на том же origin, но для внешнего доступа нужен |
| **13** | **Нет Docker** | — | Нет Dockerfile для быстрого деплоя |
| **14** | **Config.yaml и routing.json — два источника правды** | — | Модели есть и в config.yaml (с ценами) и в routing.json (mapping). Частичное дублирование. |

### 🟢 P3 — Низкие

| # | Проблема | Где | Суть |
|---|----------|-----|------|
| **15** | `Tuple[str, str]` return type | `router.py:480` | Для современных Python (3.12+) лучше `tuple[str, str]` |
| **16** | Нет Request ID | — | Сложно трассировать запросы через систему |
| **17** | Эмодзи в логах | `router.py:324` | `💰` — не во всех терминалах корректно |
| **18** | Нет graceful shutdown для stats | `router.py:611` | Статистика теряется при перезапуске |

---

# 🔴 КРИТИЧЕСКАЯ ПРОБЛЕМА: Почему sub-agents не маршрутизируются

## Подтверждённая диагностика

Из логов видно: **все** запросы идут через `deepseek/deepseek-v4-pro`:

```
💰 deepseek/deepseek-v4-pro: In 270452 | Out 135 | Cost $0.135429
💰 deepseek/deepseek-v4-pro: In 270798 | Out 544 | Cost $0.136215
```

Ни одной маршрутизации на Flash или Qwen. Ни одного `🔄 Маршрутизация: ... -> deepseek/deepseek-v4-flash`.

## Корень проблемы (3 причины)

### Причина A: System prompt sub-agent'а — generic

Zed при создании sub-agent'а генерирует **новый** system prompt через `SystemPromptTemplate`:
- Нет "CalorIt API Layer"
- Нет "database/*.py"  
- Нет "SQLAlchemy models"
- Просто: "You are the Zed coding agent... project context... date..."

→ `fingerprint_system_prompt()` возвращает `None`

### Причина B: `[AGENT:name]` префикс — зависит от Coordinator (LLM)

AGENTS.md инструктирует Coordinator добавлять `[AGENT:database]` в начало сообщения. Но:
- LLM не всегда следуют инструкциям на 100%
- Если Coordinator пропустит префикс — sub-agent не будет распознан
- Нет fallback на уровне роутера

### Причина C: `fingerprint_user_messages()` — слишком узкие паттерны

Паттерны ищут технические термины: `"database/*.py"` (weight 12), `"alembic/versions?/*.py"` (weight 10).

Но Coordinator даёт задачу естественным языком: *"Создай миграцию для таблицы users"* — в этом сообщении **нет** `"database/*.py"`.

Паттерны рассчитаны на то, что контекст спавна (write scope, files) будет в сообщении, но Zed этого не добавляет.

## ❗ Конкретный trace одного sub-agent запроса

```
1. Coordinator spawn_agent("🗄️ CalorIt Database", "Создай таблицу users")
2. Zed создаёт sub-agent thread:
   System prompt: "You are the Zed coding agent... [generic]"
   User message: "Создай таблицу users"   ← может быть с [AGENT:database], может нет
3. SmartRouter получает запрос с model="deepseek/deepseek-v4-pro"
4. Step 2 (system prompt): generic → None
5. Step 3 (agent tag): если НЕТ [AGENT:database] → None
6. Step 4 (coordinator heuristic): system prompt < 3000 chars → не Coordinator
7. Step 5 (user msg fingerprint): "Создай таблицу users" — НЕТ паттернов → None
8. Step 6 (spawn_agent pattern): в user-сообщении НЕТ "spawn_agent(" → None
9. Step 7 (heuristics): "Создай таблицу users" — нет .tsx, @router, pytest → None
10. Step 8 (fallback): coordinator mapping → deepseek/deepseek-v4-pro ❌
```

---

# 🚀 Quick Win — немедленное исправление sub-agent маршрутизации

## Решение: Sub-agent fallback heuristic

> **Идея**: Если system prompt fingerprinting **не нашёл Coordinator** (и не нашёл конкретного агента), значит это **sub-agent** → автоматически отправляем на `default_worker` (Flash/Qwen).

```python
# Новый шаг 2.5 (между system prompt fingerprint и agent tag):
# «Sub-agent fallback»
# Если system prompt короткий (< порога Coordinator) 
# И fingerprint_system_prompt вернул None (не Coordinator)
# → это sub-agent, используем default_worker
```

Это **trivially просто** и покрывает 100% sub-agent запросов, даже когда Coordinator забывает добавить `[AGENT:name]`.

**Код изменения** (в `smart_route_model()`, после шага 2):

```python
# 2.5 Sub-agent detection (Quick Win)
# Если system prompt не похож на Coordinator (короткий, не CalorIt) — 
# это sub-agent → сразу default_worker
if system_prompt and len(system_prompt) < COORDINATOR_PROMPT_THRESHOLD:
    fingerprint = fingerprint_system_prompt(system_prompt)
    if not fingerprint:
        # Не Coordinator и не конкретный CalorIt agent
        # → sub-agent от Zed → дешёвая модель
        default = state.config.get("default_worker", "deepseek/deepseek-v4-flash")
        return default, "Sub-agent (default_worker)"
```

## 🎯 Второй уровень — улучшение fingerprint_user_messages

Расширить паттерны для естественного языка (не только file scopes):

```python
"database": [
    # Существующие технические паттерны:
    (re.compile(r"database/\*\.py", re.IGNORECASE), 12),
    (re.compile(r"SQLAlchemy\s+models", re.IGNORECASE), 10),
    # НОВЫЕ: естественный язык от Coordinator'а
    (re.compile(r"миграци|migration|alembic", re.IGNORECASE), 8),
    (re.compile(r"таблиц|table|CREATE\s+TABLE", re.IGNORECASE), 7),
    (re.compile(r"CRUD|create.*read.*update.*delete", re.IGNORECASE), 6),
    (re.compile(r"модел[ьи]|model.*SQLAlchemy", re.IGNORECASE), 6),
],
```

Подобные естественно-языковые паттерны для всех 10 агентов.

---

# 🔧 План развития v1.5 → v2.0

```
Week 1 ──────────────────────────────────────────────────────────
🔴 P0  ├── Quick Win: sub-agent fallback heuristic
🔴 P0  ├── Расширение fingerprint_user_messages (естественный язык)
🔴 P0  ├── Дехардкод Coordinator fallback (гибкая смена через админку)
🟠 P1  ├── GET /v1/models (требуется Zed)
🟠 P1  ├── Автосписок моделей из RouterAI + OpenRouter
       └── Тесты на fingerprinting (pytest)

Week 2 ──────────────────────────────────────────────────────────
🟠 P1  ├── Динамические цены моделей через админку
🟠 P1  ├── Разделение портов (8765 router + 8766 admin)
🟠 P1  ├── Fallback-провайдер (RouterAI → OpenRouter при ошибке)
🟡 P2  ├── Rate limiting
       └── Структурированные JSON-логи

Week 3-4 ────────────────────────────────────────────────────────
🟡 P2  ├── CORS middleware
🟡 P2  ├── Request ID (X-Request-ID)
🟡 P2  ├── Dockerfile + docker-compose
🟢 P3  ├── Сохранение stats на диск
       └── Graceful shutdown с flush stats

Month 2+ ────────────────────────────────────────────────────────
🟢 P3  ├── Smart Router v2 — Agent Framework
🟢 P3  ├── Skill Prompting Engine (YAML-driven)
🟢 P3  ├── SQLite storage (persistent config/stats/skills)
🟢 P3  ├── Интеграция VS Code / JetBrains
       └── CLI (`sr chat "..."`)
```

## Состояние (чек-лист)

- [x] Переименование в SmartRouter
- [x] System prompt fingerprinting (Coordinator detection)
- [x] `[AGENT:name]` префикс в AGENTS.md
- [x] User message fingerprinting
- [x] Админ-панель: логи + агенты + провайдеры
- [x] Сохранение провайдеров + API-ключей из админки
- [x] config.yaml + routing.json
- [ ] **🔴 P0: Sub-agent fallback heuristic**
- [ ] **🔴 P0: fingerprint_user_messages — естественный язык**
- [ ] **🔴 P0: Дехардкод Coordinator fallback**
- [ ] `GET /v1/models`
- [ ] Автосписок моделей провайдеров
- [ ] Динамические цены в админке
- [ ] Разделение портов router/admin
- [ ] Provider failover
- [ ] Тесты (pytest)
- [ ] Rate limiting
- [ ] JSON-логи
- [ ] Docker
- [ ] Smart Router v2 (Agent Framework + Skills)

---

# 📋 План 1: Статическая админ-панель (расширенный)

## 1.1 Управление моделями для всех типов агентов

> **Статус:** ✅ Базово реализовано (вкладка Agents), но требует доработок

Текущее:
- Coordinator: select (вкладка Agents)
- Worker (default): select
- Frontend: select
- Agent mapping table: для остальных 8 агентов

Что нужно доделать:
- [ ] Coordinator — **гибкое управление** (не хардкод), см. п. 1.6
- [ ] Подгрузка списка моделей из `/models` API провайдеров (сейчас захардкожено)
- [ ] Отображение цен моделей в dropdown
- [ ] Валидация: нельзя назначить coordinator'у Flash (предупреждение)
- [ ] Hot-reload конфига без перезапуска роутера

## 1.2 Управление провайдерами

> **Статус:** ✅ Реализовано (вкладка Providers)

Поля провайдера (текущие):
- Variable name (slug для кода)
- Display name (человеческое)
- Base URL
- API Key env var + value
- Models endpoint
- Set as default (toggle)

Дополнительные поля (предлагаю):
| Поле | Тип | Описание |
|------|-----|----------|
| `rate_limit_rpm` | int | Лимит запросов в минуту (rate limiting) |
| `rate_limit_tpm` | int | Лимит токенов в минуту |
| `priority` | int | Приоритет при failover (1 = первичный) |
| `headers_extra` | object | Кастомные заголовки (напр. `X-Title: MyApp`) |
| `timeout_seconds` | int | Таймаут запроса (default: 180) |
| `max_retries` | int | Количество ретраев при 5xx |
| `enabled` | bool | Вкл/выкл провайдера без удаления |

## 1.3 Порты

> **Статус:** 🟠 Заданы в config.yaml, но не используются в коде

```yaml
# config.yaml (уже есть)
server:
  router_port: 8765
  admin_port: 8766
  admin_host: "127.0.0.1"
```

Нужно реализовать:
- [ ] Чтение портов из config.yaml (или `.env`)
- [ ] Возможность запуска на одном порту (текущий режим) или на двух
- [ ] Admin host binding (только localhost vs 0.0.0.0)

## 1.4 Вынос параметров из хардкода

> **Статус:** 🟠 Частично (config.yaml + routing.json созданы, но не всё вынесено)

| Параметр | Где сейчас | Куда вынести |
|----------|-----------|-------------|
| `MAX_LOG_ENTRIES` | `router.py:41` + `config.yaml:13` | ✅ Уже в config.yaml, но хардкод 500 в router.py:41 дублирует |
| `availableModels` | `admin.html:863-868` | ❌ Хардкод в JS. Нужно: `GET /models` API |
| `default_worker` | `routing.json` | ✅ В routing.json |
| `HEURISTIC_THRESHOLD` | `router.py:83` + `config.yaml:42` | ✅ В config.yaml |
| `COORDINATOR_PROMPT_THRESHOLD` | `router.py:82` + `config.yaml:41` | ✅ В config.yaml |
| Цены моделей | `config.yaml:14-28` | ✅ В config.yaml (но не редактируются через админку) |
| `uvicorn.run(... port=8765)` | `router.py:889` | ❌ Хардкод |

## 1.5 Авто-список моделей из провайдеров

> **Статус:** ❌ Не реализовано

API для получения списка моделей:
- `GET https://routerai.ru/api/v1/models` — список моделей RouterAI
- `GET https://openrouter.ai/api/v1/models` — список моделей OpenRouter

Что нужно:
1. API эндпоинт `GET /models` — возвращает агрегированный список из всех провайдеров
2. Фильтр: только модели для кодинга (code, chat, instruct)
3. Авто-цены: если провайдер возвращает pricing — подхватываем
4. Кнопка «Refresh models» в админке
5. Кэширование списка (TTL 1 час)

Интеграция в админку:
- Вкладка Models или dropdown в Agents с подгрузкой из `/models`
- Отображение: имя модели | провайдер | цена input/output | роль

## 1.6 Гибкое управление Coordinator (дехардкод)

> **Статус:** 🔴 Критическая проблема P0

**Проблема:** Сейчас Coordinator — это **особый** агент в коде:
1. `smart_route_model()` на шаге 4 проверяет размер system prompt (>3000) → Coordinator
2. На шаге 8 (fallback) всегда проверяет `mapping["coordinator"]` для неизвестных запросов
3. Нельзя через админку переназначить Coordinator на Flash (логика завязана на Pro)

**Решение:** Coordinator должен быть **таким же агентом**, как и все остальные:
- Определяется через fingerprinting (как сейчас)
- Его модель (`coordinator` → Pro) — просто запись в `agent_to_worker_mapping`
- Fallback для неизвестных запросов → `default_worker` (НЕ coordinator!)
- Админка позволяет менять модель Coordinator'а как и любого другого агента

**Изменения в коде:**
1. Убрать шаг 4 (Coordinator heuristic) — fingerprinting уже ловит Coordinator
2. Шаг 8: fallback → `default_worker`, а не `mapping["coordinator"]`
3. Админка: Coordinator в общем списке агентов (не отдельный select)

## 1.7 GET /v1/models (совместимость с Zed)

> **Статус:** ❌ Не реализовано

Zed при старте делает `GET /v1/models` для получения списка доступных моделей. SmartRouter должен отдавать:
```json
{
  "object": "list",
  "data": [
    {"id": "deepseek/deepseek-v4-pro", "object": "model", ...},
    {"id": "deepseek/deepseek-v4-flash", "object": "model", ...},
    ...
  ]
}
```

Без этого эндпоинта Zed может показывать ошибки при подключении (хотя чат работает).

---

## 🛣️ Roadmap

Полный план развития вынесен в отдельный файл: **[ROADMAP.md](ROADMAP.md)**

### Краткий срез приоритетов:

| Приоритет | Что | Статус |
|-----------|-----|--------|
| 🔴 P0 | Sub-agent fallback + fingerprint (естеств. язык) | ⏳ В плане |
| 🔴 P0 | Рефакторинг на 3 роли (Coordinator / Worker / Worker Img) | ⏳ В плане |
| 🔴 P0 | Fallback chain между ролями | ⏳ В плане |
| 🟠 P1 | Fine tuning ролей через админку | ⏳ В плане |
| 🟠 P1 | Provider failover (RouterAI → OpenRouter) | ⏳ В плане |
| 🟡 P2 | Тесты, Docker, JSON-логи | ⏳ В плане |
| 🟢 P3 | Smart Router v2 — Agent Framework + Skills | ⏳ В плане |

---

## 📝 Лицензия

MIT
