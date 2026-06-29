# CalorIt — Multi-Agent Configuration

## 🧠 Architecture

```
User
  └── Coordinator (главный агент в этом чате)
        │   • SYSTEM_CONTEXT.md + AGENTS.md как единый источник правды
        │   • Декомпозиция фаз на подзадачи
        │   • Распределение между spawn_agent
        │   • Синтез результатов, код-ревью
        │   • Деплой на VPS через SSH (ключ в ~/.ssh/authorized_keys)
        │
        ├── 🔧 Agent: CalorIt API Layer
        ├── 🤖 Agent: CalorIt Telegram Bot
        ├── ⚙️ Agent: CalorIt Services
        ├── 🗄️ Agent: CalorIt Database
        ├── 🧪 Agent: CalorIt Tests
        ├── 🚀 Agent: CalorIt DevOps
        ├── 🎨 Agent: CalorIt Frontend
        ├── 📱 Agent: CalorIt Mobile
        └── 🖌️ Agent: CalorIt Design
```
## 🎯 Правила делегирования задач для Coordinator

### ⚠️ КРИТИЧЕСКОЕ ПРАВИЛО ЭКОНОМИИ

**НИКОГДА не выполняй задачи из чужих Write scope сам!**

Если задача относится к зоне ответственности другого агента:
- ❌ НЕ пиши код сам (даже если задача кажется простой)
- ✅ ВСЕГДА spawn'и соответствующего агента

### Примеры:

**Плохо (тратит дорогие токены Coordinator-а):**


## 🤖 Agent Roles

### 🔧 CalorIt API Layer
| Поле | Значение |
|------|----------|
| **Files** | `app/api/*.py`, `app/schemas.py`, `app/middleware.py` |
| **Responsibility** | FastAPI endpoints, Pydantic schemas, JWT middleware, CORS |
| **Write scope** | `api/*.py`, `schemas.py`, `middleware.py` |
| **Read scope** | `app/database/crud*.py`, `app/database/models.py`, `app/services/*.py` |
| **Context on spawn** | SYSTEM_CONTEXT.md + all files in write scope |

### 🤖 CalorIt Telegram Bot
| Поле | Значение |
|------|----------|
| **Files** | `app/handlers/*.py`, `app/keyboards.py` |
| **Responsibility** | aiogram handlers, FSM states, inline keyboards, bot commands |
| **Write scope** | `handlers/*.py`, `keyboards.py` |
| **Read scope** | `app/services/*.py`, `app/database/crud.py`, `app/config.py` |
| **Context on spawn** | SYSTEM_CONTEXT.md + all files in write scope |

### ⚙️ CalorIt Services
| Поле | Значение |
|------|----------|
| **Files** | `app/services/*.py` (вкл. `reminder_service.py` — APScheduler, `nutrition_service.py` — BMI/BMR/TDEE) |
| **Responsibility** | AI service (OpenRouter), cache merge, image processing, nutrition calculations, Telegram reminders |
| **Write scope** | `services/*.py` |
| **Read scope** | `app/config.py`, `app/database/models.py`, `app/database/crud.py`, `app/schemas.py` |
| **Context on spawn** | SYSTEM_CONTEXT.md + current files in services/ |

### 🗄️ CalorIt Database
| Поле | Значение |
|------|----------|
| **Files** | `app/database/*.py`, `alembic/versions/*.py`, `alembic.ini.example` |
| **Responsibility** | SQLAlchemy models, CRUD operations, migrations |
| **Write scope** | `database/*.py`, `alembic/versions/*.py` |
| **Read scope** | `app/config.py` |
| **Context on spawn** | SYSTEM_CONTEXT.md + current database files |

### 🧪 CalorIt Tests
| Поле | Значение |
|------|----------|
| **Files** | `tests/*.py` |
| **Responsibility** | Pytest unit & integration tests |
| **Write scope** | `tests/` |
| **Read scope** | All project files |
| **Context on spawn** | SYSTEM_CONTEXT.md + relevant source files |

### 🚀 CalorIt DevOps
| Поле | Значение |
|------|----------|
| **Files** | `Dockerfile`, `docker-compose*.yml`, `nginx*.conf`, `.github/workflows/*.yml` |
| **Responsibility** | Docker, CI/CD, Nginx, SSL, deployment |
| **Write scope** | Dockerfile, docker-compose*.yml, nginx*.conf, .github/ |
| **Read scope** | `app/main.py`, `app/config.py`, `requirements.txt` |
| **Context on spawn** | SYSTEM_CONTEXT.md + current infrastructure files |

### 🎨 CalorIt Frontend
| Поле | Значение |
|------|----------|
| **Files** | `frontend/**/*` (Next.js pages, components, styles) |
| **Responsibility** | Web dashboard, Telegram Login Widget, charts, forms |
| **Write scope** | `frontend/` |
| **Read scope** | `app/schemas.py`, `app/api/*.py`, `app/database/models.py` |
| **Context on spawn** | SYSTEM_CONTEXT.md + current frontend files |

### 📱 CalorIt Mobile
| Поле | Значение |
|------|----------|
| **Files** | `mobile/**/*` (Flutter/Dart, весь проект `calorit_app`) |
| **Responsibility** | Мобильное приложение Flutter: все экраны, навигация, API-клиент, офлайн-режим, push-уведомления, сканер штрихкодов, фото тела, виджеты |
| **Write scope** | `mobile/` |
| **Read scope** | `app/schemas.py`, `app/api/*.py`, `app/database/models.py`, `app/services/nutrition_service.py`, `app/config.py`, `design/` |
| **Context on spawn** | SYSTEM_CONTEXT.md + MOBILE_APP_PLAN.md + current mobile files |

### 🖌️ CalorIt Design
| Поле | Значение |
|------|----------|
| **Files** | `design/**/*` (design tokens, темы, компоненты дизайн-системы, Figma-экспорты) |
| **Responsibility** | UX/UI дизайн: компоненты дизайн-системы (Material 3), цветовые токены (светлая/тёмная тема), типографика, иконки, анимации, accessibility, адаптивные лейауты, Figma-макеты, UX-исследования |
| **Write scope** | `design/` |
| **Read scope** | `mobile/` (для синхронизации), `frontend/` (для синхронизации), `app/schemas.py` |
| **Context on spawn** | SYSTEM_CONTEXT.md + MOBILE_APP_PLAN.md + current design files |

## 🔄 Workflow

### Sequential execution
```
Coordinator → spawn_agent(Agent A) → wait → review → spawn_agent(Agent B) → ...
```

### Parallel execution
```
Coordinator → spawn_agent(Agent A)  ─┐
             → spawn_agent(Agent B)  ─┤  (disjoint write scopes)
             → spawn_agent(Agent C)  ─┘ → wait all → review → merge

Пример (мобильная фича):
Coordinator → spawn_agent(📱 Mobile: экран + API-клиент)  ─┐
             → spawn_agent(🖌️ Design: токены + макет)     ─┤ parallel
             → spawn_agent(🔧 API: эндпоинт если нужен)     ─┘ → review → merge
```

### Full feature cycle
```
Coordinator:
  1. Разбивает фичу на подзадачи (непересекающиеся файлы)
  2. Запускает параллельно:
     → Database Agent: миграция + CRUD
     → API Agent: новый endpoint
     → Bot Agent: новый handler
     → Tests Agent: тесты
  3. Собирает результаты, проверяет, merge'ит
  4. DevOps Agent: деплой через SSH на VPS
     → Coordinator: `ssh root@31.128.36.227 "cd /root/calorit-api && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build app frontend redis"`
```

## 🚀 Deploy Workflow (обязательный порядок)

Каждая фаза завершается по следующему циклу:

```
1. 💻 Dev (Windows) — локальная разработка
   ├── Spawn агентов → изменения в файлах
   ├── Agent Tests: pytest (SQLite in-memory) → все тесты должны проходить
   └── Coordinator: ручной code-review всех изменений

2. 📦 Коммит + Пуш
   ├── GIT_EDITOR=true git add -A
   ├── GIT_EDITOR=true git commit -m "..."
   └── git push origin master

3. 🖥️ VPS (Ubuntu prod) — деплой
   ├── ssh root@31.128.36.227 "cd /root/calorit-api && git pull"
   └── ssh root@31.128.36.227 "cd /root/calorit-api && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build app frontend redis"

4. 🧪 VPS — проверка
   ├── ssh root@31.128.36.227 "cd /root/calorit-api && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app pytest tests/ -v"
   └── Coordinator предоставляет сценарии ручного тестирования пользователю
```

### ⚠️ Важно
- **После каждого спринта агентов** (а не после каждого файла) — полный цикл ниже.
- Перед пушем убедиться: все тесты зелёные, линтер не сыпет ошибок.
- После деплоя на VPS — обязательно прогнать тесты в Docker-контейнере.
- Ручные сценарии тестирования — Coordinator пишет **конкретные шаги** для совместной проверки с пользователем.

## 🖥️ Flutter Dev Environment (Windows)

**ВСЕГДА** используй этот префикс перед командами Flutter/Dart/Android:

```bash
export ANDROID_HOME="C:/android-sdk" && \
export PATH="/c/flutter/bin:/c/android-sdk/platform-tools:/c/android-sdk/cmdline-tools/latest/bin:$PATH" && \
export JAVA_HOME="C:/Program Files/Eclipse Adoptium/jdk-17.0.17.10-hotspot" && \
cd C:/Users/user/projects/calorit-api/mobile/calorit_app && \
<команда>
```

### Команды (всегда с префиксом выше)

| Действие | Команда |
|----------|---------|
| Кодогенерация (freezed/json) | `flutter pub run build_runner build --delete-conflicting-outputs` |
| Анализ | `flutter analyze` |
| Тесты | `flutter test 2>&1 \| tail -15` |
| Сборка debug APK | `flutter build apk --debug` |
| Сборка release APK | `flutter build apk --release` |
| Сборка appbundle | `flutter build appbundle --release` |
| Установка на эмулятор | `flutter install` |

### ⚠️ Известные проблемы

- `flutter analyze` выдаёт `invalid_annotation_target` — false positive freezed + analyzer. Игнорировать.
- `widget_test.dart` падает в CI — предсуществующий, не регресс.
- Все команды Dart/Flutter/Android требуют export переменных выше.

## 🔄 SDLC — Полный цикл разработки

Каждая единица работы (спринт агентов) проходит полный Software Development Lifecycle:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. 💻 Dev (Windows) — локальная разработка                          │
│    ├── Coordinator: декомпозиция задачи на непересекающиеся скоупы  │
│    ├── Parallel spawn агентов (до 3 одновременно)                   │
│    ├── Каждый агент: код + свои тесты                                │
│    └── Coordinator: code review всех изменений                      │
│                                                                     │
│ 2. 🧪 Тестирование (обязательно)                                     │
│    ├── Backend: python -m pytest tests/ -v (SQLite in-memory)       │
│    ├── Flutter: flutter test + flutter analyze                      │
│    ├── Frontend: npm run lint + npm test (если есть)                │
│    └── Все тесты должны быть ЗЕЛЁНЫМИ перед пушем                   │
│                                                                     │
│ 3. 📦 Коммит + Пуш в GitHub                                         │
│    ├── GIT_EDITOR=true git add -A                                   │
│    ├── GIT_EDITOR=true git commit -m "..."                          │
│    └── git push origin master                                       │
│                                                                     │
│ 4. 🖥️ VPS — деплой                                                   │
│    ├── ssh root@31.128.36.227 "cd /root/calorit-api && git pull"    │
│    └── ssh root@31.128.36.227 "cd /root/calorit-api &&              │
│        docker compose -f docker-compose.yml                         │
│        -f docker-compose.prod.yml up -d --build                     │
│        app frontend redis"                                           │
│                                                                     │
│ 5. 🧪 VPS — тесты в продакшен-окружении                             │
│    ├── ssh ... "docker compose exec app pytest tests/ -v"           │
│    └── Все тесты должны проходить и на VPS                          │
│                                                                     │
│ 6. 🤝 Ручное тестирование                                           │
│    ├── Coordinator готовит сценарии ручного тестирования             │
│    ├── Web: ручная проверка на calorit.pro                          │
│    ├── Mobile: сборка .apk → установка на Android-устройство        │
│    └── Пользователь выполняет сценарии, фиксирует баги              │
└─────────────────────────────────────────────────────────────────────┘
```

### 🧪 Требования к тестированию

| Платформа | Как тестируем | Где |
|-----------|-------------|-----|
| **Backend (Python)** | `python -m pytest tests/ -v` | Windows Dev + VPS Docker |
| **Flutter (Dart)** | `flutter test` + `flutter analyze` | Windows Dev (эмулятор + real device) |
| **Frontend (Next.js)** | `npm run lint` + ручная проверка | Windows Dev → VPS |

### 📱 Flutter: синтетическое тестирование на Windows Dev

- **Эмулятор:** Android Emulator (Android Studio) — API 34
- **Команды:** `flutter test`, `flutter analyze`, `flutter build apk --debug`
- **Установка на эмулятор:** `flutter install` или drag'n'drop .apk

### 📱 Flutter: ручное тестирование на реальном устройстве

1. `flutter build apk --debug` (или `--release`)
2. Скопировать `.apk` на телефон (USB / Telegram / облако)
3. Установить (разрешить «Неизвестные источники»)
4. Пройти сценарии ручного тестирования

## 🔐 SSH Deploy

У Coordinator-агента есть прямой доступ к VPS:

| Параметр | Значение |
|----------|----------|
| **Host** | `31.128.36.227` |
| **User** | `root` |
| **Auth** | SSH-ключ (добавлен в `authorized_keys`) |
| **Команда деплоя** | `ssh root@31.128.36.227 "cd /root/calorit-api && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build app frontend redis"` |

> ⚠️ GitHub Secrets (`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`) не настроены. Автоматический CI/CD деплой через GitHub Actions пока недоступен.
