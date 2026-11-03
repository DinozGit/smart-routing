# 📐 Контракт мультипровайдерного каталога (Спринт 1)

> **Единый источник правды для всех агентов спринта.** Одиннадцать агентов работают
> параллельно над непересекающимися write scope — этот файл фиксирует форматы,
> чтобы они не разъехались.
>
> Проверено против **живых API** 2026-11-02.

---

## 0. Факты о провайдерах (проверено вживую)

| Провайдер | models_endpoint | Формат ответа | `pricing.prompt` | `pricing_units` | Валюта | Моделей всего | После фильтра |
|-----------|-----------------|---------------|------------------|------------------|--------|---------------|---------------|
| **routerai** | `https://routerai.ru/api/v1/models` | `{"data":[...]}` | **number** (JSON) | есть: `{"prompt":"token","completion":"token"}` | **₽** | 582 | **350** |
| **openrouter** | `https://openrouter.ai/api/v1/models` | `{"data":[...]}` | **string** (`"0.00000037"`) | **null** | **$** | 415 | **399** |
| **ollama** | `http://localhost:11434/api/tags` | `{"models":[...]}` | нет поля `pricing` | нет | **free** | 12 | **10** |

**Ключевые факты:**

1. `pricing_units` есть **только у RouterAI**. У OpenRouter — `null`. Фильтр «тарификация за токены»
   для OpenRouter определяется по наличию числовых `pricing.prompt`/`pricing.completion` и
   отсутствию `pricing.request`.
2. RouterAI отдаёт цены **числами в рублях за токен**. OpenRouter — **строками в долларах за токен**.
   Это и есть два режима pricing-адаптера.
3. `output_modalities` у RouterAI: `["text"]` 350, `["image"]` 51, `["speech"]` 36,
   `["embeddings"]` 35, `["video"]` 31, `["transcription"]` 29, `["decisions"]` 28,
   `["image","text"]` 10. У OpenRouter: `["text"]` 399, `["image","text"]` 10,
   `["text","audio"]` 4, `["text","image"]` 2.
4. У Ollama `/api/tags` даёт `details.context_length` и `capabilities`
   (`["completion","vision","tools","thinking"]`), а `/v1/models` — только `id`.
   **Берём `/api/tags`**, он информативнее.
5. У OpenRouter 15 моделей с `pricing.prompt == "0"` — это бесплатные (`*:free`), не ошибка.

---

## 1. Конфиг провайдера (`config.yaml` → `providers:`)

```yaml
providers:
  routerai:
    display_name: RouterAI
    base_url: https://routerai.ru/api/v1/chat/completions
    models_endpoint: https://routerai.ru/api/v1/models
    api_key_env: ROUTERAI_KEY
    requires_api_key: true
    pricing_mode: auto          # auto | per_token_rub | per_token_usd | free
    default: true
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
    verify_ssl: true
    ca_bundle: ""
    extra_headers:
      HTTP-Referer: https://github.com/smart-routing/smart-router
      X-Title: SmartRouter
  ollama:
    display_name: Ollama (local)
    base_url: http://localhost:11434/v1/chat/completions
    models_endpoint: http://localhost:11434/api/tags
    api_key_env: ""
    requires_api_key: false
    pricing_mode: free
    default: false
    verify_ssl: true
    ca_bundle: ""
    extra_headers: {}
```

| Поле | Назначение | Обязательное? |
|------|-----------|---------------|
| `base_url` | URL чат-комплишена | да |
| `models_endpoint` | URL листинга моделей | да |
| `api_key_env` | Имя env-переменной с ключом | если `requires_api_key: true` |
| `requires_api_key` | `false` → прокси не требует ключ (Ollama) | нет (default `true`) |
| `pricing_mode` | `auto` — определить по типу `pricing`; остальные — принудительно | нет (default `auto`) |
| `default` | Провайдер по умолчанию (fallback для bare-ID) | нет |
| `verify_ssl` | Проверка TLS | нет (default `true`) |
| `ca_bundle` | Путь к своему CA | нет |
| `extra_headers` | Доп. заголовки запроса (dict) | нет |

### 1.1 `pricing_mode: auto` — правило автоопределения

| Условие | Результат |
|----------|-----------|
| `pricing.prompt` — **строка** (OpenRouter-стиль) | `per_token_usd`, валюта `USD` |
| `pricing.prompt` — **число** (RouterAI-стиль) | `per_token_rub`, валюта `RUB` |
| поля `pricing` нет вообще (Ollama) | `free`, валюта `NONE` |

Явные `per_token_rub` / `per_token_usd` / `free` перекрывают автоопределение.

---

## 2. Конфиг валют (`config.yaml` → `currency:`)

```yaml
currency:
  base: RUB
  usd_rate: 90.0        # 1 USD = 90 ₽ — ЕДИНСТВЕННЫЙ источник курса
```

**Семантика (однозначно):** `usd_rate` — сколько единиц **базовой** валюты стоит 1 USD.
`base` — валюта, в которой считается `stats["total_cost"]`.

> ⚠️ Секции `currency.rates` больше **нет** — раньше она была инвертирована относительно
> `usd_rate` (`USD: 0.011111` = «USD за 1 ₽» использовалось как «₽ за 1 USD»), из-за чего
> `total_cost` для USD-моделей занижался в 8100 раз. Если появится валюта кроме RUB/USD —
> её курс задаётся **опциональной** картой `currency.rates` с той же семантикой
> («сколько ₽ стоит 1 единица»): `rates: {CNY: 12.5}` → 1 CNY = 12.5 ₽.

### Перевод в базовую валюту

| Валюта | Фактор (сколько ₽ стоит 1 единица) |
|--------|-------------------------------------|
| `RUB` (базовая) | `1.0` |
| `USD` | `usd_rate` (90.0) |
| `NONE` (бесплатно) | `1.0` (цена 0) |
| прочие | из `currency.rates`, иначе `1.0` + warning |

---

## 3. Запись каталога модели

```json
{
  "id": "deepseek/deepseek-v4-pro",
  "provider": "routerai",
  "name": "DeepSeek V4 Pro",
  "description": "...",
  "context_length": 1048576,
  "input_price_1m": 61.9626,
  "output_price_1m": 123.9251,
  "currency": "RUB",
  "price_source": "api",
  "supports_images": false,
  "input_modalities": ["text"],
  "output_modalities": ["text"],
  "supported_parameters": ["temperature", "tools"],
  "pricing_units": { "prompt": "token", "completion": "token" }
}
```

| Поле | Тип | Правило |
|------|-----|---------|
| `input_price_1m` / `output_price_1m` | float | цена **за 1M токенов** = `price_per_token × 1e6`, округление до 4 знаков |
| `currency` | `"RUB"` / `"USD"` / `"NONE"` | из `pricing_mode`; `NONE` — бесплатная модель |
| `price_source` | `"api"` / `"manual"` / `"unknown"` | `manual` — переопределено в `config.yaml: models:` |
| `supports_images` | bool | `"image" in input_modalities` |
| `pricing_units` | dict | сохраняем как есть (у OpenRouter `null`) |

> ⚠️ **`supports_images` — не косметика.** Модель без поддержки изображений
> возвращает от провайдера `400 Model '...' does not support image input`,
> если запрос пришёл со скриншотом. Роли подбираются по тому, что они реально
> получают: vision нужен координатору (скрины) и `worker_img` (дизайн),
> а `worker_default` (backend, тесты, devops) читает только код.
>
> Пример из реального прогона: координатор на `routerai::deepseek/deepseek-v4-pro`
> получал `400` на каждом запросе со скриншотом — модель не поддерживает картинки.

---

## 4. Ключ модели — `provider::model_id`

- `state.available_models: Dict[str, dict]` — ключ **составной**: `"routerai::deepseek/deepseek-v4-pro"`.
- `state.models_by_provider: Dict[str, List[str]]` — provider → список **голых** `model_id`.
- `state.provider_last_sync: Dict[str, float]` — provider → время последнего синка.

> `::` не встречается в ID моделей — разделитель безопасен.

### 4.1 BC-обёртки

```python
get_model_info(model_id: str, provider: str | None = None) -> dict | None
```
- `provider` задан → точный поиск по `"provider::model_id"`.
- `provider` не задан → поиск по всем провайдерам; при нескольких совпадениях
  приоритет у `default_provider`, иначе — первый по алфавиту.

**Порядок поиска (строго):**

1. точное совпадение `"provider::model_id"` в `state.available_models`;
2. **BC-fallback:** если `model_id` есть в `state.available_models` как есть
   (старый плоский dict, оставшийся от v1) → вернуть его;
3. поиск по всем провайдерам: собрать `"<prov>::<model_id>"` для каждого
   `prov` из `state.models_by_provider`; при нескольких совпадениях —
   приоритет у `default_provider`, иначе первый по алфавиту;
4. не найдено → `None`.

> Пункт 2 обязателен: он позволяет старым плоским словарям (из фикстур тестов
> и из старых кешей) продолжать работать без правки.

---

## 5. Фильтрация моделей

**Правило (строгое): модель попадает в каталог, если:**

1. `architecture.output_modalities == ["text"]` — **ровно** text, без примесей
   (`["image","text"]`, `["text","audio"]` — отбрасываем);
2. тарификация за токены:
   - `pricing_mode == free` → всегда да;
   - `pricing_units` присутствует → `pricing_units.prompt == "token"` **и**
     `pricing_units.completion == "token"`;
   - `pricing_units` отсутствует (OpenRouter) → `pricing.prompt` и `pricing.completion`
     успешно приводятся к float **и** `pricing.request` отсутствует/равен 0.

**Ожидаемый результат:** routerai 582 → **350**, openrouter 415 → **399**, ollama 12 → **10**.

**Ollama** (`/api/tags`) — особый случай, т.к. формат отличается:
- `name` → `id` модели; `model` — дубликат, игнорируем.
- `details.context_length` → `context_length`.
- `capabilities`: наличие `"completion"` → text-выходящая; `"vision"` → `supports_images: true`;
  `"embedding"` **без** `"completion"` → **отбрасываем** (эмбеддинги: `qwen3-embedding:4b`,
  `nomic-embed-text:latest`).
- `pricing` отсутствует → `input_price_1m = 0`, `output_price_1m = 0`, `currency = "NONE"`.

**Формат ответа провайдера** — определяется по наличию ключа:
- `data` → список OpenAI-совместимый (`routerai`, `openrouter`);
- `models` → формат Ollama (`/api/tags`).

---

## 6. Pricing-адаптер

```python
def parse_pricing(pricing: dict, pricing_units: dict | None, mode: str) -> tuple[float, float, str]:
    """
    mode: auto | per_token_rub | per_token_usd | free
    Возвращает (input_per_1m, output_per_1m, currency).
    """
```

| `mode` | currency | Что делает |
|--------|----------|-----------|
| `free` | `"NONE"` | `0.0, 0.0` |
| `per_token_usd` | `"USD"` | `float(str(pricing["prompt"])) × 1e6` — OpenRouter (строки) |
| `per_token_rub` | `"RUB"` | `float(pricing["prompt"]) × 1e6` — RouterAI (числа) |
| `auto` | по типу | `prompt` строка → `USD`, число → `RUB`, нет `pricing` → `NONE` |

Округление: `round(value, 4)`. Строки-цены **обязаны** приводиться через `float(str(...))` —
`float("0.00000037")` работает, `float(None)` — нет.

---

## 7. Формат кеша (`models_cache.json`)

### v2 (новый)

```json
{
  "version": 2,
  "providers": {
    "routerai": {
      "last_sync": 1789642911.0,
      "models": {
        "deepseek/deepseek-v4-pro": { /* запись каталога, п.3 */ }
      }
    }
  }
}
```

### Миграция с v1

v1: `{"models": [ {...}, ... ], "last_sync": ..., "provider": "routerai"}`.

При загрузке v1:
1. все модели кладутся в `providers["routerai"]["models"]` (имя берётся из `data["provider"]`,
   по умолчанию `"routerai"`);
2. к каждой модели проставляется `provider` и `currency` (`"RUB"` для routerai);
3. применяется фильтр по `output_modalities == ["text"]` (в v1 кеше `pricing_units` нет,
   поэтому фильтр «за токены» при миграции **не применяется**);
4. в лог — предупреждение: «кеш мигрирован с v1, выполните Sync для полной фильтрации».

Миграция **не должна** требовать вмешательства пользователя и **не должна** ронять старт.

---

## 8. Эндпоинты

### `sync_models_from_provider`

```python
async def sync_models_from_provider(self, provider_name: str | None = None) -> dict:
    """
    provider_name=None → синк всех провайдеров (каждый в своём try/except).
    Возвращает:
        {"status": "ok"|"error",
         "results": {provider: {"status": "ok"|"error", "synced": N, "last_sync": ts, "error": str?}},
         "synced": N,      # сумма по успешным
         "last_sync": ts}  # максимум по успешным
    """
```

- Каждый провайдер обрабатывается в собственном `try/except` — падение одного
  **не** прерывает синк остальных.
- Провайдер без `models_endpoint` → `status: "error"`, `error: "models_endpoint не настроен"`.
- Провайдер без `api_key` (и `requires_api_key: true`) → `status: "error"` с внятным текстом.

### `POST /models/sync`

Тело (опционально): `{"provider": "openrouter"}`.
- без `provider` → синк **всех** провайдеров;
- с `provider` → только он.

Ответ `200`:
```json
{
  "status": "ok",
  "results": {
    "routerai":   { "status": "ok",    "synced": 350, "last_sync": 1789642911.0 },
    "openrouter": { "status": "ok",    "synced": 399, "last_sync": 1789642911.0 },
    "ollama":     { "status": "error", "synced": 0,   "error": "Connection refused" }
  },
  "synced": 749,
  "last_sync": 1789642911.0
}
```

**BC-требование (важно!):** эндпоинт обязан корректно обрабатывать результат,
который **не содержит** ключей `status`/`results` (например, замоканный в тестах
`{"synced": 10, "last_sync": 999}`). Логика:

```python
result = await state.sync_models_from_provider(provider)
payload = {"status": result.get("status", "ok"), **result}
```
- `ValueError` → HTTP **400**;
- любой прочит exception → HTTP **502**;
- `payload["status"] == "error"` → HTTP **502** с `detail=payload`.

### `GET /models/available?refresh=true`

```json
{
  "providers": {
    "routerai": {
      "last_sync": 1789642911.0,
      "count": 350,
      "models": [ /* записи каталога */ ]
    }
  },
  "models": [ /* плоский список записей, с полем provider */ ],
  "last_sync": 1789642911.0
}
```
`models` верхнего уровня — **BC** (старый админ и тесты читают плоский список).

---

## 9. Резолв спецификации модели (Phase 2)

```python
resolve_model_spec(spec: str) -> tuple[str, str]:
    """Возвращает (provider, model_id)."""
```

| Вход | Поведение |
|------|-----------|
| `"openrouter::deepseek/deepseek-chat"` | `("openrouter", "deepseek/deepseek-chat")` |
| `"deepseek/deepseek-v4-pro"` (в каталоге у 1 провайдера) | этот провайдер |
| `"deepseek/deepseek-chat"` (в каталоге у 2 провайдеров) | `default_provider` + **warning в лог** |
| `"qwen2.5-coder:7b"` (нет в каталоге) | `default_provider` + **warning в лог** |
| `"unknown::model"` (нет такого провайдера) | `default_provider` + **warning в лог** |

`smart_route_model()` возвращает **составную** спецификацию `"provider::model_id"`.

**Шаг 1 «уже дешёвая модель»** (`flash`/`qwen` в имени) — тоже резолвится в составной вид
через каталог, а не возвращается «как есть».

### 9.1 Явная спецификация клиента — точное указание

Если **клиент** прислал `"provider::model"` и провайдер известен — это явное указание:

- модель и провайдер используются **как есть**;
- ролевые настройки **не применяются**: ни префикс system prompt, ни дефолты
  температуры, ни fallback chain.

```python
if "::" in requested_model and requested_model.split("::", 1)[0] in state.providers:
    return requested_model, "", "Явная спецификация провайдера"
```

| Источник запроса | Поведение |
|---|---|
| Клиент прислал `provider::model` | уважается буквально, без маршрутизации |
| Клиент прислал голое имя (`SmartAuto`) | обычная агентная маршрутизация по `[AGENT:name]` |
| Неизвестный провайдер в префиксе (`foo::bar`) | обычная маршрутизация → `default_provider` + warning |

**Зачем:** без этого правила любая модель без «flash»/«qwen» в имени перетиралась
на coordinator-модель, а в system prompt вставлялся префикс делегирования —
обычный OpenAI-клиент (Cline, Continue, Cursor) от этого ломался.

**Zed не затронут:** он присылает голое имя (`SmartAuto`), поэтому агентная
маршрутизация по тегу работает как прежде.

---

## 10. Проксирование (Phase 2)

```python
provider, model_id = resolve_model_spec(spec)
target_url = state.providers[provider]["base_url"]
api_key = os.getenv(state.providers[provider].get("api_key_env", ""), "")
if state.providers[provider].get("requires_api_key", True) and not api_key:
    → HTTP 502 "Missing API key: <env>"
body["model"] = model_id      # ← БЕЗ префикса "provider::"
```

- Заголовки: `Authorization: Bearer <key>` (если ключ есть) + `Content-Type` +
  `extra_headers` провайдера (если заданы).
- `requires_api_key: false` → запрос проходит **без** `Authorization`.

---

## 11. Учёт стоимости (Phase 2 + Phase 4-часть)

```python
state.stats = {
    "requests": 0,
    "total_input": 0,
    "total_output": 0,
    "total_cost": 0.0,          # в базовой валюте (currency.base)
    "currency": "RUB",          # код базовой валюты
    "usd_rate": 90.0,           # 1 USD = 90 ₽
    "by_currency": {},          # {"RUB": 383.12, "USD": 12.45} — в native-валютах
    "usd_equivalent": 0.0,      # native-USD: USD-сумма как есть, RUB / usd_rate
    "by_model": {},             # ключ — составная спецификация
    "routed_count": 0,
    "not_routed_count": 0,
    "fallback_count": 0,
}
```

**Порядок поиска цены** (по ключу-спецификации `"provider::model"`):
1. `config.yaml models:` с составным ключом — ручной override **для этого провайдера**
   (`price_source = "manual"`);
2. `config.yaml models:` с голым ключом — общий ручной override (`price_source = "manual"`);
3. каталог **этого провайдера** — `get_model_info(model_id, provider)` (`price_source = "api"`);
4. каталог без провайдера — `get_model_info(model_id)` (BC-фолбэк);
5. ничего не найдено → цена `0`, `price_source = "unknown"`, в лог — предупреждение.

> ⚠️ Пункт 3 обязателен **до** пункта 4: одна и та же модель может быть у нескольких
> провайдеров с **разными ценами и валютами** (например `z-ai/glm-5.2`:
> 8.17 ₽ у RouterAI и 0.006 $ у OpenRouter). Без провайдера цена бралась бы у чужого —
> ошибка до **1136 раз**.

> **Фиктивная заглушка `{0.50, 1.50}` удалена полностью.**

> **Псевдо-валюта `NONE`.** Бесплатные модели (провайдер с `pricing_mode: free`,
> например Ollama) имеют `currency: "NONE"`. Это не валюта, а отсутствие затрат:
> - в `by_currency` такая модель **не создаёт запись** (иначе в UI появлялось `NONE 0.00`);
> - `total_cost` не увеличивается;
> - `usd_equivalent` не увеличивается.

Лог стоимости: `💰 {spec}: In {in} | Out {out} | Cost {cost:.4f} {currency}`
— **без** жёсткого `$`.

---

## 12. `GET /v1/models`

**Phase 1** — формат не меняется: OpenAI-совместимый список, `id` берётся из
поля `id` записи каталога (то есть **голый** `model_id`, без префикса).
Дедупликация — по `id`. Это сохраняет обратную совместимость с текущей админкой.

**Phase 2** — `id` становится **составным**: `"provider::model_id"` (решение Q6).

---

## 13. Write scope по агентам (Спринт 1)

| Агент | Write scope | Фаза |
|-------|-------------|------|
| `api` | `router.py` | Phase 1 → Phase 2 |
| `devops` | `config.yaml` | Phase 1 |
| `frontend` | `admin.html` | Phase 1 → Phase 2 |
| `tests` | `tests/phase5/`, правка существующих тестов | Phase 1 → Phase 2 |
| Coordinator | `docs/`, `README.md`, `SECURITY.md` | ревью + доки |

**Никто не трогает чужие файлы.**

---

# 📐 Контракт спринта «Багфиксинг F1–F7» (2026-11)

> **Этот раздел — нормативный.** Все агенты спринта реализуют **ровно** эти
> форматы, имена полей и семантику. Не отклоняться без согласования с
> координатором: агенты работают параллельно, write scope не пересекается,
> но API/UI/тесты должны сходиться в точке.
>
> **Контекст.** Жалоба пользователя: «откуда-то подтягивается ключ openrouter
> и туда стучится… даже после удаления по логам видно что он туда ломится».
> Разбор показал 5 механизмов (см. `docs/ROADMAP.md`, спринт «Багфиксинг F1–F7»).
> Ключевое: **реальных ключей в репозитории нет** (в истории git только
> плейсхолдеры) — проблема в том, что SmartRouter **сам, неявно**, выбирает
> OpenRouter, и при этом **не даёт ключ отозвать**.

---

## F1. `allow_cross_provider_bare_id` — запрет неявного кросс-провайдерного резолва

### Проблема

`resolve_model_spec(spec)` для **голого** `model_id` (без `provider::`) ищет
модель по каталогу **всех** провайдеров. В каталоге 73 модели, которые есть
**только** у `openrouter`; 11 из них содержат `flash` или `qwen` и попадают в
эвристику `router.py:1049` → `_normalize_to_composite()` → `resolve_model_spec()`
→ уникальный кандидат `openrouter` → запрос уходит на OpenRouter **с ключом
пользователя**, который OpenRouter не выбирал.

### Контракт

**Где живёт флаг:** `routing.json` (runtime-конфиг, hot-reload через `POST /config`).

```json
{
  "allow_cross_provider_bare_id": false
}
```

- **Значение по умолчанию — `false`** (fail-closed). Если ключа нет в
  `routing.json` → `false`. Действует **только** при отсутствии ключа явно.
- Читается **на каждый вызов** из `state.config` (не кэшируется) → переключается
  без перезапуска роутера.
- `true` → старое поведение (поиск по всем провайдерам) — для тех, кому нужен
  кросс-провайдерный подбор по голому ID.

### Новая семантика `resolve_model_spec(spec, source)`

Сигнатура меняется:

```python
def resolve_model_spec(spec: str, source: str = "client") -> tuple[str, str]:
```

`source` — контекст вызова:

| `source` | Кто вызывает | Семантика для голого ID |
|---|---|---|
| `"client"` | запрос от IDE/клиента (`proxy()`, `smart_route_model()` для клиентской модели) | **не пересекает провайдеров**: ищется **только** в каталоге `default_provider`; не найдено → `default_provider` |
| `"config"` | операторский конфиг: `roles.*.default_model` в `config.yaml`, `role_models`/`role_fallbacks`/`agent_to_worker_mapping` в `routing.json` | поиск по каталогу всех провайдеров (текущее поведение) — оператор явно выбрал модель |

> **Важно:** для `source="config"` поведение **не меняется**. Это защищает
> существующие инсталляции, где роль настроена на модель, доступную только у
> другого провайдера.

**Алгоритм для `source="client"`, голый ID:**

1. Если `allow_cross_provider_bare_id` == `true` → текущий алгоритм (поиск по
   всем провайдерам; единственный кандидат → он; несколько → `default_provider`
   + WARNING; ноль → `default_provider` + WARNING).
2. Иначе (`false`):
   - если ID есть в каталоге `default_provider` → `default_provider`;
   - если ID есть **только** у другого провайдера → `default_provider`
     + **INFO-лог** (см. F5);
   - если ID не найден нигде → `default_provider` + WARNING (как сейчас).

**Явная спецификация `provider::model` не меняется** — это точное указание
пользователя, оно всегда уважается (кроме правила F2 про `enabled`).

### `_normalize_to_composite`

```python
def _normalize_to_composite(model_id: str, source: str = "client") -> str:
```

- `source` пробрасывается в `resolve_model_spec`.
- **Критично:** вызовы с конфигом ролей (`config.yaml: roles.*.default_model`,
  `routing.json: role_models`) → `source="config"`.
- Вызов с **клиентским** `requested_model` (`router.py:1049`) → `source="client"`.

### Куда какой `source` передавать (обязательно к следованию)

| Место | `source` |
|---|---|
| `router.py:1050` — `_normalize_to_composite(requested_model)` (клиент без `::`) | `"client"` |
| `router.py:1060`, `1120`, `1129` — `_normalize_to_composite(coord_model)` (роль) | `"config"` |
| `router.py:1093`, `1102` — `_normalize_to_composite(model)` (agent mapping / роль) | `"config"` |
| `router.py:1653` — `resolve_model_spec(spec)` в `proxy()` | `"client"` |
| `router.py:1826` — `resolve_model_spec(chain_spec)` (цепочка fallback) | `"config"` |

---

## F2. `enabled` — провайдер можно выключить

### Где живёт флаг

`config.yaml` → `providers.<name>.enabled` (bool).

```yaml
providers:
  routerai:
    enabled: true
  openrouter:
    enabled: false     # ← провайдер выключен
  ollama:
    enabled: true
```

- **Значение по умолчанию — `true`** (BC: у провайдера без поля `enabled`
  провайдер считается включённым). Так старые `config.yaml` продолжают работать.
- `state.providers` — живой dict (`router.py:203`), поэтому переключение
  через админку применяется **сразу, без перезапуска**.
- `default_provider` **нельзя выключить** — попытка → `HTTP 400`.

### Что делает `enabled: false`

| Место | Поведение |
|---|---|
| `_sync_all_providers()` | провайдер **пропускается**, в `results` — запись `{"status": "skipped", "reason": "disabled"}`, **не** `"error"` |
| `POST /models/sync` (без `provider`) | пропускается, как выше |
| `POST /models/sync {"provider": "X"}` для выключенного | `HTTP 409`, detail `"Provider 'X' is disabled"` |
| `GET /v1/models` | модели выключенного провайдера **не выдаются** |
| `GET /models/available` | провайдер присутствует в ответе, но `"enabled": false` и `"models": []` |
| Fallback-цепочка | запись цепочки, чей провайдер выключен → **пропускается** (как «no key»), с логом `⚠️ Fallback skip (provider disabled)` |
| Явный запрос `disabled::model` | `HTTP 400`, detail `"Provider 'X' is disabled"` |
| `GET /providers` | в ответе **обязательно** поле `"enabled": bool` |

> **Почему не просто «удалить провайдера»:** удаление стирает `base_url`,
> `api_key_env`, `pricing_mode` и настройки SSL — восстановить их потом можно
> только вручную. `enabled: false` — обратимый выключатель.

### Запись флага через API

`POST /providers` принимает новое поле:

```json
{ "name": "openrouter", "enabled": false, ... }
```

- Значение `enabled` **обязательно** присутствует в ответе `POST /providers`
  (по умолчанию `true`).
- `POST /providers` сохраняет `enabled` в `config.yaml` через существующий
  `save_config_yaml()`.

---

## F3. `DELETE /providers/{name}/key` — отзыв ключа

### Проблема

Сейчас ключ можно **только записать** (`POST /providers` → `set_env_key`).
Удаления ключа нет вообще. А удаление строки из `.env` **не действует на
запущенный процесс**: `load_dotenv()` при импорте (`router.py:28`) вызывается
**без** `override=True`, поэтому (а) переменная окружения **побеждает** файл
`.env`, и (б) уже загруженный ключ остаётся в `os.environ` до перезапуска.

### Контракт

**Эндпоинт:**

```
DELETE /providers/{name}/key
```

**Ответ `200`:**

```json
{
  "status": "ok",
  "provider": "openrouter",
  "api_key_env": "OPENROUTER_API_KEY",
  "key_removed": true,
  "env_cleared": true
}
```

- `key_removed` — `true`, если строка была удалена из `.env`; `false`, если её
  там не было (но `env_cleared` всё равно может быть `true`).
- `env_cleared` — `true`, если переменная была удалена из `os.environ` **текущего
  процесса**.

**Поведение:**

1. Удаляет строку `KEY=` из файла `.env` (атомарная запись, существующий
   `_atomic_write`). Если `.env` не существует — `key_removed: false`.
2. **`os.environ.pop(api_key_env, None)`** — ключ исчезает из текущего процесса
   **без перезапуска**.
3. `GET /providers` после удаления → `has_api_key: false`, `api_key_masked`
   отсутствует.
4. Если `api_key_env` пустой (провайдер без ключа, например Ollama) →
   `HTTP 400`, detail `"Provider 'X' does not use an API key"`.
5. Если провайдер не найден → `HTTP 404`.
6. Удаление ключа **не трогает** провайдера, его `base_url` и прочее.

> **Важно:** после `os.environ.pop()` переменная окружения может вернуться при
> перезапуске процесса, если она экспортирована в системе/профиле. Это
> ожидаемо и не чинится роутером.

---

## F4. Sync-all — только включённые провайдеры

- `_sync_all_providers()` (`router.py:630`) обходит **только** провайдеров с
  `enabled != false`.
- Для выключенного провайдера в `results`:
  ```json
  "openrouter": {"status": "skipped", "reason": "disabled", "synced": 0, "last_sync": null}
  ```
- Лог — **INFO**, не ERROR: `⏭️ Провайдер 'openrouter' выключен — синк пропущен`.
- Итоговый `status` ответа `/models/sync` — `"ok"` (ошибок нет, есть пропуск).
- `GET /models/available?refresh=true` использует тот же `_sync_all_providers()`
  → выключенные провайдеры не опрашиваются.

---

## F5. Лог выбора провайдера

Цель — чтобы в логах было видно, **почему** запрос ушёл в конкретного
провайдера. Обязательные сообщения (уровень **INFO**):

| Ситуация | Сообщение |
|---|---|
| Голый ID ушёл в `default_provider` при `allow_cross_provider_bare_id=false` | `🔒 Голый ID '{model}' доступен только у провайдеров {candidates} — используется default '{default_provider}' (routing.allow_cross_provider_bare_id=false)` |
| Голый ID однозначно найден в каталоге | `📍 Модель '{model}' → провайдер '{provider}' (источник: каталог)` |
| Явный `provider::model` | `📍 Модель '{model}' → провайдер '{provider}' (источник: явное указание)` |

- Сообщения пишутся **один раз на запрос**, а не на каждый внутренний вызов
  (иначе INFO-лог засорится).
- Уровень логирования — `INFO` (совпадает с `logging.level` из `config.yaml`).

---

## F6. UI админки (`admin.html`)

### Вкладка «🔌 Providers» — таблица провайдеров

Добавить **колонку «Enabled»** с тумблером (checkbox) у каждого провайдера:

| Провайдер | Enabled | Ключ | Действия |
|---|---|---|---|
| RouterAI | ☑ | `sk-IbE****3f2a` | Edit · Delete · **Remove key** |
| OpenRouter | ☐ | — | Edit · Delete · **Remove key** |

### Требования к UI

1. **Тумблер Enabled** → `POST /providers` с полным набором полей провайдера +
   `"enabled": <bool>`. После ответа — перерисовка списка.
2. **Кнопка «Remove key»** → `DELETE /providers/{name}/key` + подтверждение.
   После ответа — обновить колонку «Ключ».
3. **Бейдж статуса ключа**: `has_api_key === true` → маска; `false` → «нет ключа».
4. **Предупреждение** (визуальное, без модалок), если провайдер `enabled` и у него
   `has_api_key === false` → текст вида:
   `⚠️ Включён, но без ключа — запросы к нему будут падать с 502`.
5. Выключенный провайдер — визуально приглушён (например, `opacity: 0.5`),
   его модели **не** показываются в списке моделей (`GET /models/available`
   отдаёт для него `"models": []`).
6. Все строки, вставляемые в DOM через `innerHTML`, экранируются существующей
   функцией `escapeHtml()`.

### Вкладка «📦 Models»

- В выпадающих списках выбора модели (`<optgroup>`) **не должно** быть моделей
  выключенных провайдеров (данные приходят из `/models/available` — достаточно
  отфильтровать по `providers[p].enabled === false`).

### Новый эндпоинт — только `api`

UI **не** реализует собственную логику удаления ключа — только вызывает
`DELETE /providers/{name}/key`.

---

## F7. Тесты (`tests/phase6/`)

Новая директория `tests/phase6/` + свой `conftest.py` (по образцу
`tests/phase5/`). Тесты **не ходят в сеть** — HTTP-клиент мокается.

### Обязательный список

| # | Тест | Что проверяет |
|---|---|---|
| 1 | `test_bare_id_stays_in_default_provider` | Голый ID, есть только в каталоге `openrouter` → `resolve_model_spec(id, "client")` → `default_provider`; **не** `openrouter` |
| 2 | `test_bare_id_flag_enables_cross_provider` | С `allow_cross_provider_bare_id=true` → возвращается `openrouter` (старое поведение) |
| 3 | `test_config_source_keeps_old_behaviour` | `resolve_model_spec(id, "config")` → `openrouter` (операторский конфиг не ломаем) |
| 4 | `test_explicit_spec_unaffected` | `openrouter::model` → `openrouter` при любом флаге |
| 5 | `test_disabled_provider_not_in_v1_models` | `GET /v1/models` не содержит моделей выключенного провайдера |
| 6 | `test_disabled_provider_skipped_in_sync_all` | Sync-all → в `results` провайдера `status == "skipped"`, сети не было |
| 7 | `test_sync_disabled_provider_returns_409` | `POST /models/sync {"provider": "openrouter"}` для выключенного → 409 |
| 8 | `test_disabled_provider_explicit_request_400` | Запрос `disabled::model` → 400 |
| 9 | `test_disabled_provider_skipped_in_fallback` | Fallback-цепочка на выключенного провайдера → запись пропущена |
| 10 | `test_delete_key_clears_env` | `DELETE /providers/{name}/key` → `os.environ` **не** содержит переменную; `has_api_key == false` |
| 11 | `test_delete_key_removes_line_from_env_file` | Строка `KEY=` удалена из `.env` (tmp-файл) |
| 12 | `test_delete_key_unknown_provider_404` | → 404 |
| 13 | `test_providers_response_has_enabled` | `GET /providers` → у каждого провайдера поле `enabled: bool` |
| 14 | `test_default_provider_cannot_be_disabled` | Попытка выключить `default_provider` → 400 |
| 15 | `test_log_records_provider_choice` | При `allow_cross_provider_bare_id=false` в логе есть сообщение про блокировку (F5) |

### Правила

- Изоляция состояния: `state.config`, `state.providers`, `state.available_models`,
  `state.models_by_provider` — **сбрасывать и восстанавливать** (см. `tests/conftest.py`).
- `routing.json` и `config.yaml` в тестах **не трогаются** — `conftest.py`
  подменяет `state.config_file` на tmp-путь.
- Тесты F7 не должны ломать существующие 257 тестов (`pytest tests/ -q` → все зелёные).

---

## F8. Матрица write scope спринта

| Агент | Write scope | Задачи |
|---|---|---|
| `api` | `router.py` | F1, F2 (серверная часть), F3 (эндпоинт), F4, F5 |
| `frontend` | `admin.html` | F6 (UI), F3 (кнопка «Remove key») |
| `devops` | `config.yaml` | F2 (`enabled: true` всем трём провайдерам) |
| `tests` | `tests/phase6/` | F7 |
| `coordinator` | `docs/`, `README.md`, `SECURITY.md` | контракт, ревью, доки |

**Запрещено:** трогать чужие файлы. `api` не правит `admin.html`, `frontend`
не правит `router.py`, `tests` не правит `config.yaml`.

**Порядок:** `api` и `frontend` могут стартовать **параллельно** (write scope не
пересекаются), но `frontend` должен опираться на этот контракт, а не на
реализацию `api`. `tests` стартует **после** того, как `api` закончит F1–F5
(иначе тесты придётся переписывать).

---

## F9. Обратная совместимость

| Что | Правило |
|---|---|
| `config.yaml` без `enabled` | провайдер считается включённым |
| `routing.json` без `allow_cross_provider_bare_id` | `false` (fail-closed) |
| `POST /providers` без `enabled` | `enabled: true` |
| `GET /providers` | **добавляется** поле `enabled` (не ломает UI — лишнее поле игнорируется) |
| Существующие 257 тестов | должны остаться зелёными; если тест падает из-за нового поведения F1 — тест правится **только** с обоснованием в комментарии |
| Каталог моделей | формат `models_cache.json` **не меняется** |
