# 🧠 SmartRouter — Roadmap

## 📐 Архитектура ролей (v2)

```
┌─────────────────────────────────────────────────────────┐
│                    SmartRouter                            │
│                                                          │
│  ┌────────────────────┐   ┌──────────────────────────┐  │
│  │   Admin Panel      │   │     Routing Engine        │  │
│  │  (управление)      │   │  (маршрутизация +        │  │
│  │                    │   │   fingerprinting)         │  │
│  └────────┬───────────┘   └───────────┬──────────────┘  │
│           │                           │                  │
│  ┌────────┴───────────────────────────┴──────────────┐  │
│  │               Три роли моделей                     │  │
│  │                                                    │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐        │  │
│  │  │Coordinator│  │Worker    │  │Worker Img│        │  │
│  │  │(сложные  │  │(default) │  │(vision)  │        │  │
│  │  │ задачи)  │  │          │  │          │        │  │
│  │  └──────────┘  └──────────┘  └──────────┘        │  │
│  │                                                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────── Fallback Chain ─────────────────┐  │
│  │                                                    │  │
│  │  Worker (default) → Если ошибка → Coordinator     │  │
│  │  Worker Img       → Если ошибка → Worker (default)│  │
│  │  Coordinator      → Если ошибка → Worker (default)│  │
│  │                                                    │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## 🔄 SDLC — Обязательный процесс разработки

> **Это правило обязательно для каждой фазы, каждого шага и каждого изменения в коде.**
> Нарушение процесса = риск падения роутера (уже было).

### Цикл одного шага

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 🛠 Code — изменение кода (minimal diff)                  │
│    ├── Только необходимые изменения                         │
│    ├── Не трогать то, что работает                          │
│    └── Комментарий о том, что изменилось                    │
│                                                             │
│ 2. 🧪 Test — запуск тестов                                  │
│    ├── pytest tests/phaseN/ -v    (текущая фаза)            │
│    ├── pytest tests/phase0/ -v   (фундамент)                │
│    └── Все тесты должны быть ЗЕЛЁНЫМИ                       │
│                                                             │
│ 3. 🔄 Restart — перезапуск роутера                          │
│    ├── Твоя команда в окне: Ctrl+C                          │
│    ├── Твоя команда: venv\Scripts\activate && python router.py│
│    └── Ждём сообщение: "SmartRouter запущен на ..."         │
│                                                             │
│ 4. ✅ Health Check — проверка что роутер жив               │
│    ├── curl http://localhost:8765/health → {"status":"ok"}  │
│    ├── curl http://localhost:8765/v1/models → массив моделей│
│    ├── curl POST /v1/chat/completions → 502/200 (не 404)   │
│    └── curl http://localhost:8765/admin → 200 HTML          │
│                                                             │
│ 5. 📦 Git Commit + Push — сохранение в репозиторий          │
│    ├── git add -A                                           │
│    ├── git commit -m "<message>"                            │
│    └── git push origin main                                 │
│                                                             │
│ 6. 📝 Docs — обновление документации                        │
│    ├── README.md — если изменились user-facing функции      │
│    ├── docs/ROADMAP.md — отметить шаг как выполненный      │
│    └── AGENTS.md — если изменились правила маршрутизации    │
│                                                             │
│ 7. 🤝 Согласование — ты проверяешь                          │
│    ├── Я показываю что изменилось                           │
│    ├── Ты смотришь логи / админку / Zed                     │
│    └── Ты говоришь "GO" → следующий шаг                    │
└─────────────────────────────────────────────────────────────┘
```

### Команды для быстрой проверки

```bash
# Проверка здоровья роутера (шаг 4)
curl -s http://localhost:8765/health
curl -s http://localhost:8765/v1/models | python -c "import sys,json; print('Models:', len(json.load(sys.stdin)['data']))"
curl -s -X POST http://localhost:8765/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"SmartAuto","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' | python -c "import sys,json; d=json.load(sys.stdin); print('Status:', 'OK' if 'choices' in d else d.get('detail','?'))"
```

### Git — правила

- **Commit после каждого шага** (не после фазы целиком)
- Сообщение: present tense, короткое, что изменилось.
- Push в master.
- Если что-то пошло не так — `git diff` → `git checkout -- <file>` для отката.

### Запасной план (если роутер упал)

Если после перезапуска роутер не работает (health → 404, логи пустые, админка не открывается):

```
1. Открой окно с router.py
2. Ctrl+C
3. Проверь нет ли ошибки в коде (SyntaxError, ImportError)
4. Запусти заново: python router.py
5. Если не помогло → откат изменений через git:
   git checkout -- router.py config.yaml admin.html
6. Перезапусти роутер снова
7. Временно → используй RouterAI напрямую в Zed settings.json
```

### Контрольные точки для каждого шага

```markdown
- [ ] 🛠 Код написан
- [ ] 🧪 Тесты проходят (pytest tests/ -v)
- [ ] 🔄 Роутер перезапущен
- [ ] ✅ /health = 200 OK
- [ ] ✅ /v1/models работает
- [ ] ✅ POST /v1/chat/completions не 404
- [ ] ✅ Админка открывается
- [ ] 📦 Git commit + push
- [ ] 📝 Документация обновлена (README / ROADMAP / AGENTS)
- [ ] 🤝 Согласовано с тобой
```

---

## 🔴 P0 — Немедленно (текущий спринт)

### ~~1.1 Quick Win: Sub-agent fallback (3 строки)~~ ❌ ОТКЛОНЁН (2026-07-01)

**Причина отклонения:** Coordinator в Zed — это не роль SmartRouter'а, а **главный thread чата**, который сам spawn'ит sub-agent'ов через `[AGENT:name]` тег. Текущая архитектура маршрутизации работает стабильно:

- Coordinator в Zed → Coordinator-модель (deepseek-v4-pro / minimax-m3)
- Sub-agent `[AGENT:database]` → worker_default (deepseek-v4-flash)
- Sub-agent `[AGENT:mobile]` → worker_img (qwen3-coder-next)

Heuristic "короткий system prompt → default_worker" **отклонён**, т.к. может сломать короткие Coordinator-промпты (например, через CLI). Если Coordinator забудет тег `[AGENT:name]` — лучше чинить Coordinator'а, чем скрывать баг эвристикой.

### ~~1.2 Расширение fingerprint_user_messages (естественный язык)~~ ❌ ОТКЛОНЁН (2026-07-01)

**Причина отклонения:** Fingerprinting естественного языка не нужен при рабочей схеме `[AGENT:name]` — Coordinator в Zed **всегда** отправляет тег (правило зафиксировано в `AGENTS.md`). Маршрутизация по тегу работает стабильно и однозначна; эвристика по user messages добавляет ложные срабатывания и неопределённость.

### 1.3 GET /v1/models ✅ СДЕЛАНО

Обязательный эндпоинт для Zed. Реализован в `router.py` (`GET /v1/models`), возвращает модели из `config.yaml` + кеша провайдера.

> 📌 Дальше (Phase 2): ID станут составными — `provider::model_id`.

### 1.4 Дехардкод Coordinator fallback ✅ СДЕЛАНО

**Что было:** неизвестные запросы → `mapping["coordinator"]` → GLM/Pro (дорого).
Также size-based fallback: `len(system_prompt) > 3000 → coordinator`.

**Что стало:** Coordinator-модель вынесена в `routing.json:role_models.coordinator` и меняется из админки **на лету, без перезапуска роутера**. Размер system prompt больше не влияет на маршрутизацию; fingerprinting отключён (`a711cd6`, `db9365a`).

**Эффект:** неизвестные запросы и длинные generic промпты больше не улетают на дорогую модель, а модель Coordinator можно менять без рестарта.

**Тесты:** `tests/phase1/test_dehardcode.py` — 8 тестов.

**Коммиты:** `1cfa15b`, `a711cd6`, `db9365a`

### 1.5 Атомарная запись конфигов ✅ СДЕЛАНО (2026-11)

**Что было:** `routing.json` / `config.yaml` / `.env` писались напрямую через `write_text`. Прерванная запись оставляла файл битым, и при следующем старте `_load_config()` молча вызывал `_init_default_config()` — **настройки ролей терялись безвозвратно**.

**Что стало:**
- `_atomic_write()` — запись в `*.tmp` + `flush` + `fsync` + `os.replace()` (атомарно на Windows/Linux)
- битый `routing.json` / `models_cache.json` сохраняется как `*.broken` и **не перезаписывается** дефолтами

**Тесты:** `tests/phase4/test_atomic_config.py` — 13 тестов.

**Коммит:** `04d1fd8`

### 1.6 Transport hardening ✅ СДЕЛАНО (2026-11)

**Что было:** сетевой сбой (например `CERTIFICATE_VERIFY_FAILED` от провайдера) ронял весь streaming-ответ, в лог уходило безобщее `Internal Proxy Error`, connect-таймаут отсутствовал (висящий TLS handshake держал слот 180 с).

**Что стало:**
- connect-таймаут 20 с + общий таймаут 180 с (настраиваются env)
- 3 ретрая с экспоненциальной задержкой на `ConnectError` / `ConnectTimeout` / `ReadTimeout`; в streaming — только пока клиент не получил ни одного байта
- реальная причина ошибки в SSE вместо `Internal Proxy Error`
- per-provider `verify_ssl` / `ca_bundle` — свой CA для корпоративных шлюзов

**Тесты:** `tests/phase4/test_transport_retry.py` — 13 тестов.

**Коммит:** `66204a2`

---

## 🟠 P1 — Неделя 1-2

### 2.1 Три роли: Coordinator / Worker / Worker Img

Переход от flat-списка агентов к трём ролям:

```yaml
# config.yaml (новый формат)
roles:
  coordinator:
    name: "🧠 Coordinator"
    description: "Сложные задачи, код-ревью, архитектура"
    default_model: "deepseek/deepseek-v4-pro"
    fallback_model: "deepseek/deepseek-v4-flash"
    agents: ["coordinator"]
    capabilities:
      tools: true
      images: false
      max_tokens: 1048576

  worker_default:
    name: "⚡ Worker (default)"
    description: "Технические задачи — database, api, tests, bot, services, devops"
    default_model: "deepseek/deepseek-v4-flash"
    fallback_model: "deepseek/deepseek-v4-pro"
    agents: ["database", "tests", "bot", "api", "services", "devops"]
    capabilities:
      tools: true
      images: false
      max_tokens: 1048576

  worker_img:
    name: "🖼️ Worker Img"
    description: "Задачи с изображениями — frontend, mobile, design"
    default_model: "qwen/qwen3-coder-next"
    fallback_model: "deepseek/deepseek-v4-flash"
    agents: ["frontend", "mobile", "design"]
    capabilities:
      tools: true
      images: true
      max_tokens: 262144
```

**Маппинг агентов на роли:**
```
coordinator → 🧠 Coordinator
database    → ⚡ Worker (default)
tests       → ⚡ Worker (default)
bot         → ⚡ Worker (default)
api         → ⚡ Worker (default)
services    → ⚡ Worker (default)
devops      → ⚡ Worker (default)
frontend    → 🖼️ Worker Img
mobile      → 🖼️ Worker Img
design      → 🖼️ Worker Img
```

### 2.2 Fallback Chain (продуманный)

```
Worker (default) падает с 5xx/503:
  → Пробуем Coordinator (может обработать)
  → Если Coordinator тоже падает → возвращаем ошибку

Worker Img падает с 5xx/503:
  → Пробуем Worker (default) — без изображений, но задачу сделает
  → Если Worker (default) тоже падает → возвращаем ошибку

Coordinator падает с 5xx/503:
  → Пробуем Worker (default) — упрощённая версия
  → Если Worker (default) тоже падает → возвращаем ошибку
```

**Реализация в proxy():**
```python
# Псевдокод
async def proxy(request):
    actual_model, role = smart_route_model(...)
    try:
        return await forward_to_provider(actual_model, body)
    except ProviderError:
        fallback_model = roles[role].fallback_model
        logger.warning(f"Fallback: {actual_model} → {fallback_model}")
        return await forward_to_provider(fallback_model, body)
```

### 2.3 Разделение портов

Чтение портов из config.yaml:
```yaml
server:
  router_port: 8765
  admin_port: 8766
  admin_host: "127.0.0.1"
```

Возможность запуска на одном порту (текущий режим) или на двух.

---

## 🟡 P2 — Неделя 3-4

### 3.1 Fine Tuning через админку

Для каждой из 3-х ролей в админке появляется **вкладка Fine Tuning**:

```yaml
# То, что можно настроить для каждой роли
roles:
  coordinator:
    model:
      current: "z-ai/glm-5.2"
      fallback: "deepseek/deepseek-v4-pro"
      provider: "RouterAI"
    
    # Параметры генерации
    parameters:
      temperature: 0.7         # slider 0.0 — 2.0
      top_p: 0.9               # slider 0.0 — 1.0
      max_tokens: 384000
      presence_penalty: 0.0    # slider -2.0 — 2.0
      frequency_penalty: 0.0   # slider -2.0 — 2.0
    
    # Prompt engineering
    system_prompt_prefix: |
      You are a senior architect. Focus on:
      - Decomposition of complex tasks
      - Code review and quality
      - Architecture decisions
    
    # Маршрутизация
    routing:
      priority_patterns:
        - "code.review|architecture|design.doc"
        - "декомпозици|архитектур"
      agents: ["coordinator"]
```

**UI для админки:**

```
┌─────────────────────────────────────────────────────┐
│  Roles                    │  Coordinator ▼           │
│  ─────────────────────────┤                          │
│  🧠 Coordinator            │  Model: [z-ai/glm-5.2 ▼]│
│  ⚡ Worker (default)       │  Fallback: [deepseek...]│
│  🖼️ Worker Img            │  Provider: [RouterAI ▼] │
│                            │                          │
│  Parameters                │  Temperature  ──●──── 0.7│
│                            │  Top P        ──●──── 0.9│
│                            │  Max Tokens   [384000  ]│
│                            │                          │
│  System Prompt Prefix      │                          │
│  ┌────────────────────────┐│                          │
│  │ You are a senior       ││                          │
│  │ architect. Focus on... ││                          │
│  └────────────────────────┘│                          │
│                            │                          │
│  [💾 Save Role Config]     │                          │
└─────────────────────────────────────────────────────┘
```

### 3.2 Динамические цены моделей

- Поле в админке для каждой модели: `input_price`, `output_price`
- Авто-обновление из RouterAI/OpenRouter API
- Отображение стоимости в реальном времени в логах

### 3.3 Failover между провайдерами

- RouterAI → OpenRouter при 5xx/таймауте
- Настройка в админке: приоритет, таймауты, retry policy

---

---

## 🧪 Система тестирования (per-phase)

Тесты пишутся и расширяются **последовательно**, вместе с каждой фазой. После каждой фазы — запуск тестов этой и всех предыдущих фаз.

### 🏃 Как запускать

```bash
cd smart-routing
venv\Scripts\activate
pytest tests/ -v              # Все тесты
pytest tests/ -v -k "phase1"  # Только фазу 1
pytest tests/ -v --tb=short   # Без длинных traceback
```

### Файловая структура тестов

```
tests/
├── conftest.py                 # Общие фикстуры (клиент, конфиг)
├── requirements-test.txt       # Зависимости для тестов (pytest, httpx)
├──
├── phase0/
│   ├── test_health.py          # /health, /v1/models
│   ├── test_proxy.py           # POST /v1/chat/completions (базовый)
│   ├── test_logs.py            # /logs, /stats
│   └── test_config.py          # /config (загрузка/сохранение)
│
├── phase1/
│   ├── test_fingerprinting.py  # Fingerprint-паттерны (sys prompt + user msg)
│   ├── test_routing_logic.py   # smart_route_model() — все 8 шагов
│   ├── test_sub_agent.py       # Sub-agent fallback heuristic
│   ├── test_natural_lang.py    # Естественно-языковые паттерны
│   └── test_providers_api.py   # /providers CRUD
│
├── phase2/
│   ├── test_roles.py           # 3 роли: Coordinator / Worker / Worker Img
│   ├── test_fallback.py        # Fallback chain (5xx → другая модель)
│   ├── test_ports.py           # Разделение портов (8765/8766)
│   └── test_admin_panel.py     # Админка (вкладки Agents, Providers, Roles)
│
├── phase3/
│   ├── test_fine_tuning.py     # API параметров ролей (temperature и т.д.)
│   ├── test_prices.py          # Динамические цены моделей
│   ├── test_provider_failover.py # RouterAI → OpenRouter при ошибке
│   └── test_blacklist.py       # API-blacklist
│
├── phase4/
│   ├── test_transport_retry.py  # Ретраи, backoff, per-provider SSL, таймауты
│   ├── test_atomic_config.py    # Атомарная запись конфигов, backup битых файлов
│   ├── test_docker.py          # Dockerfile сборка + запуск
│   ├── test_logging.py         # JSON-логи, Request ID
│   ├── test_structured_logs.py # Структурированные логи
│   └── test_perf.py            # Производительность (latency, rps)
```

### Что тестировать в каждой фазе

#### Phase 0 — Существующая функциональность (тесты до рефакторинга)

| Тест | Что проверяет | Критерий успеха |
|------|-------------|----------------|
| `test_health.py` | `GET /health` и `GET /v1/models` | 200 OK, корректный JSON |
| `test_proxy.py` | POST с валидным телом | 502 (нет ключа) или 200 (с ключом) |
| `test_logs.py` | `GET /logs`, `GET /stats` | Возвращает массив, структура корректна |
| `test_config.py` | `GET/POST /config`, сохранение в routing.json | Чтение-запись, файл создаётся |

```bash
# После Phase 0:
pytest tests/phase0/ -v
```

#### Phase 1 — Quick Wins (sub-agent fallback + fingerprint)

| Тест | Что проверяет | Критерий успеха |
|------|-------------|----------------|
| `test_fingerprinting.py` | `fingerprint_system_prompt()` для всех 10 агентов | Каждый агент ≥ порога |
| `test_routing_logic.py` | Все 8 шагов `smart_route_model()` | Корректная маршрутизация |
| `test_sub_agent.py` | Sub-agent без system prompt → default_worker | Не Coordinator, а Flash |
| `test_natural_lang.py` | Естественный язык: "создай таблицу" → database | Score ≥ порога |
| `test_providers_api.py` | CRUD провайдеров, сохранение ключей | Создать/обновить/удалить |

```bash
# После Phase 1:
pytest tests/phase0/ tests/phase1/ -v
```

#### Phase 2 — 3 роли + Fallback

| Тест | Что проверяет | Критерий успеха |
|------|-------------|----------------|
| `test_roles.py` | Маппинг агентов на Coordinator/Worker/Worker Img | Все 10 агентов распределены |
| `test_fallback.py` | 5xx → fallback_model, цепочка падений | Лог fallback, смена модели |
| `test_ports.py` | Раздельные порты router/admin | 8765 работает, 8766 работает |
| `test_admin_panel.py` | HTML админки, JS-функции | Статус 200, скрипты не падают |

```bash
# После Phase 2:
pytest tests/ -v -k "phase0 or phase1 or phase2"
```

#### Phase 3 — Fine Tuning + Failover

| Тест | Что проверяет | Критерий успеха |
|------|-------------|----------------|
| `test_fine_tuning.py` | API температуры, промпт-префиксов | Сохраняется, применяется |
| `test_prices.py` | Изменение цен через админку | cost пересчитывается |
| `test_provider_failover.py` | Отключение RouterAI → OpenRouter | Прокси переключается |
| `test_blacklist.py` | deprecated model → 400 | Блокировка работает |

```bash
# После Phase 3:
pytest tests/ -v
```

#### Phase 4 — Transport hardening + атомарная запись (2026-11) ✅

| Тест | Что проверяет | Критерий успеха |
|------|-------------|----------------|
| `test_transport_retry.py` | Ретраи на `ConnectError` / `ConnectTimeout` / `ReadTimeout`, экспоненциальный backoff, отсутствие ретрая после отправки байтов, per-provider SSL-клиент и его кэш, честный текст ошибки в SSE | 13 тестов, без сети |
| `test_atomic_config.py` | Атомарная запись (нет `.tmp` в остатке), перезапись целиком, backup битого `routing.json` как `*.broken`, конфиг НЕ затирается дефолтами | 13 тестов |

```bash
# После Phase 4:
pytest tests/phase4/ -v
```

#### Phase 5 — Мультипровайдерность ✅ (2026-11)

| Тест | Что проверяет | Критерий успеха |
|------|---------------|-----------------|
| `test_provider_catalog.py` | Каталог моделей по провайдерам, фильтрация text→text, миграция формата кеша | 21 тест |
| `test_resolve_model_spec.py` | `provider::model_id` → `(provider, model_id)`, bare-ID → каталог → `default_provider` | 9 тестов |
| `test_provider_proxy.py` | Проксирование к правильному провайдеру, ключ из модели, `body["model"]` без префикса | 14 тестов |
| `test_currency_pricing.py` | Цены и валюты: ₽ из RouterAI, USD из OpenRouter, free для Ollama | 10 тестов |
| `test_regressions.py` | Регресс-тесты на 4 бага, найденных ручным прогоном | 16 тестов |

```bash
# После Phase 5:
pytest tests/phase5/ -v
```

**Итого: 243 теста, все зелёные** (`pytest tests/ -q`).

#### Phase 6 — Docker + Production

| Тест | Что проверяет | Критерий успеха |
|------|-------------|----------------|
| `test_docker.py` | `docker build .` + `docker run` | Контейнер стартует, /health 200 |
| `test_logging.py` | JSON-логи, Request ID | Структура, X-Request-ID в ответе |
| `test_perf.py` | 100 rps, latency < 500ms | Не падает под нагрузкой |

```bash
# Все тесты перед деплоем:
pytest tests/ -v --tb=short
```

### ⚙️ conftest.py (базовая структура)

```python
# tests/conftest.py
import pytest
from httpx import AsyncClient, ASGITransport
import sys
sys.path.insert(0, "..")

@pytest.fixture
async def client():
    """Тестовый HTTP-клиент к SmartRouter."""
    from router import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def sample_coordinator_prompt():
    return "You are the Zed coding agent. AGENTS.md, SYSTEM_CONTEXT.md, spawn_agent, VPS deploy."

@pytest.fixture
def sample_bot_prompt():
    return "You are a Telegram Bot with aiogram handlers, FSM states, inline keyboards."
```

### 🔄 Цикл разработки с тестами

Каждая фаза:

```
1. 🛠 Реализация фичи (код)
2. 🧪 Написание тестов для этой фичи (в tests/phaseN/)
3. ✅ Запуск: pytest tests/ -v
4. 📦 Коммит + Пуш
5. 🖥 Деплой на VPS
6. 🧪 Тесты на VPS: docker compose exec app pytest tests/ -v
```

### 4.2 Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "router.py"]
```

### 4.3 Structured Logging + Metrics

- JSON-логи вместо text
- Prometheus endpoint `/metrics`
- Request ID (X-Request-ID)

### 4.4 Smart Router v2 — Agent Framework

```
skills/
├── coordinator/
│   ├── code-review.yaml
│   ├── architecture.yaml
│   └── deploy.yaml
├── worker/
│   ├── database.yaml
│   ├── api.yaml
│   ├── tests.yaml
│   └── devops.yaml
└── worker-img/
    ├── frontend.yaml
    ├── mobile.yaml
    └── design.yaml
```

### 4.5 Skill Prompting Engine

```python
class SkillEngine:
    """
    1. Определяет агента (fingerprint + scope analysis)
    2. Загружает skill.yaml
    3. Инжектирует system_prompt с пресетом роли
    4. Применяет routing rules
    """
```

---

## 📊 Приоритет выполнения

```
Сейчас ──────────────────────────────────────────────────────
🔴 P0  ├── ✅ GET /v1/models (готов)
🔴 P0  ├── ✅ Реальные цены моделей в config.yaml (была дефолтная заглушка)
🔴 P0  ├── ✅ Hot-reload server.* параметров (single_port)
🔴 P0  ├── ✅ Атомарная запись конфигов (2026-11)
🔴 P0  └── ✅ Transport hardening: ретраи + таймауты + per-provider SSL (2026-11)

Спринт 2026-11 ───────────────────────────────────────────────
🟠 P1  ├── Phase 1 — каталог моделей по провайдерам (+ фильтрация)   ✅
🟠 P1  ├── Phase 2 — resolve_model_spec: provider::model_id          ✅
🟠 P1  ├── Phase 3 — cross-provider fallback                        🟡 частично
🟠 P1  ├── Phase 4 — цены / валюты / лимиты                        🟡 частично
🟠 P1  └── Phase 5 — UX админки                                     🟡 частично

Неделя 1-2 (исторический план) ─────────────────────────────
🟠 P1  ├── Три роли: Coordinator / Worker / Worker Img          ✅
🟠 P1  ├── Fallback chain                                        ✅
🟠 P1  ├── Разделение портов                                     ✅
🟠 P1  ├── Fine tuning в админке (параметры + промпты)           ✅
🟠 P1  ├── Динамические цены моделей                             ⏳ Phase 4
🟠 P1  └── Structured Logging (JSON-логи + Request ID)          ⏳ Спринт 3

Неделя 3-4 ─────────────────────────────────────────────────
🟡 P2  ├── Provider failover (RouterAI → OpenRouter)            ⏳ Phase 3
🟡 P2  ├── Rate limiting                                         ⏳ Спринт 3
🟡 P2  ├── Тесты (pytest)                                        ✅ 198 тестов
🟡 P2  └── Docker                                                ⏳

Месяц 2+ ───────────────────────────────────────────────────
🟢 P3  ├── Переход на БД — по триггерам (история затрат / >10K моделей)
🟢 P3  ├── Smart Router v2 — Agent Framework
🟢 P3  ├── Skill Prompting Engine
🟢 P3  ├── CLI (`sr chat`)
       └── Prometheus metrics
```

> ❌ Снято с приоритета (отклонено 2026-07-01): sub-agent fallback heuristic (Step 1.1), fingerprint_user_messages — естественный язык (Step 1.2). Coordinator в Zed маршрутизирует sub-agent'ов через `[AGENT:name]` тег — эвристика не нужна и может ломать короткие Coordinator-промпты.
>
> ❌ Снято с приоритета (2026-11): переход на БД на текущем этапе — JSON остаётся (конфиг ручной и версионируемый, кеш регенерируем, статистика in-memory). БД нужна только при появлении истории затрат по дням, >1 параллельного писателя, аудит-трейла конфига или >10K моделей.

---

## 🔄 Статус выполнения

- [x] Переименование в SmartRouter
- [x] System prompt fingerprinting
- [x] `[AGENT:name]` префикс в AGENTS.md
- [x] User message fingerprinting
- [x] Админ-панель: логи + агенты + провайдеры
- [x] Сохранение провайдеров + API-ключей из админки
- [x] config.yaml + routing.json
- [x] GET /v1/models
- [x] Исправлен баг: `@app.post("/v1/chat/completions")` + `load_dotenv()`
- [x] **🔴 P0: Sub-agent fallback heuristic** (Step 1.1)
- [x] **🔴 P0: fingerprint_user_messages — естественный язык** (Step 1.2)
- [x] **🧪 Phase 0: 32 теста (health, proxy, config, logs)**
- [x] **🧪 Phase 1: 30 тестов (sub-agent, natural lang)**
- [x] **🔴 P0: Дехардкод Coordinator fallback** (Step 1.4, commit 1cfa15b)
- [x] **🔴 P0: Рефакторинг на 3 роли (Coordinator / Worker / Worker Img)** (Step 2.1, commit 0f3359f)
- [x] **🔴 P0: Fallback chain между ролями** (Step 2.2, commit 9263a2b)
- [x] **🟠 P1: Phase 2.5 — Управление моделями через админку** (models_cache.json, sync RouterAI API, вкладка Models, кнопка Test Routing)
- [x] **🟠 P1: Phase 2.6 — Дехардкод: единый источник правды** (routing.json role_models, авто-fallback, изоляция тестов conftest)
- [x] **🧪 Phase 2: 61 тест (roles, fallback, ports, models)**
- [x] **📊 Итого: 143 теста, все зелёные**
- [x] **🔧 Fix FastAPI startup: replace deprecated `@app.on_event("shutdown")` with `@asynccontextmanager` lifespan** (commit f8edbb0)
- [x] **🔍 Code review SmartRouter** (2026-07-01): выявлены P1-P3, подтверждена стабильная работа архитектуры `[AGENT:name]` → role mapping
- [ ] ~~🔴 Step 2.5 (sub-agent fallback heuristic)~~ → ❌ ОТКЛОНЁН 2026-07-01 (Coordinator в Zed сам маршрутизирует через `[AGENT:name]`, эвристика не нужна)
- [x] **🔌 Transport hardening: ретраи при сетевых/SSL-ошибках, connect-таймаут 20 с, per-provider `verify_ssl` / `ca_bundle`, честный текст ошибки в SSE** (commit 66204a2, 2026-11)
- [x] **🔐 P0: атомарная запись конфигов** — `*.tmp` + `os.replace()`, битый `routing.json` сохраняется как `*.broken` и не перезаписывается дефолтами (commit 04d1fd8, 2026-11)
- [x] **📚 План мультипровайдерной переработки** — [`docs/MULTIPROVIDER_PLAN.md`](MULTIPROVIDER_PLAN.md) (commit ec52f46)
- [x] **📊 Итого: 198 тестов, все зелёные** (`pytest tests/ -q`)
- [x] **🧪 Phase 1 — каталог моделей по провайдерам** (+ фильтрация text→text, миграция кеша v1→v2, pricing-адаптеры, валюты) ✅ 2026-11
- [x] **🧪 Phase 2 — `resolve_model_spec`, ключи `provider::model_id`, провайдер определяется по модели** ✅ 2026-11
- [x] **🧹 Удаление мёртвого fingerprint-кода** (~317 строк + тесты) ✅ 2026-11
- [x] **🐛 4 бага, найденных ручным прогоном** (цена чужого провайдера, смешение валют в `total_cost`, затирание ролей в `POST /config`, двойной префикс в `/v1/models`) ✅ 2026-11
- [ ] 🟠 P1: **Phase 3 — cross-provider fallback** (цепочка уже умеет уходить на другого провайдера; нужен UI для `role_fallbacks` и явная логика 5xx/таймаутов)
- [ ] 🟠 P1: **Phase 4 — остатки**: авто-курс валют (4.6), лимиты, `context_length` → cap `max_tokens` для всех провайдеров (4.7)
- [ ] 🟡 P2: **Phase 5 — UX админки — остатки**: показать курс и сумму в USD в UI, бейдж цен по провайдерам
- [ ] 🟡 P2: Rate limiting
- [ ] 🟡 P2: JSON-логи + Request ID
- [ ] 🟢 P3: **Переход на БД** — только при появлении истории расходов по дням, >1 параллельного писателя, аудит-трейла конфига или >10K моделей

---

## 🧩 Спринт 2026-11 — Мультипровайдерность

> Полный архитектурный план: **[MULTIPROVIDER_PLAN.md](MULTIPROVIDER_PLAN.md)**. Ниже — статус и принятые решения.

### Цель

Сделать SmartRouter **провайдер-независимым**: любой OpenAI-совместимый провайдер (RouterAI, OpenRouter, локальный Ollama) добавляется через админку, его модели сканируются и управляются там же, а модели свободно назначаются ролям Coordinator / Worker **без перезапуска** роутера.

### Принятые решения

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Формат ключа модели | `provider::model_id` (`::` не встречается в ID моделей) |
| 2 | Валюты | RUB и USD хранятся **раздельно**, конверсия на лету по настраиваемому курсу |
| 3 | `config.yaml: models:` | Остаётся как **ручной override цен** (ручное значение выигрывает у каталога API) |
| 4 | Провайдер без ключа (Ollama) | Флаг `requires_api_key: false` в конфиге провайдера |
| 5 | Глобальный переключатель провайдера | Переименован в `default_provider`; используется **только** как fallback для bare-ID и моделей вне каталога; из UI убирается |
| 6 | `GET /v1/models` | Возвращает составные ID (`provider::model`) |
| 7 | Состав провайдеров | `routerai`, `openrouter`, `ollama` встроены; расширяется любым OpenAI-совместимым |
| 8 | Хранилище | JSON остаётся (см. «Отклонено» ниже) |

### Статус фаз

| Фаза | Что | Статус |
|-------|-----|--------|
| **Phase 0** | Атомарная запись конфигов | ✅ 2026-11 (`04d1fd8`) |
| **Phase 1** | Каталог моделей по провайдерам: `state.models_by_provider`, адаптеры цен (`auto` / `per_token_rub` / `per_token_usd` / `free`), фильтрация text→text, миграция кеша v1→v2, `POST /models/sync` с параметром `provider`, колонка Provider в админке | ✅ 2026-11 |
| **Phase 2** | `resolve_model_spec(spec) -> (provider, model_id)`; `proxy()` берёт URL и ключ **из модели**, а не из глобального провайдера; `body["model"]` уходит без префикса `provider::`; `log_usage()` по составному ключу с валютой; `role_fallbacks` в `routing.json`; `<optgroup>` в выпадающих списках ролей | ✅ 2026-11 |
| **Phase 3** | Cross-provider fallback | 🟡 частично: цепочка fallback **уже умеет** уходить на другого провайдера (проверено: OpenRouter 503 → RouterAI 200 OK), но явного `role_fallbacks` UI пока нет |
| **Phase 4** | Цены / валюты / лимиты | 🟡 основное сделано: валюты, `by_currency`, `usd_equivalent`, ручные override'ы с привязкой к провайдеру. Осталось: авто-курс (4.6), лимиты |
| **Phase 5** | UX админки: тест соединения, счётчики моделей, фильтры | 🟡 большая часть сделана в Phase 1–2 (выбор провайдера, фильтр по провайдеру, поиск, назначение на роль, `requires_api_key` / `pricing_mode` / `extra_headers` в форме) |

### ❌ Отклонено

- ~~**Переход на БД (SQLite / Postgres) на текущем этапе**~~ — JSON остаётся: конфиг должен оставаться ручным и версионируемым в git, кеш моделей регенерируем, статистика — in-memory агрегаты. БД нужна только при появлении: истории затрат по дням, >1 параллельного писателя, аудит-трейла конфига или >10K моделей. → P3 с триггерами.
- ~~**Глобальное отключение проверки TLS**~~ — вместо этого per-provider `verify_ssl` / `ca_bundle` (реализовано в `66204a2`).

---

## 🐛 Известные баги (не исправлены)

| # | Баг | Где | План |
|---|-----|-----|------|
| **1** | **Каталог `models_cache.json` не ограничен по размеру** — описание моделей занимает ~1 МБ на 3 провайдера | `router.py:_build_v2_cache` | P3 (обрезать `description`) |
| **2** | **Статистика не переживает перезапуск** — in-memory агрегаты | `router.py:state.stats` | P3 (переход на БД по триггерам) |
| **3** | **`role_fallbacks` не настраивается из админки** — только вручную через `POST /config` | `admin.html` | Phase 3 |
| **4** | **Курс валют статичный** (`usd_rate` в конфиге) — ручное обновление | `config.yaml` | Phase 4.6 |
| **5** | **Цены из `config.yaml` — глобальные или провайдер-специфичные** — при смене провайдера override надо перепривязать | `config.yaml:models:` | Документировано в README |
