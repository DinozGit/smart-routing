# Contributing to SmartRouter

Спасибо за интерес к проекту.

## Быстрый старт для разработчика

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
pip install pytest pytest-asyncio
```

Требуется **Python 3.10+**.

## Тесты

```bash
venv\Scripts\python.exe -m pytest tests/ -q
```

**Все тесты должны быть зелёными перед коммитом.**

### Структура тестов

Тесты разложены по фазам, каждая фаза — в своей директории `tests/phaseN/`:

| Директория | Что покрывает |
|---|---|
| `phase0` | базовые: health, proxy, config, logs |
| `phase1` | дехардкод Coordinator fallback |
| `phase2` | роли, fallback chain, порты, модели |
| `phase3` | fine tuning |
| `phase4` | transport hardening, атомарная запись конфигов |
| `phase5` | мультипровайдерность: каталог, ключи `provider::model_id`, валюты |

**Новая фича → новая фаза** → новая директория `tests/phaseN/`.

### Правила

- Тесты **не ходят в сеть** — мокай HTTP-клиент:
  `patch.object(router.http_client, "post", mock)`.
- Фикстуры изолируют состояние: `state.available_models`, `state.models_by_provider`,
  `state.provider_last_sync`, `state.stats` — сбрасывай и восстанавливай,
  иначе тесты текут друг в друга.
- `routing.json` в тестах не трогается — `conftest.py` подменяет пути на tmp.

## Write scope

Полные правила делегирования и разграничение зон ответственности —
в [AGENTS.md](AGENTS.md). Коротко: не трогай чужие файлы; изменения в
`router.py`, `admin.html`, `config.yaml` и `tests/` распределены по разным
агентам и не должны смешиваться в одном коммите.

## Формат коммита

- Subject — императив, до 50 символов, без точки в конце.
- Body — по 72 символа, и только если subject не раскрывает суть.

```text
Add per-provider SSL settings

Each provider can now override verify_ssl and ca_bundle, so a
corporate CA no longer requires disabling TLS globally.
```

## Как добавить провайдера

Контракт — в [docs/PROVIDER_CONTRACT.md](docs/PROVIDER_CONTRACT.md).

Коротко: провайдер описывается в `config.yaml: providers:`
(`base_url`, `models_endpoint`, `api_key_env`, `requires_api_key`,
`pricing_mode`), после чего его модели синхронизируются через
`POST /models/sync {"provider": "<имя>"}`.
