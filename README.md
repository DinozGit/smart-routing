# 🧠 SmartRouter — Smart Model Router for Zed & Multi-Agent Coding

## 🎯 Для чего нужен

SmartRouter — это легковесный прокси-сервер, который:
1. Принимает запросы в OpenAI-compatible формате от Zed (и других IDE)
2. Определяет **какой агент** отправил запрос (Coordinator, database, frontend, ...)
3. **Автоматически подменяет дорогую модель** (DeepSeek Pro) на дешёвую (DeepSeek Flash / Qwen Coder) для worker-агентов
4. Экономит до **90% затрат на AI-токены**
5. Предоставляет **веб-админку** для управления моделями, агентами и провайдерами

## 📋 Что нового

### Спринт 2026-11 (2) — Мультипровайдерность: Phase 1 + Phase 2

- 🌍 **Каталог моделей по провайдерам.** `models_cache.json` переведён на формат v2:
  `{"version": 2, "providers": {"routerai": {"models": {...}, "last_sync": ...}}}`.
  Ключ модели теперь **составной** — `"provider::model_id"` (например `openrouter::deepseek/deepseek-v4-pro`).
  Старый кеш v1 мигрируется автоматически при старте.
- 🧹 **Фильтрация моделей.** В каталог попадают только text-выходящие модели с тарификацией
  за токены. RouterAI: 582 → **351**, OpenRouter: 415 → **399**, Ollama: 12 → **10**
  (эмбеддинги отброшены). Модели помечаются `supports_images` для роли `worker_img`.
- 💱 **Валюты.** Цена хранится вместе с валютой (`RUB` / `USD` / `NONE`).
  RouterAI отдаёт цены **числами в рублях**, OpenRouter — **строками в долларах** —
  единый pricing-адаптер различает оба режима (`auto` / `per_token_rub` / `per_token_usd` / `free`).
  В статистике: `by_currency` (в native-валюте), `total_cost` (в базовой валюте) и `usd_equivalent`.
- 🎯 **Провайдер определяется моделью.** `provider::model` — единица маршрутизации:
  URL, ключ и SSL-клиент берутся у провайдера **модели**, а не из глобального переключателя.
  Роли назначаются моделями любого провайдера — **без перезапуска роутера**.
- 🔌 **Провайдеры из коробки:** `routerai` (₽), `openrouter` ($), `ollama` (локальный, бесплатно, без API-ключа).
  Любой OpenAI-совместимый провайдер добавляется через админку.
- 🧹 **Удалён мёртвый код** (~317 строк): `fingerprint_system_prompt`, `fingerprint_user_messages`,
  `AGENT_FINGERPRINTS`, `AGENT_SCOPE_PATTERNS` и 4 неиспользуемых порога — fingerprinting
  отключён ещё в 2026-07, но код оставался ловушкой для следующего разработчика.
- 🐛 **Исправлено 4 бага**, найденных при ручном прогоне: цена бралась у чужого провайдера
  (ошибка до 1136×), `total_cost` суммировал рубли и доллары без пересчёта,
  `POST /config` затирал модели соседних ролей, двойной префикс в `GET /v1/models`.
- 🧪 **243/243 теста зелёные** (`venv\Scripts\python.exe -m pytest tests/ -q`), из них 16 регресс-тестов
  на найденные баги (`tests/phase5/test_regressions.py`).

### Спринт 2026-11 — Transport hardening + Phase 0 (атомарная запись)

- 🔌 **66204a2 — Ретраи и per-provider SSL.** Инцидент 18:20: TLS-сбой провайдера (`CERTIFICATE_VERIFY_FAILED: self-signed certificate`) ронял весь streaming-ответ, а в лог уходило безобщее `Internal Proxy Error`. Диагностика: сертификат `routerai.ru` валиден (Let's Encrypt, до 17.11.2026), 10 подряд TLS-соединений дали один fingerprint → сбой был **транзиентным на стороне провайдера**, не ошибкой конфига. Исправление: connect-таймаут 20 с (раньше висящий handshake держал слот 180 с), 3 повтора с экспоненциальной задержкой (0.7 / 1.4 / 2.8 с) на `ConnectError` / `ConnectTimeout` / `ReadTimeout` — в streaming повтор только пока клиент не получил ни одного байта, реальная причина ошибки в SSE вместо `Internal Proxy Error`, per-provider настройки `verify_ssl` / `ca_bundle` для корпоративных CA.
- 🔐 **04d1fd8 — Атомарная запись конфигов (P0).** `routing.json` / `config.yaml` / `.env` писались напрямую — прерванная запись оставляла файл битым, и при следующем старте роутер **молча затирал настройки ролей** дефолтами. Теперь: запись через `*.tmp` + `fsync` + `os.replace()`, битый конфиг сохраняется как `*.broken` и не перезаписывается.
- 📚 **ec52f46 — `MULTIPROVIDER_PLAN.md`**: план перехода на мультипровайдерный роутинг (RouterAI / OpenRouter / Ollama, ключи `provider::model_id`).
- 🧪 **198/198 тестов зелёные** на момент этого спринта (`venv\Scripts\python.exe -m pytest tests/ -q`).
  → После спринта мультипровайдерности — **243 теста**.

### Спринт 2026-07 — Code review & hotfix

- 🔧 **f8edbb0** — Исправлен критический баг запуска: `@app.on_event("shutdown")` заменён на современный `@asynccontextmanager lifespan`. Без фикса SmartRouter падал с `TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'` (uvicorn ≥ 0.30 / FastAPI ≥ 0.110).
- ✅ **Code review P1–P3** проведён: задокументированы «мёртвый» fingerprint, отсутствие rate limiting, persistent stats, CORS, Docker, неограниченный рост `models_cache.json`.
- ❌ **ШАГ 2.5 (sub-agent fallback heuristic) — отклонён.** Coordinator в Zed — это главный thread чата, а не роль роутера. Существующая связка `[AGENT:name]` → `agent_to_worker_mapping` работает корректно, а добавление fallback'а по длине system prompt ломало бы короткие Coordinator-промпты (например, через CLI). Подробнее — в логе спринта.
- 🐛 **Coordinator minimax/minimax-m3** падал с `In 0/Out 0` → вся маршрутизация через `Unknown → coordinator` шла на сломанную модель. Сейчас явная модель `minimax/*` не трогается (шаг 1).
- 🧪 **172/172 теста зелёные** на master (c5a7d1a..f8edbb0).

---

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

> ⚠️ **Важно про venv на Windows.** В системе часто установлено несколько Python одновременно (например, `C:\Users\<user>\AppData\Roaming\Python\Python314` + системный `python.exe`). Если после `venv\Scripts\activate` вызывается `python -m pytest` не из `venv\Scripts\`, идёт конфликт с `AppData\…\site-packages` (другой `pip install` граф).
>
> **Проверка:**
> ```bash
> where python       # первый путь должен быть smart-routing\venv\Scripts\python.exe
> python -c "import sys; print(sys.executable)"
> ```
> Если путь не из `venv\` — закройте терминал, откройте новый **с уже активированным venv** (`venv\Scripts\activate` в начале сессии), либо запускайте напрямую `.\venv\Scripts\python.exe -m pytest tests/`.

### Настройка

Создайте `.env` файл:
```env
ROUTERAI_KEY=sk-ra-your-key-here
```

### Запуск

```bash
python router.py
```

> 🔌 **Single-port режим:** в текущей версии `single_port: true` — API и админка слушают **один и тот же порт `8765`**. Параметры `router_port` / `admin_port` в `config.yaml` зарезервированы под будущий split-режим и сейчас игнорируются.

Откроется на `http://localhost:8765` (API + `http://localhost:8765/admin` — админка).

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

### Приоритет маршрутизации (фактически 3 шага)

| # | Механизм | Описание | Пример |
|---|----------|----------|--------|
| 1 | Явная модель | Если модель уже Flash/Qwen — не меняем, но **резолвим провайдера по каталогу** | `flash` в имени |
| 2 | Тег `[AGENT:name]` | Явный префикс в user-сообщении → `agent_to_worker_mapping` | `[AGENT:database] Создай...` |
| 3 | Default fallback | Ничего не распознано → модель роли `coordinator` | `Unknown → coordinator default` |

Результат любого шага — **составная спецификация** `"provider::model_id"`.
Провайдер из неё определяет URL, ключ и SSL-клиент; провайдеру уходит **чистый** `model_id` без префикса.

> 📌 **Fingerprinting отключён** (commit `a711cd6`, `db9365a`) — и **удалён из кода** (2026-11).
> Таблица «8 уровней» из ранних ревизий больше не соответствует коду: `fingerprint_system_prompt()`,
> `fingerprint_user_messages()`, `AGENT_FINGERPRINTS` и `AGENT_SCOPE_PATTERNS` удалены целиком
> (~317 строк), вместе с тестами `tests/phase1/test_natural_lang.py`.
> Причина: Coordinator в Zed — это главный thread чата, он сам ставит задачи субагентам через
> `spawn_agent()` с тегом `[AGENT:name]`, и эвристика ломала бы короткие Coordinator-промпты.
> Деталь — в `ROADMAP.md` (шаги 1.1 / 1.2 отклонены).

---

## 📊 API эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/v1/chat/completions` | Основной прокси (OpenAI-compatible) |
| `GET` | `/v1/models` | Список моделей (OpenAI-compatible) |
| `GET` | `/health` | Health check |
| `GET` | `/stats` | Статистика использования |
| `GET` | `/logs?level=INFO&limit=200` | Логи |
| `GET` | `/admin` | Админ-панель |
| `GET/POST` | `/config` | Конфигурация агентов |
| `GET/POST/DELETE` | `/providers[/{name}]` | Управление провайдерами |
| `GET` | `/models/available[?refresh=true]` | Каталог моделей: сгруппирован по провайдерам + плоский список |
| `POST` | `/models/sync` | Синхронизация каталога. Тело `{"provider": "..."}` — опционально (без него — все провайдеры) |

### Настройки транспорта (env)

| Переменная | По умолчанию | Смысл |
|------------|--------------|-------|
| `ROUTER_REQUEST_TIMEOUT` | `180` | Общий таймаут запроса (с) |
| `ROUTER_CONNECT_TIMEOUT` | `20` | Таймаут установления соединения / TLS-handshake (с) |
| `ROUTER_RETRY_ATTEMPTS` | `3` | Повторы при сетевых ошибках |
| `ROUTER_RETRY_BACKOFF` | `0.7` | Базовая задержка ретрая (с), далее ×2 |

### SSL для провайдера (вкладка Providers в админке)

| Поле | Смысл |
|------|-------|
| `verify_ssl` | Проверять TLS-сертификат (по умолчанию `true`) |
| `ca_bundle` | Путь к своему CA-файлу — для корпоративных шлюзов и self-signed сертификатов |

> ⚠️ Глобально отключать проверку SSL не нужно: `verify_ssl: false` и `ca_bundle` задаются **для конкретного провайдера**, остальные продолжают работать с системным CA.

---

## 🌍 Провайдеры и валюты (`config.yaml`)

### Провайдеры

```yaml
providers:
  routerai:
    display_name: RouterAI
    base_url: https://routerai.ru/api/v1/chat/completions
    models_endpoint: https://routerai.ru/api/v1/models
    api_key_env: ROUTERAI_KEY
    requires_api_key: true
    pricing_mode: auto          # auto | per_token_rub | per_token_usd | free
    default: true               # ← fallback для голых model_id
    verify_ssl: true
    ca_bundle: ""
    extra_headers: {}
  openrouter:
    display_name: OpenRouter
    base_url: https://openrouter.ai/api/v1/chat/completions
    models_endpoint: https://openrouter.ai/api/v1/models
    api_key_env: OPENROUTER_API_KEY
    requires_api_key: true
    pricing_mode: auto
    default: false
    extra_headers:
      HTTP-Referer: https://github.com/smart-routing/smart-router
      X-Title: SmartRouter
  ollama:
    display_name: Ollama (local)
    base_url: http://localhost:11434/v1/chat/completions
    models_endpoint: http://localhost:11434/api/tags
    api_key_env: ""
    requires_api_key: false      # ← локальный провайдер, ключ не нужен
    pricing_mode: free
    default: false
```

| Поле | Смысл |
|------|-------|
| `requires_api_key` | `false` → запрос уходит **без** `Authorization` (Ollama) |
| `pricing_mode` | `auto` — валюта определяется по типу цены (строка → USD, число → RUB); остальные — принудительно |
| `default` | Провайдер по умолчанию. Используется **только** как fallback для голых model_id и моделей вне каталога. Это **не** глобальный переключатель |
| `extra_headers` | Доп. заголовки запроса (для OpenRouter — `HTTP-Referer`, `X-Title`) |

Любой OpenAI-совместимый провайдер добавляется через админку (вкладка **Providers**)
или правкой `config.yaml`. Ключ провайдера хранится в `.env` по имени `api_key_env`.

### Валюты

```yaml
currency:
  base: RUB                    # валюта, в которой считается stats["total_cost"]
  usd_rate: 90.0               # 1 USD = 90 ₽ (ручное значение, авто-курса нет)
  rates:
    RUB: 1.0
    USD: 0.011111              # = 1/90
```

- `stats["by_currency"]` — суммы **в native-валюте** каждого провайдера;
- `stats["total_cost"]` — сумма **в базовой валюте** (пересчёт по `rates`);
- `stats["usd_equivalent"]` — эквивалент в долларах по `usd_rate`.

### Ручные override'ы цен

Секция `models:` — ручное override цен (выигрывает у каталога API).
Ключ может быть **глобальным** или **с привязкой к провайдеру**:

```yaml
models:
  routerai::deepseek/deepseek-v4-flash:    # только для RouterAI
    input_price: 9.157                     # ₽ за 1M токенов
    output_price: 18.3141
    currency: RUB
  # openrouter::deepseek/deepseek-v4-pro:  # только для OpenRouter (пример)
  #   input_price: 1.6                     # $ за 1M токенов
  #   output_price: 4.8
  #   currency: USD
```

> ⚠️ Важно: модель может существовать **у нескольких провайдеров** с разными ценами
> и валютами (например `z-ai/glm-5.2`: 8.17 ₽ у RouterAI и 0.006 $ у OpenRouter).
> Поэтому override'ы лучше привязывать к провайдеру.

## ⚙️ Конфигурация агентов (`routing.json`)

```json
{
  "role_models": {
    "coordinator": "routerai::minimax/minimax-m3",
    "worker_default": "ollama::qwen3.5:9b",
    "worker_img": "openrouter::z-ai/glm-5.2"
  },
  "agent_to_worker_mapping": {
    "database": "auto",
    "tests": "auto",
    "bot": "auto",
    "devops": "auto",
    "api": "auto",
    "services": "auto",
    "frontend": "auto",
    "mobile": "auto",
    "design": "auto"
  },
  "role_fallbacks": {
    "worker_default": "routerai::deepseek/deepseek-v4-flash"
  },
  "default_worker": "routerai::deepseek/deepseek-v4-flash",
  "enable_auto_routing": true
}
```

Значение модели — **составная спецификация** `"provider::model_id"`.
Значение `"auto"` означает: модель определяется по роли агента (динамически).

> 💡 `POST /config` **мержит** словари: чтобы сменить модель только у одной роли,
> достаточно `{"role_models": {"worker_default": "ollama::qwen3.5:9b"}}` —
> модели других ролей сохранятся.

---

## 🏗️ Архитектура проекта

```
smart-routing/
├── router.py          # Основной сервер (FastAPI + маршрутизация)
├── admin.html         # SPA админ-панель (vanilla JS, без бандлера)
├── config.yaml        # Провайдеры, роли, валюты, override'ы цен
├── routing.json       # Роли → модели, agent → worker mapping (runtime-конфиг)
├── models_cache.json  # Кеш каталога моделей v2 (генерируется, gitignored)
├── MULTIPROVIDER_PLAN.md # План мультипровайдерной переработки
├── docs/
│   └── PROVIDER_CONTRACT.md # Контракт каталога/ключей/валют (источник правды)
├── .env               # API-ключи
├── requirements.txt   # Зависимости
├── AGENTS.md          # Протокол мультиагентной работы и маршрутизации
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
- **API**: `GET /stats` → JSON с requests, routed, costs по моделям, `by_currency`, `usd_equivalent`
- **Health**: `GET /health` → `{"status": "ok", "cost": "0.1234", "currency": "RUB"}`

---

# 🔬 Code Review — 2026-06-29, пересмотрен 2026-11

## ✅ Сильные стороны

| Аспект | Оценка | Комментарий |
|--------|--------|------------|
| Архитектура | ⭐⭐⭐⭐⭐ | Однофайловый прокси, 5 зависимостей, минимум сложности |
| Приоритет маршрутизации | ⭐⭐⭐⭐⭐ | 3 шага: явная модель → `[AGENT:name]` → coordinator default |
| Fingerprinting | ⭐⭐⭐ | Код оставлен, но **не вызывается** — шаги 1.1/1.2/2.5 отклонены (см. ниже) |
| Streaming (SSE) | ⭐⭐⭐⭐ | Корректная обработка chunk'ов, извлечение usage |
| Admin panel | ⭐⭐⭐⭐ | SPA без бандлера, логи + агенты + провайдеры, работает |
| Кольцевой буфер логов | ⭐⭐⭐⭐⭐ | In-memory, 500 записей, через logging.Handler |
| Graceful shutdown | ⭐⭐⭐⭐ | httpx.AsyncClient корректно закрывается |
| Сохранение .env из админки | ⭐⭐⭐⭐ | Динамическое обновление ключей + `load_dotenv(override=True)` |

## ⚠️ Проблемы (приоритетные)

### 🔴 P0 — Критические

| # | Проблема | Где | Статус |
|---|----------|-----|--------|
| ~~**1**~~ | ~~Sub-agents не маршрутизируются — всегда идут через Pro~~ | `router.py` | ✅ **Решено** — связка `spawn_agent()` + тег `[AGENT:name]` в `AGENTS.md` работает: Coordinator ставит задачу агенту, агент уходит на свою модель. Fingerprinting не нужен и был отключён (`a711cd6`, `db9365a`) |
| ~~**2**~~ | ~~Coordinator имеет жёсткую привязку~~ | `router.py` | ✅ **Решено** — модель Coordinator задаётся в `routing.json:role_models.coordinator` и меняется из админки **на лету, без перезапуска** (commit `b8b0a63` и ранее) |
| ~~**3**~~ | ~~Admin port из config.yaml не используется~~ | `config.yaml` | ⚠️ **Осознанно** — `single_port: true`, API + админка на одном порту `8765`. Разделение портов — в бэклоге P2 |

### 🟠 P1 — Высокие

| # | Проблема | Где | Статус |
|---|----------|-----|--------|
| ~~**4**~~ | ~~Модели в админке захардкожены~~ | `admin.html` | ✅ **Решено** — вкладка Models, подгрузка из `/v1/models` |
| ~~**5**~~ | ~~Нет автосписка моделей из провайдеров~~ | `router.py` | ✅ **Решено** — `models_cache.json` + `POST /models/sync` + `GET /models/available` |
| **6** | Prices не обновляются динамически + **несогласованность валют** | `router.py:log_usage` | 🐛 **Открыто (Phase 4)** — см. «Известные баги» ниже |
| **7** | Нет fallback-провайдера | `router.py` | ⏳ **В работе (Phase 3)** — cross-provider fallback по плану `MULTIPROVIDER_PLAN.md` |
| ~~**8**~~ | ~~Нет тестов~~ | `tests/` | ✅ **Решено** — 198 тестов, `venv\Scripts\python.exe -m pytest tests/ -q` |
| **9** | Сбой сети роняет запрос без ретрая | `router.py:proxy` | ✅ **Решено в 2026-11** (`66204a2`) — 3 ретрая с backoff, connect-таймаут 20 с, честный текст ошибки в SSE |

### 🟡 P2 — Средние

| # | Проблема | Где | Суть |
|---|----------|-----|------|
| **10** | **Нет rate limiting** | — | ⏳ Спринт 3 — защита от перерасхода токенов |
| **11** | **Logger не структурированный** | `router.py:31-36` | ⏳ Спринт 3 — JSON-логи + Request ID |
| **12** | **Нет CORS middleware** | `router.py` | ⏳ Спринт 3 (нужно только для внешнего доступа к админке) |
| **13** | **Нет Docker** | — | ⏳ Не в приоритете — проект живёт локально |
| **14** | **Config.yaml и routing.json — два источника правды** | — | ⚠️ Частично: `config.yaml` — провайдеры/роли/цены (человеческий ввод, git), `routing.json` — runtime (модели ролей, tuning). Разведение зафиксировано в `MULTIPROVIDER_PLAN.md` |

### 🟢 P3 — Низкие

| # | Проблема | Где | Статус |
|---|----------|-----|--------|
| **15** | `Tuple[str, str]` return type | `router.py:480` | — Для современных Python (3.12+) лучше `tuple[str, str]` |
| ~~**16**~~ | ~~`@app.on_event("shutdown")` deprecated~~ | `router.py:899` | ✅ **Исправлено в f8edbb0** — заменён на `@asynccontextmanager lifespan`. В uvicorn ≥ 0.30 / FastAPI ≥ 0.110 прежний код падал с `TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'`. |
| **17** | Нет Request ID | — | — Сложно трассировать запросы через систему |
| **18** | Эмодзи в логах | `router.py:324` | — `💰` — не во всех терминалах корректно |
| **19** | Нет graceful shutdown для stats | `router.py:611` | — Статистика теряется при перезапуске |

---

# ✅ РЕШЕНО: как sub-agents маршрутизируются

> **Статус: решено.** Раздел сохранён как история ревью 2026-06-29.

Изначально проблема выглядела так: все запросы шли через `deepseek/deepseek-v4-pro`, ни одного `🔄 Маршрутизация: ... -> deepseek/deepseek-v4-flash`:

```
💰 deepseek/deepseek-v4-pro: In 270452 | Out 135 | Cost $0.135429
💰 deepseek/deepseek-v4-pro: In 270798 | Out 544 | Cost $0.136215
```

Диагноз тогда свёлся к трём причинам (все они сняты):

### Причина A: System prompt sub-agent'а — generic

Zed при создании sub-agent'а генерирует **новый** system prompt через `SystemPromptTemplate` — без маркеров роли.

→ Решение: **fingerprinting отключён** (`a711cd6`). Роль определяется не по тексту промпта, а по явному тегу.

### Причина B: `[AGENT:name]` префикс — зависит от Coordinator (LLM)

AGENTS.md инструктирует Coordinator добавлять `[AGENT:database]` в начало сообщения. LLM не всегда следует инструкциям на 100%.

→ Решение: **AGENTS.md теперь содержит жёсткое правило** — «При вызове `spawn_agent()` КАЖДОЕ сообщение sub-agent'у ДОЛЖНО начинаться с `[AGENT:agent_name]`», а сам SmartRouter использует этот тег для выбора дешёвой модели. Отдельный fallback-heuristic не потребовался.

### Причина C: `fingerprint_user_messages()` — слишком узкие паттерны

Паттерны искали технические термины (`database/*.py`, `alembic/versions/*.py`), а Coordinator даёт задачу естественным языком.

→ Решение: **fingerprinting отключён** (`a711cd6`), а в 2026-11 его код **удалён целиком** (~317 строк) вместе с тестами `tests/phase1/test_natural_lang.py`. Роль определяется только по тегу `[AGENT:name]` — см. `ROADMAP.md` (шаги 1.1 / 1.2 / 2.5 отклонены).

### Как работает сейчас

```
1. Coordinator вызывает spawn_agent("🔧 API", "[AGENT:api] Добавь эндпоинт POST /models/sync")
2. Zed создаёт sub-agent thread с этим user-сообщением
3. SmartRouter: smart_route_model() видит тег [AGENT:api]
4. → agent_to_worker_mapping["api"] → роль worker_default → её модель
5. Модель Coordinator в это время не тратится
```

> ⚠️ Всё ещё стоит следить за тем, чтобы Coordinator **не забывал** префикс `[AGENT:name]`: без него запрос корректно уйдёт в Coordinator (fallback по умолчанию), а не к Worker.

---

# 🔧 План развития v1.5 → v2.0

> Актуальные приоритеты — в `ROADMAP.md` и `MULTIPROVIDER_PLAN.md`. Блок ниже — исторический срез на 2026-07, актуализирован по состоянию на 2026-11.

```
Спринт 2026-11 ───────────────────────────────────────────────────
🔴 P0  ├── ✅ Атомарная запись конфигов (04d1fd8)
       └── ✅ Transport hardening: ретраи + SSL + таймауты (66204a2)

Спринт 2026-11 (продолжение) ─────────────────────────────────────
🟠 P1  ├── Phase 1 — каталог моделей по провайдерам + фильтрация
🟠 P1  ├── Phase 2 — resolve_model_spec, ключи provider::model_id
🟠 P1  ├── Phase 3 — cross-provider fallback (Спринт 2)
🟠 P1  └── Phase 4 — цены/валюты/лимиты (Спринт 2)

Спринт 2026-11 (Спринт 3) ────────────────────────────────────────
🟡 P2  ├── Phase 5 — UX админки: тест соединения, счётчики, фильтры
🟡 P2  ├── Rate limiting
🟡 P2  └── Структурированные JSON-логи + Request ID

Месяц 2+ ────────────────────────────────────────────────────────
🟢 P3  ├── БД (SQLite) — только при появлении истории затрат / >10K моделей
🟢 P3  ├── Smart Router v2 — Agent Framework
🟢 P3  ├── Skill Prompting Engine (YAML-driven)
🟢 P3  └── Интеграция VS Code / JetBrains, CLI (`sr chat "..."`)
```

## Состояние (чек-лист)

- [x] Переименование в SmartRouter
- [x] `[AGENT:name]` префикс в AGENTS.md — **единственный рабочий канал** маршрутизации sub-agent'ов
- [x] Админ-панель: логи + агенты + провайдеры + модели
- [x] Сохранение провайдеров + API-ключей из админки
- [x] config.yaml + routing.json
- [x] **🟢 P3 #16: lifespan вместо `@app.on_event` (f8edbb0)**
- [x] **🔴 P0: Дехардкод Coordinator fallback** — смена моделей на лету, без перезапуска
- [x] **`GET /v1/models`**
- [x] **Автосписок моделей провайдера** (`models_cache.json` + `/models/sync`)
- [x] **Fine tuning ролей через админку** (параметры + system prompt prefix)
- [x] **🧪 198 тестов** (`pytest tests/ -q`)
- [x] **🔴 P0: атомарная запись конфигов** (2026-11, `04d1fd8`)
- [x] **🟠 P1: transport hardening** — ретраи, connect-таймаут, per-provider SSL (2026-11, `66204a2`)
- [ ] **🟠 P1: Phase 1 — каталог моделей по провайдерам** (следующий)
- [ ] **🟠 P1: Phase 2 — провайдер определяется по модели**
- [ ] Динамические цены в админке + корректные валюты (Phase 4)
- [ ] Provider failover (cross-provider, Phase 3)
- [ ] Rate limiting
- [ ] JSON-логи + Request ID
- [ ] Разделение портов router/admin (сейчас single_port=true → 8765)
- [ ] Persistent stats
- [ ] Smart Router v2 (Agent Framework + Skills)

### ❌ Отклонено

- ~~**Шаг 2.5 — sub-agent fallback heuristic**~~ (см. раздел «📋 Что нового»). Coordinator в Zed — главный thread чата, а не роль роутера. Связка `[AGENT:name]` → `agent_to_worker_mapping` остаётся единственным каналом маршрутизации sub-agent'ов.
- ~~**Переход на БД (SQLite/Postgres) на текущем этапе**~~ — JSON остаётся: конфиг должен быть ручным и версионируемым в git, кеш регенерируем, статистика — in-memory агрегаты. Триггеры для перехода: история затрат по дням, >1 параллельного писателя, аудит-трейл конфига, >10K моделей.
- ~~**Глобальное отключение проверки SSL**~~ — вместо этого per-provider `verify_ssl` / `ca_bundle`.

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

> **Статус:** ✅ Реализовано (`router.py`, endpoint `GET /v1/models`)

Zed при старте делает `GET /v1/models` для получения списка доступных моделей. SmartRouter отдаёт:
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

> 📌 **Дальше (Phase 2 плана):** ID моделей станут составными — `provider::model_id` (например `openrouter::deepseek/deepseek-v4-flash`), чтобы провайдер определялся по самой модели, а не глобальным переключателем.

---

## 🐛 Известные баги (не исправлены)

| # | Баг | Где | Планируется |
|---|-----|-----|-------------|
| **1** | **Валюты в `log_usage()` перепутаны** — стоимость считается как ₽ за 1M токенов, но подписывается символом `$`. Фактические цены RouterAI — в рублях за токен, OpenRouter — строки в USD, Ollama — бесплатно | `router.py:log_usage` | Phase 4 |
| **2** | **Фиктивный fallback цен** `{0.50, 1.50}` для неизвестных моделей — в статистику попадают выдуманные числа | `router.py:log_usage` | Phase 4 |
| **3** | **Цены в `config.yaml: models:` выдуманы** — например `deepseek-v4-pro: 0.5` против реальных ~131.95 ₽/1M | `config.yaml` | Phase 4 (ручной override) |
| **4** | **Каталог моделей загрязнён** — 401 модель, из них лишь ~15% text→text. Нужен фильтр по `architecture.output_modalities` и `pricing_units.prompt == "token"` | `router.py:sync_models_from_provider` | Phase 1 |
| **5** | **Статистика не переживает перезапуск** — in-memory агрегаты | `router.py:state.stats` | P3 |

> 💡 **Про БД.** Переход на SQLite/Postgres на текущем этапе **не нужен**: конфиг должен оставаться ручным и версионируемым в git, кеш моделей регенерируем, статистика — in-memory агрегаты. БД станет актуальна, когда появится: история затрат по дням, больше одного параллельного писателя, аудит-трейл конфига или больше 10K моделей. Зафиксировано как P3 с триггерами в `ROADMAP.md`.

---

## 🛣️ Roadmap

Полный план развития вынесен в отдельный файл: **[ROADMAP.md](ROADMAP.md)**, архитектурный план мультипровайдерности — в **[MULTIPROVIDER_PLAN.md](MULTIPROVIDER_PLAN.md)**.

### Краткий срез приоритетов:

| Приоритет | Что | Статус |
|-----------|-----|--------|
| 🔴 P0 | Рефакторинг на 3 роли (Coordinator / Worker / Worker Img) | ✅ Сделано |
| 🔴 P0 | Fallback chain между ролями | ✅ Сделано |
| 🔴 P0 | Дехардкод Coordinator fallback (смена моделей без перезапуска) | ✅ Сделано |
| 🔴 P0 | Атомарная запись конфигов | ✅ Сделано (2026-11) |
| 🟠 P1 | Fine tuning ролей через админку | ✅ Сделано |
| 🟠 P1 | Transport hardening (ретраи, connect-таймаут, per-provider SSL) | ✅ Сделано (2026-11) |
| 🟠 P1 | Phase 1 — каталог моделей по провайдерам | ⏳ Следующий |
| 🟠 P1 | Phase 2 — провайдер определяется по модели (`provider::model_id`) | ⏳ Далее |
| 🟠 P1 | Phase 4 — цены, валюты, лимиты | ⏳ Спринт 2 |
| 🟡 P2 | Provider failover (cross-provider) | ⏳ Спринт 2 |
| 🟡 P2 | Rate limiting, JSON-логи, Request ID | ⏳ Спринт 3 |
| 🟢 P3 | Переход на БД (только при появлении истории затрат / >10K моделей) | ⏳ По триггерам |
| 🟢 P3 | Smart Router v2 — Agent Framework + Skills | ⏳ В плане |

---

## 📝 Лицензия

MIT
