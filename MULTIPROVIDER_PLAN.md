# 🔀 SmartRouter v3 — Multi-Provider Architecture [L1-438]

> **Статус:** ✅ **Phase 1 + Phase 2 реализованы (2026-11).** Phase 3–5 — частично, см. таблицу фаз.
> **Цель:** Provider-agnostic роутер. Любой OpenAI-совместимый провайдер подключается через админку, его модели сканируются и назначаются на Coordinator/Worker роли — независимо от провайдера.
>
> **Контракт реализации:** [`docs/PROVIDER_CONTRACT.md`](docs/PROVIDER_CONTRACT.md) — источник правды
> по форматам каталога, ключам `provider::model_id`, валютам и API.

---

## ✅ Принятые решения (согласованы)

| # | Вопрос | Решение | Статус |
|---|--------|---------|--------|
| **Q1** | Формат ключа модели | `provider::model_id` (композитная строка) | ✅ |
| **Q2** | Валюты | Рубли и доллары **раздельно**, конверсия **на лету** (курс в конфиге) | ✅ |
| **Q3** | Секция `models:` в config.yaml | Оставить как **override** цен (ручная цена важнее цены из каталога) | ✅ |
| **Q4** | Провайдер без ключа (Ollama) | Флаг `requires_api_key: false` в конфиге провайдера | ✅ |
| **Q5** | `_active_provider` | Переименовать в `default_provider`; убрать из UI как «переключатель всего» | ✅ |
| **Q6** | `GET /v1/models` для Zed | Отдавать композитные ID (`provider::model`) | ✅ |
| **Q7** | Провайдеры | `routerai`, `openrouter`, `ollama` из коробки; далее — любой OpenAI-compatible | ✅ |
| **Q8** | Хранилище | JSON остаётся (см. раздел «БД или JSON») | ✅ |

### Решения, принятые при реализации (2026-11)

| # | Вопрос | Решение |
|---|--------|---------|
| **D1** | Мёртвый fingerprint-код (~317 строк + тесты) | **Удалён целиком** — код был написан и покрыт тестами, но не вызывался с 2026-07 |
| **D2** | Директория тестов Phase 5 | `tests/phase5/` (`tests/phase4/` уже занят transport+atomic) |
| **D3** | Валюты | `currency.base` / `currency.usd_rate` в конфиге, **без** динамического курса. `total_cost` — в базовой валюте, `by_currency` — в native, `usd_equivalent` — по курсу |
| **D4** | Выдуманные цены в `config.yaml: models:` | Заменены **реальными** из живого каталога; ключи привязаны к провайдеру (`routerai::…`) |
| **D5** | OpenRouter | `pricing_mode: auto` (цены-строки → USD); `extra_headers` для `HTTP-Referer` / `X-Title`; ключ `OPENROUTER_API_KEY` |
| **D6** | Ollama | `models_endpoint: /api/tags` (даёт `context_length` и `capabilities`), `requires_api_key: false`, `pricing_mode: free` |
| **D7** | Провайдеры «из коробки» | Все три в `config.yaml` сразу; форма провайдера в админке дополнена `requires_api_key`, `pricing_mode`, `extra_headers` |
| **D8** | `verify_ssl` | Без изменений: только per-provider, `false` — исключительно при реальном self-signed |

### Решения, принятые по ходу реализации (найдено ручным прогоном)

| # | Проблема | Решение |
|---|----------|---------|
| **D9** | `pricing_units` есть только у RouterAI; у OpenRouter — `null` | Фильтр «за токены»: при наличии `pricing_units` — `prompt == "token"`, иначе — числовые `pricing.prompt`/`completion` и отсутствие `pricing.request` |
| **D10** | `pricing.prompt` — число у RouterAI и строка у OpenRouter | `pricing_mode: auto` определяет валюту по типу значения (строка → USD, число → RUB) |
| **D11** | `/models/sync` уходил **без** `Authorization` → OpenRouter отдавал чужой каталог (435 вместо 399) | Запрос листинга моделей теперь авторизуется |
| **D12** | `output_modalities == ["text"]` строго (не «содержит text») | Отсекает `["image","text"]`, `["text","audio"]` — RouterAI 582 → 351, OpenRouter 415 → 399, Ollama 12 → 10 |

---

## 🗄️ БД или JSON — ответ

### Короткий ответ: **JSON остаётся. БД сейчас избыточна.**

**Почему JSON здесь правильный выбор:**

| Данные | Формат | Почему не БД |
|--------|--------|---------------|
| `routing.json` (роли, маппинги, tuning) | JSON | Должен быть **человекочитаемым** и **в git**. В БД его не поревьюишь diff'ом |
| `config.yaml` (провайдеры, роли) | YAML | То же самое |
| `models_cache.json` (каталог моделей) | JSON | **Регенерируемый кеш** — терять нечего. БД не даёт выигрыша |
| `state.stats` | In-memory | Агрегаты-счётчики. БД нужна только если нужна **история во времени** |

Аргументы «давайте в БД» обычно звучат так: *«а вдруг вырастет»*, *«нужны индексы»*, *«транзакции»*. Но:

- Каталог моделей — это ~400 записей, заменяемых целиком. Индексы не нужны.
- Конфиг пишет **один пользователь** через админку. Конкуренции нет.
- Статистика — **агрегаты** (requests, cost, by_model), не лог событий. Хранить их в БД, чтобы потом запрашивать «за последние 30 дней» — можно, но сейчас никто этого не спрашивает.

### ⚠️ Но нашёл реальный баг — он маскируется под «нужна БД»

Запись конфига **не атомарна**:

```python
# router.py — RouterState._sync_write_config
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

Если процесс убить в момент записи (Ctrl+C во время сохранения из админки) — `routing.json` останется **битым**. А при следующем старте:

```python
# router.py — RouterState._load_config
except Exception as e:
    logger.error(f"Ошибка загрузки {self.config_file}: {e}")
    self._init_default_config()   # ← тихо сбрасывает ВСЁ на дефолты
    migrated = True
```

→ **Все твои назначения моделей молча теряются.** Никакой БД для этого не нужно — нужно 5 строк атомарной записи:

```python
@staticmethod
def _sync_write_config(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)   # атомарно на всех ОС
```

**Это приоритетнее любой БД.**

### 🔀 Когда SQLite станет нужен (триггеры)

| Триггер | Что откроется |
|---------|---------------|
| Хочешь историю расходов по дням/неделям | Таблица `usage_daily(provider, model, date, tokens, cost, currency)` |
| `>1` процесс пишет конфиг одновременно | Нормальные транзакции вместо `asyncio.Lock` |
| История изменений конфига (аудит) | Таблица `config_changes(ts, key, old, new)` |
| >10K моделей × несколько провайдеров с метаданными | Нормальные индексы и полнотекстовый поиск |

**Рекомендация:** JSON сейчас + атомарные записи + SQLite как **P3 с триггерной формулировкой** («перейти на SQLite, когда понадобится история статистики»).

---

## 💱 Валюты — универсальный подход

### Что реально отдают провайдеры

| Провайдер | Формат цены | Валюта | Тип |
|-----------|-------------|--------|-----|
| **RouterAI** | `pricing.prompt = 0.0000157086735` (number) | **₽** | per-token |
| **OpenRouter** | `pricing.prompt = "0.0000025"` (string) | **$** | per-token |
| **Ollama** | поля `pricing` нет | — | free |

Подтверждение валюты RouterAI — из самого API:
```json
{
  "id": "google/lyria-3-pro-preview",
  "description": "Полноформатные песни оцениваются в 8₽ за песню...",
  "pricing": { "request": 8.3778692 }
}
```
Описание говорит «8₽», pricing говорит `8.3778` → **цены в рублях**.

### ⚠️ Баг в текущем коде

```python
# router.py — log_usage()
cost = (input_tokens * price_info["input"] + output_tokens * price_info["output"]) / 1_000_000
state.stats["total_cost"] += cost
# ...
logger.info(f"💰 {model}: In {input_tokens} | Out {output_tokens} | Cost ${cost:.6f}")
```

Цены из кеша — это **₽/1M токенов**, а выводится `$`. Твои логи:
```
minimax/minimax-m3: In 143479 | Out 332 | Cost $4.352001
```
→ На самом деле **4.35 ₽** (~$0.05). А `config.yaml` вообще содержит выдуманные цены:
```yaml
deepseek/deepseek-v4-pro:
  input_price: 0.5      # ← выдумано; реально 131.95 ₽/1M (~$1.50)
```

### Целевая модель

Цена хранится **вместе с валютой**, выводится с символом, конверсия — на лету:

```python
# В каталоге модели:
{
  "id": "deepseek/deepseek-v4-pro",
  "provider": "routerai",
  "input_price_1m": 131.9529,      # ₽
  "output_price_1m": 219.9214,
  "currency": "RUB",
  "price_source": "api"            # api | manual (override из config.yaml)
}

# Статистика:
{
  "total_cost": 4.35,              # в «базовой» валюте (см. ниже)
  "by_currency": { "RUB": 383.12, "USD": 12.45 },
  "usd_equivalent": 17.22,         # по курсу из конфига
  "usd_rate": 90.0                 # 1 USD = 90 ₽ (configurable)
}
```

**Курс — в конфиге**, обновляемый вручную или через API (в Фазе 4):
```yaml
currency:
  base: RUB
  usd_rate: 90.0            # 1 USD = 90 ₽
  rates:
    RUB: 1.0
    USD: 0.0111             # = 1/90
```

### Универсальный pricing-адаптер

Один код на все провайдеры, разница только в режиме:

```python
def parse_pricing(pricing: dict, units: dict, mode: str) -> tuple[float, float, str]:
    """
    Возвращает (input_per_1m, output_per_1m, currency).
    mode: per_token_rub | per_token_usd | free
    """
    if mode == "free":
        return 0.0, 0.0, "NONE"
    prompt = pricing.get("prompt", 0)
    completion = pricing.get("completion", 0)
    if mode == "per_token_usd":
        # OpenRouter: цены приходят строками
        prompt = float(prompt or 0)
        completion = float(completion or 0)
        currency = "USD"
    else:
        # RouterAI: числа, в рублях
        prompt = float(prompt or 0)
        completion = float(completion or 0)
        currency = "RUB"
    # ×1e6 — переводим «за токен» в «за 1M токенов»
    return round(prompt * 1e6, 4), round(completion * 1e6, 4), currency
```

---

## 🏗️ Целевая архитектура

```
┌──────────────────────────────────────────────────────────────┐
│                        SmartRouter                           │
│                                                              │
│  config.yaml                                                 │
│    providers: {routerai, openrouter, ollama}                │
│      ├─ base_url, api_key_env, models_endpoint              │
│      ├─ requires_api_key: bool                              │
│      ├─ pricing_mode: per_token_rub|per_token_usd|free      │
│      └─ default: bool  → default_provider                   │
│    currency: {base, usd_rate, rates}                        │
│    models: {model_id: {provider, prices, currency}} ← OVERRIDE
│                                                              │
│  routing.json                                                │
│    role_models: {coordinator, worker_default, worker_img}    │
│      значения = "provider::model_id"                        │
│    role_fallbacks: {role: "provider::model_id"}             │
│    agent_to_worker_mapping: {agent: "auto"|"provider::model"}│
│                                                              │
│  models_cache.json                                           │
│    providers: {provider: {models: [...], last_sync}}         │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Routing Engine                                    │     │
│  │  1. [AGENT:name] тег → агент → роль → spec          │     │
│  │  2. resolve_spec("provider::model") → (prov, model) │     │
│  │  3. proxy() → base_url[provider] + key[provider]    │     │
│  │  4. body["model"] = model_id  (без префикса!)       │     │
│  │  5. fallback chain: [(prov,model), (prov,model)]    │     │
│  └────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

### Ключевой принцип

> **Провайдер определяется моделью, а не глобальным переключателем.**
> `provider::model_id` — это единица маршрутизации. Всё остальное (fallback, цены,
> контекст, лимиты) — атрибуты этой единицы.

---

## 📦 Фазы реализации

### 🟢 Фаза 1 — Каталог моделей по провайдерам

**Цель:** каждый провайдер синкается отдельно; модели хранятся с привязкой к провайдеру и валюте.

| # | Задача | Файл |
|---|--------|------|
| 1.1 | `state.available_models`: плоский dict → `{"provider::model": info}` | `router.py` |
| 1.2 | Индекс `state.models_by_provider: {provider: [model_ids]}` | `router.py` |
| 1.3 | `get_model_info(provider, model_id)` — новая сигнатура + BC-обёртка | `router.py` |
| 1.4 | `sync_models_from_provider(provider_name)` — убрать хардкод `routerai` | `router.py` |
| 1.5 | **Pricing-адаптеры** (`per_token_rub` / `per_token_usd` / `free`) + валюта | `router.py` |
| 1.6 | **Фильтрация моделей** — оставить только `text→text` (см. ниже) | `router.py` |
| 1.7 | Миграция старого `models_cache.json` (формат `{"models": [...], "provider": "routerai"}`) | `router.py` |
| 1.8 | Новый формат кеша: `{"providers": {provider: {models, last_sync}}}` | `router.py` |
| 1.9 | `POST /models/sync` принимает `{"provider": "..."}` | `router.py` |
| 1.10 | `GET /models/available` → группировка по провайдерам | `router.py` |
| 1.11 | Админка: dropdown провайдера + Sync + колонка Provider | `admin.html` |

#### Фильтрация моделей (находка из реального API)

Сейчас в кеш попадают **все 401 моделей**, включая генерацию картинок, видео, TTS, эмбеддинги и Structured Decision API. Для чат-роутера они бесполезны и засоряют dropdown.

Отсеивать по полям API:
```json
{
  "architecture": {
    "output_modalities": ["text"],       // ← нужны только text-выходящие
    "input_modalities": ["text", "image"]
  },
  "pricing_units": { "prompt": "token", "completion": "token" }
}
```

**Правила:**
- `output_modalities` содержит `text` → в каталог
- `pricing_units.prompt == "token"` → только тарификация за токены (у image/video — за request/image/second)
- `input_modalities` содержит `image` → помечается как `supports_images: true` (для роли `worker_img`)

**Ожидаемый результат:** 401 → ~60–80 релевантных моделей в dropdown вместо 401.

#### Тесты (новый `tests/phase4/`)

- Синк 3 провайдеров на моках httpx → правильные цены и валюты для каждого
- OpenRouter: цена-строка `"0.0000025"` → `2.5` USD/1M
- RouterAI: цена-число `0.0001319528574` → `131.9529` ₽/1M
- Ollama: нет pricing → 0, currency `NONE`
- Фильтрация: image/video/TTS/embedding-модели отброшены
- Миграция старого кеша
- `models_by_provider` индекс корректен

**Риск:** затрагивает `get_model_info` / `get_all_available_models` / `list_models` / `log_usage` — все 4 места правятся в одной фазе.

---

### 🔵 Фаза 2 — Провайдер определяется моделью ⭐ ГЛАВНАЯ

**Цель:** роль → модель любого провайдера; провайдер резолвится автоматически.

| # | Задача | Файл |
|---|--------|------|
| 2.1 | `resolve_model_spec(spec) -> (provider, model_id)` — `provider::model` + BC для голых ID | `router.py` |
| 2.2 | `smart_route_model()` возвращает **композитный** spec | `router.py` |
| 2.3 | **Шаг 1 «уже дешёвая модель»** — если запрошенная модель есть в каталоге, резолвим её провайдера (сейчас возвращается «как есть» без провайдера) | `router.py` |
| 2.4 | `proxy()` — `target_url`/`key_env` берутся у провайдера **модели**, а не `default_provider` | `router.py` |
| 2.5 | `body["model"]` уходит провайдеру **без** префикса `provider::` | `router.py` |
| 2.6 | `log_usage()` — цена по композитному ключу + валюта; убрать фейковую заглушку `{0.50, 1.50}` | `router.py` |
| 2.7 | `routing.json` — новая опция `role_fallbacks` | `router.py` |
| 2.8 | Админка: dropdown ролей → `<optgroup>` по провайдерам, с ценой и валютой | `admin.html` |
| 2.9 | Админка: назначение модели на роль прямо из вкладки Models | `admin.html` |

#### Трассировка BC (обратная совместимость)

| В `routing.json` | Резолвится в |
|------------------|---------------|
| `deepseek/deepseek-v4-pro` | поиск в каталоге → найден у 1 провайдера → он |
| `deepseek/deepseek-chat` | найден у 2 провайдеров → `default_provider` + warning в лог |
| `qwen2.5-coder:7b` (нет в каталоге) | `default_provider` + warning в лог |

#### Результат для пользователя

```
Админка → Providers → добавить Ollama → Save
Админка → Models → выбрать Ollama → Sync → видим qwen2.5-coder:7b
Админка → Agents → Worker (default) = "ollama::qwen2.5-coder:7b" → Save
                                    ↓
Без рестарта. Coordinator → RouterAI. Worker → локальный Ollama. Стоимость Worker = 0.
```

#### Тесты

- `resolve_model_spec`: композит / голый ID (найден у 1 / у 2 / не найден)
- proxy уходит в правильный `base_url` для `provider::model`
- в body провайдеру уходит **чистый** `model_id`
- `body["model"]` не содержит `::`
- переключение роли через `POST /config` → следующий запрос идёт в нового провайдера
- Ollama (`requires_api_key: false`) → запрос проходит без ключа
- Шаг 1: запрошенная `qwen/...` резолвится в провайдера каталога

**Риск:** ломает часть существующих 172 тестов → потребуется правка `tests/conftest.py`, `tests/phase2/test_models.py`, `tests/phase3/test_tuning_proxy.py`.

---

### 🟡 Фаза 3 — Кросс-провайдерный fallback

| # | Задача |
|---|--------|
| 3.1 | Fallback chain как список композитных спецификаций |
| 3.2 | `get_role_fallback_model()` возвращает spec (провайдер + модель) |
| 3.3 | Retry: другой `base_url`, другой ключ, другая модель |
| 3.4 | `fallback_count` в статистике + разбивка по провайдерам |

**Сценарий:** Coordinator на RouterAI упал (5xx) → fallback на `routerai::deepseek-v4-flash` → если и RouterAI лежит → `openrouter::deepseek/deepseek-chat`.

**Тесты:** 5xx у openrouter → уход на routerai; таймаут; все упали → 502; 4xx без fallback.

---

### 🟡 Фаза 4 — Цены, валюты, лимиты

| # | Задача |
|---|--------|
| 4.1 | Валюта из конфига провайдера + из каталога модели |
| 4.2 | Статистика: `by_currency` + `usd_equivalent` по курсу из конфига |
| 4.3 | **Убрать фейковую заглушку** `{0.50, 1.50}` → 0 + пометка «цена неизвестна» |
| 4.4 | `config.yaml models:` → override цены (по решению Q3) |
| 4.5 | Ollama → 0 в статистике (сейчас рисует несуществующие $0.50/$1.50) |
| 4.6 | Авто-обновление курса (опционально, внешний API) |
| 4.7 | `context_length` из каталога → cap `max_tokens` работает для всех провайдеров |

---

### 🟢 Фаза 5 — UX админки

| # | Задача |
|---|--------|
| 5.1 | Кнопка **Test connection** для провайдера (ping `models_endpoint`) |
| 5.2 | Счётчик моделей + время последнего синка у каждого провайдера |
| 5.3 | Вкладка Models: колонки Provider / Model / Context / Price / Currency / Modality |
| 5.4 | Фильтр по провайдеру + поиск по модели |
| 5.5 | Бейдж «vision» для моделей с image-input |
| 5.6 | Переключатель `default_provider` (переименован из `_active_provider`) |
| 5.7 | Показать курс валюты и сумму в USD |

---

## 📊 Сводка

| Фаза | Что даёт | Размер | Риск | Приоритет | Статус |
|------|----------|--------|------|-----------|--------|
| **1** | Синк моделей любого провайдера, фильтрация, валюты | ~200 строк | 🟢 низкий | 🔴 P0 | ✅ 2026-11 |
| **2** ⭐ | Провайдер ← модель. Свободная смена ролей | ~250 строк | 🟡 средний | 🔴 P0 | ✅ 2026-11 |
| **3** | Failover между провайдерами | ~120 строк | 🟡 средний | 🟠 P1 | 🟡 частично |
| **4** | Цены/валюты/лимиты | ~100 строк | 🟢 низкий | 🟠 P1 | 🟡 частично |
| **5** | UX админки | ~250 строк | 🟢 низкий | 🟠 P1 | 🟡 частично |
| **0** | **Атомарные записи конфига** | ~15 строк | 🟢 низкий | 🔴 **P0** | ✅ 2026-11 |

---

## 🔀 Рекомендуемый порядок

### Спринт 1: «Провайдер-agnostic ядро» ✅ ЗАВЕРШЁН (2026-11)
**Фаза 0 + Фаза 1 + Фаза 2**

Обоснование: Фаза 1 без Фазы 2 не даёт пользовательской ценности (модели сканируются, но не назначаются). Фаза 0 (атомарные записи) — 15 строк, закрывает реальную потерю данных, и её логично делать первым коммитом.

**Итог спринта — достигнут и проверен на живых API:**
> Добавил OpenRouter и Ollama через админку → Sync → вкладка Models показывает модели всех трёх провайдеров с ценами и валютами → вкладка Agents: Coordinator = `routerai::minimax/minimax-m3`, Worker = `ollama::qwen3.5:9b` → Save → **без рестарта**: Coordinator на RouterAI, Worker локально и бесплатно.

Подтверждено прогоном: `[AGENT:database]` → `POST http://localhost:11434/v1/chat/completions` → `200 OK`,
`Cost 0.0000 NONE`, `by_model: {"ollama::qwen3.5:9b": …}`.

### Спринт 2: «Отказоустойчивость и деньги» 🟡 ЧАСТИЧНО
**Фаза 3 + Фаза 4**

> RouterAI упал → автоматический уход на OpenRouter (или на flash). Статистика показывает рубли и доллары отдельно + эквивалент в USD.

Сделано: валюты, `by_currency`, `usd_equivalent`, ручные override'ы с привязкой к провайдеру,
и цепочка fallback уже умеет уходить на другого провайдера (проверено: OpenRouter 503 → RouterAI 200 OK).
Осталось: явная логика 5xx/таймаутов, UI для `role_fallbacks`, авто-курс, лимиты.

### Спринт 3: «Полировка» ⏳
**Фаза 5** + rate limiting + structured logging.

---

## ✅ Definition of Done (для каждой фазы)

1. Код написан, минимальный дифф
2. Новые тесты в `tests/phase5/` — все зелёные
3. Все существующие тесты зелёные (**243 на момент завершения Phase 1+2**)
4. Ручная проверка через админку / API (сценарий записан в README)
5. `git commit` + `push origin main`
6. README/ROADMAP обновлены

---

## ❓ Открытые вопросы

| # | Вопрос | Статус / решение |
|---|--------|------------------|
| A | Как хранить курс валют? | ✅ `config.yaml` (`currency.usd_rate`), ручное обновление. Авто-обновление — Phase 4.6, опционально |
| B | RouterAI отдаёт USD-цены? | ✅ **Нет** — цены в рублях (числа). Разделение сделано через `pricing_mode: auto` по типу значения |
| C | Фильтровать не-текстовые модели? | ✅ Да, строго `output_modalities == ["text"]` + тарификация за токены |
| D | Нужны ли `default_provider` вообще? | ✅ Да, как fallback для голых ID в `routing.json` и для моделей вне каталога |
| E | Где хранить `models:` override-цены | ✅ В `config.yaml`, с полем `currency`; ключ может быть глобальным или `provider::model` |
| F | Что с каталогом без авторизации? | ✅ `/models/sync` авторизуется — иначе OpenRouter отдаёт каталог, недоступный пользователю |
| G | Нужен ли SQLite? | ⏳ Нет. JSON + атомарные записи. Переход — по триггерам (история затрат, >1 писатель, аудит, >10K моделей) |

---

*План создан 2026-07-01 на основе реального API RouterAI.
Phase 1 + Phase 2 реализованы 2026-11-02 (см. `docs/PROVIDER_CONTRACT.md` и `ROADMAP.md`).*
