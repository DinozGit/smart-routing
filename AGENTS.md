# SmartRouter — Multi-Agent Configuration

> Конфигурация мультиагентной работы **в этом репозитории** и протокол маршрутизации,
> который понимает SmartRouter.

## 🧠 Architecture

```
Zed (IDE) или любой OpenAI-клиент
  └── SmartRouter (:8765)  — FastAPI-прокси
        │   1. Читает тег [AGENT:name] из user-сообщения
        │   2. Тег → агент → роль (coordinator / worker_default / worker_img)
        │   3. Роль → модель в формате "provider::model_id"
        │   4. Провайдера модели определяет ключ, а не глобальный переключатель
        │   5. Проксирует на base_url[provider] с ключом[provider]
        └── Единый источник правды:
              config.yaml   → провайдеры, роли, валюты, override'ы цен
              routing.json  → роли → модели, agent → worker mapping
              models_cache.json → каталог моделей по провайдерам (генерируется)
```

**Контракт реализации:** [`docs/PROVIDER_CONTRACT.md`](docs/PROVIDER_CONTRACT.md) —
форматы каталога, ключи `provider::model_id`, валюты, API. Читай его перед правками.

## 🎯 Правила делегирования

**НИКОГДА не выполняй задачи из чужого write scope сам!**
Если задача относится к зоне ответственности другого агента — **всегда** спавни его.
Это экономит токены: у Coordinator'а дорогая модель, у worker'ов — дешёвая.

## 🏷️ ПРАВИЛО МАРШРУТИЗАЦИИ ДЛЯ SMART ROUTER

**Каждое сообщение sub-agent'у должно начинаться с `[AGENT:agent_name]`.**

Допустимые имена (они же — ключи в `routing.json: agent_to_worker_mapping`):

| Агент | Роль в SmartRouter | Что делает |
|-------|--------------------|------------|
| `coordinator` | `coordinator` | Декомпозиция, синтез, code-review |
| `database` | `worker_default` | Схема данных, миграции, модели |
| `tests` | `worker_default` | Pytest, тестовая инфраструктура |
| `api` | `worker_default` | FastAPI-эндпоинты, схемы, middleware |
| `services` | `worker_default` | Бизнес-логика, интеграции, фоновые задачи |
| `bot` | `worker_default` | Telegram-бот, хендлеры, FSM |
| `devops` | `worker_default` | Docker, CI/CD, конфиги, деплой |
| `frontend` | `worker_img` | Веб-интерфейс (Next.js/React) |
| `mobile` | `worker_img` | Мобильные приложения (Flutter/Dart) |
| `design` | `worker_img` | Дизайн-система, токены, макеты |

Роль назначается **по тегу**, а не по догадкам. SmartRouter сам подставит модель роли
и сам выберет провайдера — вручную модель указывать не нужно.

```python
spawn_agent("🔧 API", "[AGENT:api] Добавь эндпоинт POST /models/sync")
```

> ⚠️ Если тег не проставлен, запрос уйдёт в `coordinator` — это дорогая модель.
> Проверь, что тег стоит **первым** в сообщении.

## 🤖 Agent Roles (write scope в этом репозитории)

| Агент | Write scope | Ответственность |
|-------|-------------|------------------|
| **api** | `router.py` | FastAPI-эндпоинты, маршрутизация, каталог моделей, учёт стоимости |
| **frontend** | `admin.html` | Веб-админка (vanilla JS, без бандлера) |
| **tests** | `tests/` | Pytest, unit & integration, регресс-тесты |
| **devops** | `config.yaml`, `Dockerfile`, `docker-compose*.yml`, `nginx*.conf`, `.github/` | Конфигурация, Docker, CI/CD, деплой |
| **coordinator** | `docs/`, `README.md`, `ROADMAP.md`, `MULTIPROVIDER_PLAN.md` | Декомпозиция, ревью, документация, координация |

**Никто не трогает чужие файлы.** Если нужен чужой change — опиши его в отчёте, но не делай.

### Особенности этого репозитория

- **Python-проект, один модуль** `router.py` (~1900 строк) + SPA `admin.html` (~2500 строк).
- **Никаких внешних зависимостей кроме 5**: `fastapi`, `uvicorn`, `httpx`, `python-dotenv`, `pyyaml`.
- **Веб-фреймворка во фронтенде нет** — только vanilla JS, без CDN и без сборки.
- **Провайдер-агностичность обязательна:** никаких хардкодов `routerai` / `ROUTERAI_KEY` /
  `https://routerai.ru/...` в коде. Всё — из `config.yaml`.
- **Ключи моделей составные:** `"provider::model_id"`. Провайдеру уходит **чистый** `model_id`.

## 🔄 Workflow

### Parallel execution
```
Coordinator → spawn_agent(Agent A)  ─┐
             → spawn_agent(Agent B)  ─┤  (непересекающиеся write scope)
             → spawn_agent(Agent C)  ─┘ → wait all → review → merge
```

> Перед параллельным запуском **зафиксируй контракт** (форматы JSON, имена полей,
> сигнатуры) — иначе агенты разъедутся. Для этого в проекте есть
> `docs/PROVIDER_CONTRACT.md`.

### Full feature cycle
```
1. 💻 Локальная разработка
   ├── Coordinator: декомпозиция → параллельный spawn агентов
   ├── Агенты: код + тесты в своём write scope
   └── Coordinator: code-review всех изменений

2. 🧪 Тестирование (обязательно)
   └── venv\Scripts\python.exe -m pytest tests/ -q     → все тесты зелёные

3. 📦 Коммит + Пуш
   ├── GIT_EDITOR=true git add -A
   ├── GIT_EDITOR=true git commit -m "..."
   └── git push origin main

4. 🤝 Ручное тестирование
   └── Coordinator даёт пользователю конкретные шаги для проверки
```

> ⚠️ Ветка — **`main`** (не `master`).
> ⚠️ `models_cache.json` — **генерируемый** кеш, он в `.gitignore`. Не коммить его.
> ⚠️ `routing.json` — **runtime-конфиг**, коммитится. После ручной проверки
> смотри `git diff routing.json`, чтобы не закоммитить случайный эксперимент.

## 🔄 SDLC — Полный цикл разработки

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. 💻 Dev — локальная разработка                                     │
│    ├── Coordinator: декомпозиция задачи на непересекающиеся скоупы  │
│    ├── Параллельный spawn агентов (до 3 одновременно)                │
│    ├── Каждый агент: код + свои тесты                                │
│    └── Coordinator: code review всех изменений                       │
│                                                                     │
│ 2. 🧪 Тестирование (обязательно)                                     │
│    └── venv\Scripts\python.exe -m pytest tests/ -q                   │
│        Все тесты должны быть ЗЕЛЁНЫМИ перед пушем                    │
│                                                                     │
│ 3. 📦 Коммит + Пуш в GitHub                                          │
│    ├── GIT_EDITOR=true git add -A                                    │
│    ├── GIT_EDITOR=true git commit -m "..."                           │
│    └── git push origin main                                          │
│                                                                     │
│ 4. 🤝 Ручное тестирование                                            │
│    └── Coordinator готовит сценарии: админка + API                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 🧪 Тестирование

| Платформа | Как тестируем | Где |
|-----------|---------------|-----|
| **Backend (Python)** | `venv\Scripts\python.exe -m pytest tests/ -q` | Windows Dev |

### Структура тестов

```
tests/
├── conftest.py      # фикстуры: изоляция конфигов, HTTP-клиент
├── phase0/          # базовые: health, proxy, config, logs
├── phase1/          # дехардкод Coordinator fallback
├── phase2/          # роли, fallback, порты, модели
├── phase3/          # fine tuning
├── phase4/          # transport hardening + атомарная запись
└── phase5/          # мультипровайдерность ← текущая фаза
```

**Новые фичи → `tests/phaseN/`** — отдельная директория на фазу, свой `conftest`-контекст.

### Частые грабли

- **Windows + venv:** если после `venv\Scripts\activate` вызывается `python` не из `venv\Scripts\`
  — будет конфликт с `AppData\...\site-packages`. Запускай `.\venv\Scripts\python.exe -m pytest` напрямую.
- **Тесты не должны ходить в сеть.** Мокай HTTP-клиент:
  `patch.object(router.http_client, "post", mock)` — см. `tests/phase3/test_tuning_proxy.py`.
- **Фикстуры изолируют состояние.** `state.available_models`, `state.models_by_provider`,
  `state.provider_last_sync`, `state.stats` — сбрасывай и восстанавливай, иначе тесты текут друг в друга.
- **`routing.json` в тестах не трогается** — `conftest.py` подменяет `state.config_file` на tmp.
- **`fingerprinting` удалён** — кода `fingerprint_*`/`AGENT_FINGERPRINTS` в проекте больше нет.
  Не resurrect'и его: роутинг идёт по тегу `[AGENT:name]`.

## 🐛 Отладка

```bash
# Логи роутера
curl -s "http://127.0.0.1:8765/logs?level=INFO&limit=200"

# Каталог моделей по провайдерам
curl -s http://127.0.0.1:8765/models/available

# Синк конкретного провайдера
curl -s -X POST http://127.0.0.1:8765/models/sync \
     -H "Content-Type: application/json" -d '{"provider":"openrouter"}'

# Статистика (цены по валютам)
curl -s http://127.0.0.1:8765/stats
```

---

*Конфигурация SmartRouter. Формат ключей моделей и семантика валют —
в [`docs/PROVIDER_CONTRACT.md`](docs/PROVIDER_CONTRACT.md).*
