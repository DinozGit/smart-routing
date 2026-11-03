# SmartRouter

**OpenAI-совместимый прокси с умной маршрутизацией моделей.**

Один адрес для всех ваших AI-агентов. Работает с Zed, VSCode (Cline), Cursor,
Continue, OpenWebUI и любым другим клиентом, умеющим говорить с OpenAI API.

```mermaid
graph LR
    A[Zed / VSCode / Cline / любой OpenAI-клиент] -->|http://localhost:8765/v1| B[SmartRouter]
    B -->|по цене и возможностям| C[routerai · ₽]
    B --> D[openrouter · $]
    B --> E[ollama · бесплатно]
```

---

## Что это даёт

| | Без роутера | Со SmartRouter |
|---|---|---|
| **Модель для агента** | одна на всех | дешёвая для worker'ов, дорогая для координатора |
| **Провайдеры** | прибиты к одному | RouterAI, OpenRouter, локальный Ollama — переключаются без кода |
| **Стоимость** | непрозрачна | посчитана в рублях **и** долларах, с USD-эквивалентом |
| **Каталог моделей** | ручной список | 760 моделей, синхронизируются автоматически |
| **Цены** | зашиты в коде | живые из каталога провайдера, в рублях **и** долларах |
| **Не-текстовые модели** | в общем списке | отфильтрованы (картинки, видео, TTS, эмбеддинги) |

**Экономия на агентных задачах — до 90%.** Worker-агенту (чтение файлов, тесты,
миграции) хватает модели за ~6 ₽/1M токенов, тогда как «универсальная» модель
может стоить 132 ₽/1M — разница в 22 раза.

---

## Быстрый старт

### 1. Установка

```bash
git clone https://github.com/DinozGit/smart-routing.git
cd smart-routing

python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
```

Всего **5 зависимостей**: `fastapi`, `uvicorn`, `httpx`, `python-dotenv`, `pyyaml`.

### 2. Ключи провайдеров

```bash
copy .env.example .env           # Windows
# cp .env.example .env           # macOS / Linux
```

Впишите хотя бы один ключ:

```env
ROUTERAI_KEY=sk-ra-...
OPENROUTER_API_KEY=sk-or-v1-...
```

Локальный Ollama ключа не требует.

> `.env` в `.gitignore` — в репозиторий он не попадёт.

### 3. Запуск

```bash
python router.py
```

Роутер слушает **127.0.0.1:8765** — API и админка на одном порту.
Проверка:

```bash
curl http://localhost:8765/health
# {"status":"ok","cost":"0.0000","currency":"RUB"}
```

### 4. Загрузить каталог моделей

Откройте <http://localhost:8765/admin> → вкладка **Models** → **«Sync всех»**.

Скачается каталог всех провайдеров: **351** RouterAI + **399** OpenRouter + **10** Ollama = **760** моделей с ценами и валютами.

### 5. Подключить клиент

```bash
curl http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"routerai::deepseek/deepseek-v4-flash",
       "messages":[{"role":"user","content":"Привет"}]}'
```

Подробные инструкции для каждого IDE — в **[docs/IDE_SETUP.md](docs/IDE_SETUP.md)**.

---

## Подключение к IDE

### VSCode — Cline / Roo Code

Settings → Cline → API Provider:

| Поле | Значение |
|---|---|
| API Provider | `OpenAI Compatible` |
| Base URL | `http://localhost:8765/v1` |
| API Key | `sk-local` — любой текст, роутер его не проверяет |
| Model ID | `routerai::deepseek/deepseek-v4-flash` |

Работает tool-calling, streaming, всё остальное — стандартный OpenAI API.

### Zed — агентная маршрутизация

```json
{
  "language_models": {
    "openai_compatible": {
      "smart-router": {
        "api_url": "http://localhost:8765/v1",
        "available_models": [
          { "name": "SmartAuto", "display_name": "SmartRouter (Auto)" }
        ]
      }
    }
  }
}
```

В Zed модель выбирается **автоматически** по тегу агента — см. раздел
«Агентная маршрутизация».

### Любой OpenAI-клиент

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8765/v1", api_key="sk-local")
resp = client.chat.completions.create(
    model="openrouter::z-ai/glm-5.3-flash",
    messages=[{"role": "user", "content": "Привет"}],
)
```

---

## Модели: формат `provider::model_id`

Роутер работает с **составными** идентификаторами — с указанием провайдера:

| ID | Провайдер | Цена за 1M токенов | Контекст | Картинки |
|---|---|---|---|---|
| `routerai::qwen/qwen3.8-27b` | RouterAI | **0.42 / 25.79 ₽** | 1000K | ✅ |
| `routerai::qwen/qwen3.7-flash` | RouterAI | 3.16 / 13.68 ₽ | 976K | ✅ |
| `routerai::minimax/minimax-m3` | RouterAI | 24.21 / 101.05 ₽ | 1024K | ✅ |
| `routerai::deepseek/deepseek-v4-flash` | RouterAI | 10.00 / 20.00 ₽ | 1024K | ❌ |
| `routerai::deepseek/deepseek-v4-pro` | RouterAI | 132.63 / 221.06 ₽ | 1024K | ❌ |
| `openrouter::z-ai/glm-5.3-flash` | OpenRouter | 0.03 / 0.08 **$** | 1024K | ✅ |
| `ollama::qwen3:4b` | Ollama | **0 / 0** | 256K | ❌ |

> ⚠️ **Колонка «Картинки» важна при выборе модели.**
> Модель без поддержки изображений возвращает от провайдера
> `400 Model '...' does not support image input` — если запрос пришёл со скриншотом.
> Coordinator получает скриншоты, поэтому ему нужна vision-модель;
> worker'ам, которые только читают код, она не требуется.

Список всех моделей:

```bash
curl -s http://localhost:8765/v1/models | python -c "import json,sys; [print(m['id']) for m in json.load(sys.stdin)['data']]"
```

> **Составной ID = точное указание.** Если клиент прислал `provider::model`,
> роутер использует именно эту модель и этого провайдера — без «умной»
> перемаршрутизации и без подстановки ролевых промптов.

---

## Агентная маршрутизация

Для IDE с поддержкой субагентов (Zed, Roo Code) роутер умеет сам выбирать модель
по типу агента.

Три роли. Модель подобрана под то, что роль **реально получает**:

| Роль | Модель по умолчанию | Цена за 1M | Картинки | Для кого |
|---|---|---|---|---|
| `coordinator` | `routerai::minimax/minimax-m3` | 24.21 ₽ | ✅ | координатор: декомпозиция, ревью, **скриншоты** |
| `worker_default` | `routerai::qwen/qwen3.8-27b` | **0.42 ₽** | ✅ | backend, тесты, боты, devops — только чтение кода |
| `worker_img` | `routerai::qwen/qwen3.7-flash` | 3.16 ₽ | ✅ | frontend, mobile, design — работа с визуалом |

Разрыв между coordinator и worker — **57×**. Именно в этом и смысл роутера:
координатору нужна vision-модель, потому что к нему приходят скриншоты,
а worker'ам, которые только читают и пишут код, хватает текстовой.

Выбор роли — по тегу `[AGENT:name]` в сообщении:

```
[AGENT:database] создай миграцию для таблицы users
```

Роутятся агенты `coordinator`, `database`, `tests`, `api`, `services`, `bot`,
`devops` → `worker_default`; `frontend`, `mobile`, `design` → `worker_img`.

Соответствие ролей и моделей настраивается в `routing.json` и меняется
**без перезапуска** роутера.

> Если клиент прислал готовую модель (`provider::model`), маршрутизация **не**
> применяется — выбор пользователя уважается.

---

## Провайдеры

Из коробки: **RouterAI** (цены в ₽), **OpenRouter** (цены в $) и **Ollama**
(локально, бесплатно, без API-ключа).

Любой OpenAI-совместимый провайдер добавляется через админку (вкладка
**Providers**) — нужны `base_url`, `models_endpoint` и имя переменной с ключом.

| Поле | Смысл |
|---|---|
| `requires_api_key` | `false` — запрос уходит без `Authorization` (Ollama) |
| `enabled` | `false` — провайдер **выключен**: не синкается, не попадает в `/v1/models`, не используется в fallback-цепочке. Обратимый выключатель — в отличие от удаления, `base_url`/`api_key_env`/SSL-настройки остаются на месте |
| `pricing_mode` | `auto` — валюта определяется по типу цены (строка → USD, число → ₽) |
| `default` | провайдер по умолчанию, fallback для моделей вне каталога |
| `extra_headers` | доп. заголовки (OpenRouter: `HTTP-Referer`, `X-Title`) |
| `verify_ssl` / `ca_bundle` | TLS — для корпоративных CA и self-signed |

Полный формат — в **[docs/PROVIDER_CONTRACT.md](docs/PROVIDER_CONTRACT.md)**.

---

## Отключение провайдера и отзыв ключа

Роутер **никогда сам не выбирает провайдера, которого вы не указали**: голый
`model_id` из клиента резолвится только в каталоге провайдера по умолчанию
(см. «Модели: формат `provider::model_id`»). Но если OpenRouter (или любой
другой) вам не нужен — выключите его одной кнопкой, а не удаляйте:

| Действие | Где | Что делает |
|---|---|---|
| **Enabled** (тумблер) | вкладка **🔌 Providers** | провайдер выключается: роутер к нему не обращается, его модели исчезают из `/v1/models` и из выпадающих списков |
| **Remove key** | вкладка **🔌 Providers** | ключ удаляется из `.env` **и** из окружения текущего процесса — действует **без перезапуска** роутера |

```bash
# Выключить провайдера
curl -s -X POST http://127.0.0.1:8765/providers \
     -H "Content-Type: application/json" \
     -d '{"name":"openrouter","enabled":false,"base_url":"https://openrouter.ai/api/v1/chat/completions","models_endpoint":"https://openrouter.ai/api/v1/models","api_key_env":"OPENROUTER_API_KEY","requires_api_key":true,"pricing_mode":"auto"}'

# Отозвать ключ
curl -s -X DELETE http://127.0.0.1:8765/providers/openrouter/key
```

> ⚠️ **Ручное удаление строки из `.env` не работает** на уже запущенном
> роутере: переменная окружения остаётся в памяти процесса, и запросы
> продолжат уходить. Пользуйтесь **Remove key** — он чистит и файл, и
> окружение процесса.
>
> Если ключ экспортирован в системе или в профиле оболочки, он вернётся при
> перезапуске роутера. Проверьте: `echo $OPENROUTER_API_KEY` (Linux/macOS),
> `echo %OPENROUTER_API_KEY%` (Windows).

---

## Стоимость и валюты

Цены хранятся вместе с валютой и обновляются при синхронизации каталога.

```yaml
currency:
  base: RUB          # валюта stats["total_cost"]
  usd_rate: 90.0     # 1 USD = 90 ₽
```

В статистике:

| Поле | Значение |
|---|---|
| `total_cost` | сумма **в базовой валюте** (₽) |
| `by_currency` | суммы **в native-валютах**: `{"RUB": 383.12, "USD": 12.45}` |
| `usd_equivalent` | эквивалент в долларах по `usd_rate` |

```bash
curl -s http://localhost:8765/stats | python -m json.tool
```

---

## API

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/v1/chat/completions` | Основной прокси (OpenAI-совместимый) |
| `GET` | `/v1/models` | Список моделей (составные ID) |
| `GET` | `/health` | Проверка живости |
| `GET` | `/stats` | Статистика и стоимость |
| `GET` | `/logs?level=INFO&limit=200` | Логи |
| `GET` | `/admin` | Веб-админка |
| `GET`/`POST` | `/config` | Конфигурация ролей и агентов |
| `GET`/`POST`/`DELETE` | `/providers[/{name}]` | Управление провайдерами |
| `DELETE` | `/providers/{name}/key` | Отзыв ключа: удаляет его из `.env` и из окружения процесса |
| `GET`/`PUT` | `/roles[/{name}]/tuning` | Параметры и промпты ролей |
| `GET` | `/models/available` | Каталог моделей, сгруппированный по провайдерам |
| `POST` | `/models/sync` | Синхронизация каталога (тело `{"provider": "..."}` — опционально) |

---

## Конфигурация

| Файл | Что хранит | В git? |
|---|---|---|
| `config.yaml` | провайдеры, роли, валюты, ручные override'ы цен | ✅ |
| `routing.json` | роли → модели, агент → роль, промпты | ✅ (runtime-конфиг) |
| `models_cache.json` | кеш каталога моделей | ❌ генерируется |
| `.env` | API-ключи | ❌ |

Ручные override'ы цен нужны только для моделей, которых **нет в каталоге**
(свой прокси, self-hosted) — пример в `config.yaml`.

---

## Возможности и ограничения

| | |
|---|---|
| ✅ | `/v1/chat/completions`, streaming (SSE), function calling (`tools`) |
| ✅ | Каталог моделей по провайдерам с автосинхронизацией |
| ✅ | Учёт стоимости в нескольких валютах |
| ✅ | Веб-админка без сборки (vanilla JS) |
| ❌ | Аутентификация самого роутера — рассчитан на локальный запуск (`127.0.0.1`) |
| ❌ | CORS — не включён намеренно: браузерный клиент сможет управлять локальным роутером |
| ❌ | Rate limiting, JSON-логи, Docker — в планах ([docs/ROADMAP.md](docs/ROADMAP.md)) |

---

## Troubleshooting

| Симптом | Решение |
|---|---|
| `Connection refused` | Роутер не запущен: `python router.py` |
| `502 Missing API key: ROUTERAI_KEY` | Не заполнен `.env`. Проверьте `GET /providers` → `has_api_key` |
| `{"detail":"Invalid JSON body"}` | Windows `curl` отправил тело не в UTF-8 — используйте `--data-binary @file` |
| Модель в ответе не та, что выбрана | Указан `SmartAuto` или голое имя без `provider::` — укажите составной ID |
| Роутер стучится в провайдера, которого я не выбирал | Проверьте `GET /providers` → `enabled`. Если `false`, но в логах есть обращения — перезапустите роутер: ключ остался в окружении процесса. Подробнее — «Отключение провайдера и отзыв ключа» |
| После удаления ключа из `.env` провайдер всё ещё используется | Удаление из файла не действует на запущенный процесс — нажмите **Remove key** в админке |
| В промпте лишний текст про делегирование | Та же причина — используйте `provider::model` |
| Пустой ответ | Вкладка **Logs** в админке — там реальная ошибка провайдера |

---

## Документация

| Документ | О чём |
|---|---|
| [docs/IDE_SETUP.md](docs/IDE_SETUP.md) | Подключение к каждому IDE, пошагово |
| [docs/PROVIDER_CONTRACT.md](docs/PROVIDER_CONTRACT.md) | Контракт: каталог, ключи моделей, валюты, API |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Планы, статус фаз, история спринтов |
| [docs/MULTIPROVIDER_PLAN.md](docs/MULTIPROVIDER_PLAN.md) | Архитектура мультипровайдерного роутера |
| [AGENTS.md](AGENTS.md) | Протокол мультиагентной работы |

---

## Разработка

```bash
venv\Scripts\python.exe -m pytest tests/ -q     # 257 тестов
```

Структура тестов — по фазам, каждая в своей директории `tests/phaseN/`.

Правила делегирования и описание write scope — в [AGENTS.md](AGENTS.md).

---

## Лицензия

[MIT](LICENSE) © 2026 DinozGit
