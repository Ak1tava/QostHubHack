# Запуск и проверка Т01

Нужны Python 3.12, uv и Node.js 24 с npm 12. Lock-файлы уже созданы: `services/api/uv.lock`, `apps/web/package-lock.json`. Проверенная среда: Windows, Python 3.12.14, uv 0.12.22, Node 24.19.0, npm 12.2.0. Команды ниже выполняются из корня репозитория, если не указан другой каталог.

Для контейнерного запуска достаточно Docker с Compose v2; локальные Python/Node не нужны. До интеграции PR используйте опубликованную ветку `codex/t01-bootstrap`, а не документационную `main`.

## Контейнерный запуск

Скопируйте `.env.example` в корневой `.env`, только если файла ещё нет. Задайте случайный локальный `POSTGRES_PASSWORD` и `DATABASE_URL=postgresql+psycopg://qosthub:URL_ENCODED_PASSWORD@db:5432/qosthub`; в URL должен находиться тот же пароль с percent-encoding спецсимволов. Внешние токены оставьте пустыми. Не задавайте секреты через `VITE_`.

```sh
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 120
```

Web и PWA: `http://localhost:5173`; API: `http://127.0.0.1:8000`; Swagger: `http://localhost:5173/docs`; `/health/live` → 200 `{"status":"ok"}`; `/health/ready` → 200 `{"status":"ready"}`. Неверная/недоступная БД → 503 `{"status":"not_ready"}`, liveness остаётся доступен. Nginx сохраняет общий browser origin, cookie и Origin; API/БД опубликованы только на loopback.

```sh
docker compose logs --tail 100
docker compose down
```

Обычный `down` сохраняет volumes PostgreSQL и приватных фото; фото не раздаются Nginx. Миграций приложения в Т01 нет: T02 добавит отдельную команду Alembic, startup её автоматически не выполняет. Worker добавляется в T06.

## Нативная разработка API и web

`.env` необязателен. При необходимости скопируйте `.env.example` в `.env` в **корне репозитория**, не перезаписывая существующий файл; секреты и `DATABASE_URL` для запуска основы оставьте пустыми. Настройки читаются через `from app.core.config import settings`, переменные окружения имеют приоритет. Ключи никогда не задавать с префиксом `VITE_`: такие значения попадают в браузер.

Терминал 1:

```sh
cd services/api
uv sync --locked
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API: `http://127.0.0.1:8000`; Swagger: `/docs`; OpenAPI: `/openapi.json`; `GET /health/live` → `200 {"status":"ok"}`. Для разработки можно добавить `--reload`. Импорт/startup не подключается к БД. Без `DATABASE_URL` readiness возвращает 503; для локальной PostgreSQL URL должен использовать `localhost`, а не Compose-host `db`.

Терминал 2, из корня:

```sh
npm --prefix apps/web ci
npm --prefix apps/web run dev
```

Откройте `http://localhost:5173`. Vite слушает loopback, порт фиксирован (`strictPort`). API, health, Swagger и OpenAPI проксируются в `127.0.0.1:8000`; browser origin остаётся `http://localhost:5173`, как в `PUBLIC_BASE_URL`. Frontend использует относительные URL. При выборе другого browser origin обновите `PUBLIC_BASE_URL`. В контейнерах общий origin обеспечивает Nginx.

Проверка сборки:

```sh
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

Результат сборки — `apps/web/dist`, он исключён из Git. `npm --prefix apps/web run preview` предназначен только для просмотра сборки, не заменяет будущий production reverse proxy. Остановка обоих серверов — `Ctrl+C` в каждом терминале.

## Контракты, PWA и тесты

- Источник контрактов — реальные серверные Pydantic-схемы и подключённые routers. Генерируемые файлы вручную не исправляются; экспорт работает без БД и внешних токенов.
- PWA кеширует статическую оболочку. API/health/документация работают только по сети; полноценная offline-синхронизация не реализована. Новая версия применяется после подтверждения пользователя. Service worker включён в production-сборке, а не в `npm run dev`; для установки на телефон требуется HTTPS (localhost — исключение).
- TypeScript 5.9.3 совместим с openapi-typescript 7.13.0. Vitest 5.0.3, jsdom 28.1.0 и Playwright 1.63.0 закреплены в lock-файле. Корневые e2e используют отдельный tsconfig для разрешения пакетов из `apps/web`.
- B может сразу начать T02 от опубликованной основы: `db.py`, `security.py`, модели, миграции, серверные сессии/CSRF, права и справочники. SQLAlchemy, psycopg и Alembic уже установлены; дополнительные зависимости запрашиваются у A. БД/модели/миграции/auth-модули в этой подготовке не создавались.
- Не пересоздавать `main.py`, `config.py`, manifest/lock-файлы, web и инструкции. A — единственный ответственный за эти общие файлы, Compose и генерируемые контракты. B передаёт A импорты готовых routers, требования пакетов и настроек; A вносит отдельный коммит, B подтягивает его.

Точные договорённости — [C1 в plans.md](../plans.md#c1-данные-авторизация-и-api): sync SQLAlchemy + `postgresql+psycopg://...`; будущие `Base`/`get_db`, Session на запрос и явный commit сервисом; `router` из каждого модуля, единственный `/api/v1` в main. Серверная HttpOnly cookie сохранена; согласованы JSON входа/выхода/me, единая ошибка и CSRF через `/auth/csrf` и `X-CSRF-Token`. Серверные Pydantic-схемы — источник OpenAPI, клиентские типы будут генерироваться A. Эти интерфейсы **не заменены фиктивными реализациями**. Третий участник подключается позже.

Из `services/api`:

```sh
uv run --locked pytest -q
uv run --locked python -m app.export_openapi
```

Из корня:

```sh
npm --prefix apps/web run generate:api
npm --prefix apps/web run typecheck
npm --prefix apps/web run test -- --run
npm --prefix apps/web run build
npm --prefix apps/web exec -- playwright install chromium
npm --prefix apps/web run test:e2e
```

Перед e2e запустите Compose либо API и `npm --prefix apps/web run preview -- --host 127.0.0.1 --port 5173 --strictPort`. E2E_BASE_URL позволяет указать другой адрес. Клиент входа, API-клиент сессии и авторизация выполняются при интеграции T02 по C1.2.

## Фактические локальные проверки Т01 — 2026-10-03

| Команда / проверка | Результат |
| --- | --- |
| `uv run --locked pytest -q` из `services/api` | PASS: 8 тестов; первоначально 7 отказов на отсутствующих readiness/export, затем 8/8 |
| Экспорт OpenAPI без доступной БД | PASS: стабильный JSON, совпадает с runtime; ответы readiness 200/503 |
| `npm --prefix apps/web run generate:api` | PASS: TypeScript сгенерирован из OpenAPI |
| `npm --prefix apps/web run typecheck` | PASS: приложение, тестовые настройки и корневые e2e |
| `npm --prefix apps/web run test -- --run` | PASS: 3 теста подтверждения, откладывания и ошибки обновления PWA |
| `npm --prefix apps/web run build` | PASS: Vite/PWA; manifest, service worker и 11 precache entries |
| `npm --prefix apps/web run test:e2e` | PASS: 3 Chromium-теста на production preview + реальном API; БД отсутствовала, readiness 503 |
| `npm --prefix apps/web audit --json` | PASS: 0 известных уязвимостей |

Docker локально отсутствует; реальный PostgreSQL и Nginx локальной проверкой не подтверждены. Нативный HTTPS Git работает через существующий credential helper; недействительный токен `gh` не заменялся. npm/uv/Chromium установлены только в игнорируемую `.tooling` этой рабочей копии.

## Контейнерная приёмка GitHub Actions

Workflow `T01 bootstrap acceptance` использует чистый checkout, locked install, проверку дрейфа контрактов, pytest/Vitest/build и production Compose. `infra/verify_stack.py` в одноразовом CI-окружении проверяет настоящий SELECT 1, остановку/восстановление БД, неизменность PostgreSQL-кластера и сохранность приватного файлового volume после `down`/`up`. Скрипт требует `CI=true` и не предназначен для работающего стенда.

Playwright затем проверяет Nginx proxy и offline-границы настоящего service worker. При сбое сохраняются очищенные от значений секретов Compose-логи и браузерные артефакты на 7 дней. Завершение job удаляет только одноразовые CI-volumes. Результат контейнерного CI пока ожидается; статус Т01 определяется только `plans.md`.

## Исторические проверки общей основы — 2026-10-03

Исходный Git: `main...origin/main`, рабочее дерево чистое; последние коммиты `f2af222`, `4f2f901`, `d6beddd` (всего 3). Ветка проверки — `chore/parallel-foundation`, созданная от `f2af222`; итоговый SHA подготовки: `git log -1 --format=%H` в этой ветке. SSH clone не прошёл проверку host key; HTTPS clone успешен. Исходная копия документации вне этого клона не менялась.

В среде агента uv/npm отсутствовали в PATH: установлены **только рядом с клоном** в `../tooling`, без глобальной установки. Python предоставлен runtime Codex. Ниже точные PowerShell-команды подготовки (пути относительно корня клона); при обычной установке uv/npm они не нужны:

```powershell
$env:PATH = (Resolve-Path ../tooling).Path + ';' + $env:PATH
$env:npm_config_cache = Join-Path (Resolve-Path ../tooling) 'npm-cache'
cd services/api
$env:UV_CACHE_DIR = Join-Path (Resolve-Path ../../../tooling) 'uv-cache'
& ../../../tooling/uv.exe lock --python C:/Users/white/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
& ../../../tooling/uv.exe sync --locked --python C:/Users/white/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
$env:DATABASE_URL = ''
$env:SESSION_SECRET = ''
$env:OPENAI_API_KEY = ''
$env:TELEGRAM_BOT_TOKEN = ''
& ../../../tooling/uv.exe run --locked --offline uvicorn app.main:app --host 127.0.0.1 --port 8000
```

| Реально выполненная команда / проверка | Результат |
| --- | --- |
| `uv lock` и `uv sync --locked` с указанным Python | PASS: разрешено 25 пакетов (включая проект), установлено 24; FastAPI 0.142.2, Pydantic 2.13.5, SQLAlchemy 2.0.54, psycopg 3.3.6, Alembic 1.20.0 |
| `uv run --locked --offline uvicorn app.main:app --host 127.0.0.1 --port 8000` | PASS: Application startup complete без `.env`, БД и ключей |
| `Invoke-WebRequest http://127.0.0.1:8000/health/live` | PASS: 200, JSON `{"status":"ok"}` |
| `Invoke-RestMethod http://127.0.0.1:8000/openapi.json` | PASS: 200; содержит схему ответа liveness и только `/health/live` |
| `Invoke-WebRequest http://127.0.0.1:8000/health/ready -SkipHttpErrorCheck` и аналогично `/api/v1/auth/me` | PASS по границам основы: оба 404, нет имитации readiness/авторизации |
| `npm.cmd --prefix apps/web ci --offline --no-audit --no-fund` | PASS: 26 пакетов установлены из lock-файла |
| `npm.cmd --prefix apps/web run typecheck` | PASS: `tsc --noEmit`, exit 0 |
| `npm.cmd --prefix apps/web run build` | PASS: TypeScript + Vite 8.3.2, 15 модулей, файлы `dist/index.html`, CSS и JS; exit 0 |
| `npm.cmd --prefix apps/web run dev`, затем `Invoke-WebRequest http://localhost:5173` | PASS: Vite ready; HTTP 200, HTML содержит React entry `/src/main.tsx` |
| `Invoke-WebRequest http://localhost:5173/health/live` | PASS: proxy к API вернул 200 и `status=ok` |
| `Invoke-WebRequest http://localhost:5173/api/v1/auth/me -SkipHttpErrorCheck` | PASS: через proxy получен FastAPI 404 `Not Found`; маршрут T02 не создан |

Первый запуск сборки внутри sandbox завершился `spawn EPERM` при загрузке Vite config; та же команда вне ограничения дочерних процессов прошла без правок кода. Первые попытки вызова uv/npm имели неверный локальный путь/раскладку standalone npm; локальный launcher исправлен до приведённых успешных проверок. Это настройка среды агента, не дополнительное требование проекта.

Docker/БД/миграции, функциональный вход и e2e **не проверялись и не реализованы**. Это не приёмка T01/T02 и не независимая проверка другим участником с чистого клона.

## Историческая передача общей основы

Эти команды предназначены для владельца; агент push/merge не выполнял. В данном клоне:

```sh
git push -u origin chore/parallel-foundation
```

Затем каждый участник в своём клоне получает **одну и ту же** опубликованную основу:

```sh
git fetch origin
# A:
git switch -c codex/t01-bootstrap origin/chore/parallel-foundation
# B (в другом клоне):
git switch -c feat/T02-data-auth origin/chore/parallel-foundation
```

Сначала убедитесь, что рабочее дерево своего клона чистое, или сохраните свои изменения. Оба проверяют совпадение базового SHA (`git rev-parse origin/chore/parallel-foundation`). Общие изменения A переносить согласованным коммитом, не переписывая ветку B. В `main` основу можно интегрировать позже отдельным review; сейчас merge не требуется.

Справка по выбранным интерфейсам: [SQLAlchemy psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg), [Vite: требования среды](https://vite.dev/guide/), [установка uv](https://docs.astral.sh/uv/getting-started/installation/).
