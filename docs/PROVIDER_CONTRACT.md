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
  usd_rate: 90.0        # 1 USD = 90 ₽ (ручное значение, авто-курса нет)
  rates:
    RUB: 1.0
    USD: 0.011111       # = 1/90
```

`base` — валюта, в которой считается `stats["total_cost"]`.
Конверсия выполняется **на лету** по `rates`.

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
| `currency` | `"RUB"` / `"USD"` / `"NONE"` | из `pricing_mode` |
| `price_source` | `"api"` / `"manual"` / `"unknown"` | `manual` — переопределено в `config.yaml: models:` |
| `supports_images` | bool | `"image" in input_modalities` |
| `pricing_units` | dict | сохраняем как есть (у OpenRouter `null`) |

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
    "by_currency": {},          # {"RUB": 383.12, "USD": 12.45}
    "usd_equivalent": 0.0,      # total_cost / usd_rate
    "by_model": {},             # ключ — составная спецификация
    "routed_count": 0,
    "not_routed_count": 0,
    "fallback_count": 0,
}
```

**Порядок поиска цены** (по ключу-спецификации `"provider::model"`):
1. `config.yaml → models:` — ручной override (`price_source = "manual"`);
2. каталог (`state.available_models`) — `price_source = "api"`;
3. ничего не найдено → цена `0`, `price_source = "unknown"`, в лог — предупреждение.

> **Фиктивная заглушка `{0.50, 1.50}` удаляется полностью.**

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
| Coordinator | `docs/`, `README.md`, `ROADMAP.md`, `MULTIPROVIDER_PLAN.md` | ревью + доки |

**Никто не трогает чужие файлы.**
