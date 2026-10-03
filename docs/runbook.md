# Локальный запуск общей основы

Нужны Python 3.12, uv и Node.js 24 с npm 12. Lock-файлы уже созданы: `services/api/uv.lock`, `apps/web/package-lock.json`. Проверенная среда: Windows, Python 3.12.14, uv 0.12.22, Node 24.19.0, npm 12.2.0. Команды ниже выполняются из корня репозитория, если не указан другой каталог.

## API и web

`.env` необязателен. При необходимости скопируйте `.env.example` в `.env` в **корне репозитория**, не перезаписывая существующий файл; секреты и `DATABASE_URL` для запуска основы оставьте пустыми. Настройки читаются через `from app.core.config import settings`, переменные окружения имеют приоритет. Ключи никогда не задавать с префиксом `VITE_`: такие значения попадают в браузер.

Терминал 1:

```sh
cd services/api
uv sync --locked
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API: `http://127.0.0.1:8000`; Swagger: `/docs`; OpenAPI: `/openapi.json`; `GET /health/live` → `200 {"status":"ok"}`. Для разработки можно добавить `--reload`. БД и Telegram/OpenAI не используются при старте. `/health/ready` ещё отсутствует (404), доступность БД пока не проверяется.

Терминал 2, из корня:

```sh
npm --prefix apps/web ci
npm --prefix apps/web run dev
```

Откройте `http://localhost:5173`. Vite слушает loopback, порт фиксирован (`strictPort`). Пути `/api` и `/health` проксируются в API на `127.0.0.1:8000`; browser origin остаётся `http://localhost:5173`, как в `PUBLIC_BASE_URL`. API-запросы frontend должны использовать относительные URL. При выборе другого browser origin обновите `PUBLIC_BASE_URL` перед реализацией входа. В production единый origin обеспечит reverse proxy из T01.

Проверка сборки:

```sh
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

Результат сборки — `apps/web/dist`, он исключён из Git. `npm --prefix apps/web run preview` предназначен только для просмотра сборки, не заменяет будущий production reverse proxy. Остановка обоих серверов — `Ctrl+C` в каждом терминале.

## Что есть и что делать дальше

- Созданы API `app.main:app`, конфигурация, liveness с Pydantic-схемой, runtime OpenAPI, минимальный React/TypeScript/Vite, lock-файлы, `.env.example` и `.gitignore`.
- A (инициатор) продолжает T01: Dockerfile/Compose, `/health/ready` с настоящей проверкой БД (200/503), экспорт OpenAPI, генерацию TS, Vitest/Playwright/PWA и запуск с чистого клона другим участником. **LoginPage и вся клиентская авторизация тоже принадлежат A**; они не реализованы в основе.
- B может сразу начать T02 от опубликованной основы: `db.py`, `security.py`, модели, миграции, серверные сессии/CSRF, права и справочники. SQLAlchemy, psycopg и Alembic уже установлены; дополнительные зависимости запрашиваются у A. БД/модели/миграции/auth-модули в этой подготовке не создавались.
- Не пересоздавать `main.py`, `config.py`, manifest/lock-файлы, web и инструкции. A — единственный ответственный за эти общие файлы, Compose и генерируемые контракты. B передаёт A импорты готовых routers, требования пакетов и настроек; A вносит отдельный коммит, B подтягивает его.

Точные договорённости — [C1 в plans.md](../plans.md#c1-данные-авторизация-и-api): sync SQLAlchemy + `postgresql+psycopg://...`; будущие `Base`/`get_db`, Session на запрос и явный commit сервисом; `router` из каждого модуля, единственный `/api/v1` в main. Серверная HttpOnly cookie сохранена; согласованы JSON входа/выхода/me, единая ошибка и CSRF через `/auth/csrf` и `X-CSRF-Token`. Серверные Pydantic-схемы — источник OpenAPI, клиентские типы будут генерироваться A. Эти интерфейсы **не заменены фиктивными реализациями**. Третий участник подключается позже.

Экспорт `uv run python -m app.export_openapi`, `generate:api`, `test`, `test:e2e`, Compose и команды миграций **пока не существуют**. T01 — IN_PROGRESS, T02 — TODO, общая основа — REVIEW до интеграции.

## Фактические проверки 2026-10-03

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

## Как передать основу обоим участникам

Эти команды предназначены для владельца; агент push/merge не выполнял. В данном клоне:

```sh
git push -u origin chore/parallel-foundation
```

Затем каждый участник в своём клоне получает **одну и ту же** опубликованную основу:

```sh
git fetch origin
# A:
git switch -c feat/T01-bootstrap origin/chore/parallel-foundation
# B (в другом клоне):
git switch -c feat/T02-data-auth origin/chore/parallel-foundation
```

Сначала убедитесь, что рабочее дерево своего клона чистое, или сохраните свои изменения. Оба проверяют совпадение базового SHA (`git rev-parse origin/chore/parallel-foundation`). Общие изменения A переносить согласованным коммитом, не переписывая ветку B. В `main` основу можно интегрировать позже отдельным review; сейчас merge не требуется.

Справка по выбранным интерфейсам: [SQLAlchemy psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg), [Vite: требования среды](https://vite.dev/guide/), [установка uv](https://docs.astral.sh/uv/getting-started/installation/).
