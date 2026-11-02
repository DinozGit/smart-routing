# Подключение SmartRouter к IDE

SmartRouter — OpenAI-совместимый прокси. Любой клиент, умеющий говорить с
OpenAI API, работает с ним без специальной поддержки.

```
Клиент (Zed, Cline, Continue, Cursor, OpenWebUI, OpenAI SDK…)
   └── HTTP → http://localhost:8765/v1
                └── SmartRouter выбирает провайдера и модель
                        └── routerai / openrouter / ollama
```

---

## 0. Запуск роутера

```bash
git clone https://github.com/DinozGit/smart-routing.git
cd smart-routing

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

copy .env.example .env         # Windows
# cp .env.example .env         # macOS / Linux
```

Впишите ключи в `.env` (файл в `.gitignore`, в репозиторий не попадает):

```env
ROUTERAI_KEY=sk-ra-...
OPENROUTER_API_KEY=sk-or-v1-...
```

Запуск:

```bash
python router.py
```

Проверка:

```bash
curl http://localhost:8765/health
# {"status":"ok","cost":"0.0000","currency":"RUB"}

curl http://localhost:8765/models/available | head -c 200
```

Админка: <http://localhost:8765/admin> — вкладка **Models** → «Sync всех».

---

## 1. Ключи моделей: `provider::model_id`

Роутер отдаёт модели в составном виде — с указанием провайдера:

```bash
curl -s http://localhost:8765/v1/models | head -c 300
```

```json
{"object":"list","data":[
  {"id":"routerai::deepseek/deepseek-v4-flash","object":"model","created":1700000000,"owned_by":"RouterAI"},
  {"id":"openrouter::z-ai/glm-5.3-flash",   "object":"model","created":1700000000,"owned_by":"openrouter"},
  {"id":"ollama::qwen3:4b",                  "object":"model","created":1700000000,"owned_by":"ollama"}
]}
```

| Префикс | Что это |
|---------|---------|
| `routerai::` | RouterAI — цены в **₽** |
| `openrouter::` | OpenRouter — цены в **$** |
| `ollama::` | локальный Ollama — **бесплатно**, ключ не нужен |

> **Составной ID = точное указание.** Если клиент прислал `provider::model`,
> роутер использует именно эту модель и именно этого провайдера —
> без «умной» перемаршрутизации и без подстановки ролевых промптов.

---

## 2. VSCode — Cline

Cline (и Roo Code) работают в extension host VSCode, то есть в Node.js —
CORS им не нужен, достаточно HTTP-доступа.

**Settings → Cline → API Provider:**

| Поле | Значение |
|------|----------|
| API Provider | **OpenAI Compatible** |
| Base URL | `http://localhost:8765/v1` |
| API Key | любой непустой текст (например `sk-local`) — **роутер его не проверяет** |
| Model ID | `routerai::deepseek/deepseek-v4-flash` (см. список ниже) |

**Как узнать доступные модели:**

```bash
curl -s http://localhost:8765/v1/models | python -c "import json,sys; [print(m['id']) for m in json.load(sys.stdin)['data']]"
```

Полезные стартовые варианты:

| Модель | Когда взять |
|--------|-------------|
| `routerai::deepseek/deepseek-v4-flash` | основная рабочая лошадка, дёшево |
| `routerai::deepseek/deepseek-v4-pro` | сложные задачи |
| `openrouter::z-ai/glm-5.3-flash` | очень дёшево, в долларах |
| `ollama::qwen3:4b` | локально, **бесплатно**, без интернета |

> ⚠️ **Не используйте `SmartAuto`**, если не хотите умную маршрутизацию:
> она перенаправит запрос на модель роли `coordinator` и добавит в system prompt
> инструкции по делегированию. Для обычного coding-assistant это лишнее.

**Проверка в Cline:** задайте агентом «создай файл test.txt с текстом `hello`».
В логах роутера (`/logs` или вкладка Logs в админке) должна появиться строка:

```
💰 routerai::deepseek/deepseek-v4-flash: In 812 | Out 45 | Cost 0.000038 RUB
```

---

## 3. VSCode — Continue

**Settings → Continue → Models:**

```jsonc
{
  "models": [
    {
      "title": "SmartRouter (flash)",
      "provider": "openai",
      "model": "routerai::deepseek/deepseek-v4-flash",
      "apiBase": "http://localhost:8765/v1",
      "apiKey": "sk-local"
    }
  ]
}
```

---

## 4. Любой OpenAI-клиент (curl / OpenAI SDK)

### curl (ASCII — работает везде)

```bash
curl http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ollama::qwen3:4b",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

### curl (кириллица)

> ⚠️ **Нюанс Windows.** `curl` в Windows отправляет тело в кодировке консоли
> (OEM-codepage), а не в UTF-8 — запрос с кириллицей вернёт
> `{"detail":"Invalid JSON body"}`. **Это проблема `curl`, а не роутера:**
> при UTF-8 всё работает. Два обходных пути:

**Вариант A — тело в файле** (файл всегда в UTF-8):
```bash
# в Windows положите файл в UTF-8 и выполните:
curl http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  --data-binary @request.json
```

**Вариант B — JSON-escape** (тело остаётся чистым ASCII):
```bash
curl http://localhost:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"ollama::qwen3:4b","messages":[{"role":"user","content":"\u041f\u0440\u0438\u0432\u0435\u0442"}]}'
```

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8765/v1", api_key="sk-local")

resp = client.chat.completions.create(
    model="routerai::deepseek/deepseek-v4-flash",
    messages=[{"role": "user", "content": "Привет"}],
)
print(resp.choices[0].message.content)
```

---

## 5. Zed

В `settings.json`:

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

В Zed работает **агентная маршрутизация**: модель выбирается по тегу
`[AGENT:name]` в сообщении — Coordinator получает дорогую модель,
worker-агенты — дешёвую. Подробности — в [README](../README.md).

---

## 6. Что поддерживается

| Возможность | Статус |
|-------------|--------|
| `/v1/chat/completions` (non-streaming) | ✅ |
| Streaming (SSE) | ✅ |
| Function calling / `tools` | ✅ — тело запроса проксируется как есть |
| `temperature`, `top_p`, `max_tokens` | ✅ |
| `max_tokens` cap по `context_length` модели | ✅ (60% от контекста) |
| `/v1/models` | ✅ составные ID |
| Аутентификация на самом роутере | ❌ — предполагается локальный запуск на `127.0.0.1` |

> Роутер **не проксирует** `Authorization` клиента — он подставляет свой ключ
> провайдера из `.env`. Поэтому в поле «API Key» в IDE можно писать что угодно.

---

## 7. Диагностика

| Симптом | Причина и решение |
|---------|-------------------|
| `Connection refused` | Роутер не запущен. `python router.py` |
| `502 Missing API key: ROUTERAI_KEY` | Не заполнен `.env` **или** у модели нет ключа. Проверьте `GET /providers` → `has_api_key` |
| Модель в ответе не та, что выбрана | Вы указали `SmartAuto` или голое имя без `provider::`. Укажите составной ID |
| В system prompt лишний текст про делегирование | Та же причина — используйте `provider::model` |
| `404` на `/v1/chat/completions` при `GET` | Метод должен быть `POST` |
| Пустой ответ | Смотрите вкладку **Logs** в админке — там реальная ошибка провайдера |
| `{"detail":"Invalid JSON body"}` | Windows `curl` отправил тело не в UTF-8 — см. раздел 4 |

Проверить, что роутер отвечает:

```bash
curl -s http://localhost:8765/health
curl -s http://localhost:8765/stats | python -m json.tool | head -20
```
