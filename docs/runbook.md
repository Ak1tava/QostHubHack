# Запуск и проверка

Нужны Python 3.12, uv и Node.js 24 с npm 12. Lock-файлы уже созданы: `services/api/uv.lock`, `apps/web/package-lock.json`. Проверенная среда: Windows, Python 3.12.14, uv 0.12.22, Node 24.19.0, npm 12.2.0. Команды ниже выполняются из корня репозитория, если не указан другой каталог.

Для контейнерного запуска достаточно Docker с Compose v2; локальные Python/Node не нужны. Для работы используйте интегрированную `main`; Т01 и Т02 прошли полную автоматическую приёмку.

## Контейнерный запуск

Скопируйте `.env.example` в корневой `.env`, только если файла ещё нет. Задайте случайный локальный `POSTGRES_PASSWORD` и `DATABASE_URL=postgresql+psycopg://qosthub:URL_ENCODED_PASSWORD@db:5432/qosthub_demo`; в URL должен находиться тот же пароль с percent-encoding спецсимволов. Внешние токены оставьте пустыми. Не задавайте секреты через `VITE_`.

```sh
docker compose config --quiet
docker compose up --build -d --wait --wait-timeout 120
```

Web и PWA: `http://localhost:5173`; API: `http://127.0.0.1:8000`; Swagger: `http://localhost:5173/docs`; `/health/live` → 200 `{"status":"ok"}`; `/health/ready` → 200 `{"status":"ready"}`. Неверная/недоступная БД → 503 `{"status":"not_ready"}`, liveness остаётся доступен. Nginx сохраняет общий browser origin, cookie и Origin; API/БД опубликованы только на loopback.

```sh
docker compose logs --tail 100
docker compose down
```

Обычный `down` сохраняет volumes PostgreSQL и приватных фото; фото не раздаются Nginx. Отдельный сервис `migrate` выполняет `alembic upgrade head` после готовности PostgreSQL; API запускается после успешного завершения этого сервиса. Импорт и lifespan приложения не выполняют миграции. Повторный явный запуск: `docker compose run --rm migrate`; проверка схемы: `docker compose exec api .venv/bin/alembic check`. Worker добавляется в T06.

Если volume уже создавался для базы `qosthub`, изменение `POSTGRES_DB` не создаст новую базу автоматически. Запустите `docker compose up -d --wait db`, затем `docker compose exec db createdb -U qosthub qosthub_demo` один раз и повторите общий запуск. Существующая база и её данные сохраняются; `down --volumes` применяется только к одноразовой CI-среде.

Nginx перезаписывает входящие `X-Forwarded-For`/`X-Real-IP` адресом соединения. Uvicorn доверяет только Nginx `172.30.42.10`, а не всей сети или `*`; прямое обращение к API не позволяет подменить IP. Compose использует сеть `172.30.42.0/24`; при конфликте с вашей сетью согласованно измените subnet, адрес web и `FORWARDED_ALLOW_IPS` в Compose.

Создайте локальные аккаунты: `docker compose exec api .venv/bin/python -m app.modules.auth.demo --confirm-demo`. Команда интерактивно спрашивает два пароля, создаёт `demo-master`/`demo-worker`, участок, бригаду и смену; существующие аккаунты не перезаписываются. Она разрешена только для локальных `qosthub_demo*`/`qosthub_test*`. В web доступны вход и выход; ПИН вводится строкой. Серверные проверки прав, CSRF/Origin, ротация и отзыв сессии действуют на реальных маршрутах.

## Нативная разработка API и web

`.env` необязателен. При необходимости скопируйте `.env.example` в `.env` в **корне репозитория**, не перезаписывая существующий файл; секреты и `DATABASE_URL` для запуска основы оставьте пустыми. Настройки читаются через `from app.core.config import settings`, переменные окружения имеют приоритет. Ключи никогда не задавать с префиксом `VITE_`: такие значения попадают в браузер.

Терминал 1:

```sh
cd services/api
uv sync --locked
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

API: `http://127.0.0.1:8000`; Swagger: `/docs`; OpenAPI: `/openapi.json`; `GET /health/live` → `200 {"status":"ok"}`. Для разработки можно добавить `--reload`. Импорт/startup не подключается к БД. Без `DATABASE_URL` readiness возвращает 503; для локальной PostgreSQL URL должен использовать `localhost`, а не Compose-host `db`.

Для входа задайте локальный PostgreSQL URL с базой `qosthub_demo`, выполните из `services/api` команды `uv run --locked alembic upgrade head`, `uv run --locked alembic check`, `uv run --locked python -m app.modules.auth.demo --confirm-demo`. На локальном HTTP используйте `SESSION_COOKIE_SECURE=false`, на HTTPS cookie всегда Secure. `SESSION_SECRET` для непрозрачных сессий не используется.

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

Результат сборки — `apps/web/dist`, он исключён из Git. `npm --prefix apps/web run preview` предназначен только для просмотра сборки; production web и API запускаются через Nginx в Compose. Остановка обоих серверов — `Ctrl+C` в каждом терминале.

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

## Приёмка интеграции Т01–Т02

Перед `uv run --locked pytest -q` создайте **две отдельные одноразовые** PostgreSQL-базы: `qosthub_test_ci` и `qosthub_migration_test_ci`. Задайте `TEST_DATABASE_URL` и `MIGRATION_TEST_DATABASE_URL` через окружение с этими именами; рабочий `DATABASE_URL` к fixtures не относится. Тесты удаляют/создают таблицы в первой базе, делают upgrade/check/downgrade/upgrade во второй. Запрещено направлять их в базу приложения; защитные проверки имён выполняются самими тестами.

CI создаёт эти базы до pytest, проверяет все серверные тесты на настоящем `app.main`, экспорт без БД и отсутствие diff при повторной генерации, Vitest/typecheck/build, образы и migration-service. Затем выполняет `alembic check`, `infra/verify_proxy.py` (раздельные IP-лимиты и отказ подмены через Nginx/прямой API), `infra/verify_stack.py` (отказ/восстановление БД, сохранность аккаунтов и фотохранилища) и Playwright через production Nginx. Браузерные аккаунты синтетические; пароли создаются в CI и маскируются. Auth-трейсы отключены; сырые браузерные отчёты не публикуются. При сбое сохраняются только Compose-статусы/логи с маскированием секретов из `.env` и окружения, включая E2E_PASSWORD.

Фактические результаты интеграции — [T01-T02-verification.md](T01-T02-verification.md). Исторические проверки ниже относятся к указанным коммитам Т01/общей основы. 2026-10-03 пользователь исключил отдельный запуск другим участником из текущей приёмки Т01; эта ручная проверка не выполнялась. Критерии Т01/Т02 подтверждены интеграцией и успешным CI main.

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

Playwright затем проверяет Nginx proxy и offline-границы настоящего service worker. При сбое сохраняются очищенные от значений секретов Compose-логи и браузерные артефакты на 7 дней. Завершение job удаляет только одноразовые CI-volumes. Статус Т01 определяется только `plans.md`.

**Фактический CI — PASS:** [run 37127545893](https://github.com/Ak1tava/QostHubHack/actions/runs/37127545893), commit `f26c44a1077a7388106be9b90e879fb6dfdf06fa`, Ubuntu 24.04. pytest 8/8, Vitest 3/3, Playwright 3/3; locked install, повторная генерация без diff, production build, Compose config/up и все контейнеры Healthy. `verify_stack.py` вывел `PASS: real SQL readiness, database outage/recovery, PostgreSQL and private photo volume persistence`. Внешние интеграционные токены были пустыми. Саморевью diff выполнено исполнителем без подагентов по AGENTS.md; независимая проверка другим участником на этом этапе не выполнялась; позднее пользователь исключил её из текущей приёмки (см. карточку Т01 в plans.md).

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
## T10: HTTPS-стенд и Telegram

Для контейнерного стенда пользователь устанавливает и запускает Docker Desktop с Linux containers; агент не устанавливает GUI. Проверьте `docker version` и `docker compose version`. `compose.restore.yaml` требует Compose ≥2.24.4: поддержка `!override` описана в [Docker Docs](https://docs.docker.com/reference/compose-file/merge/).

Секреты задаются пользователем в ignored `.env`: `POSTGRES_PASSWORD`, `DATABASE_URL`, `SESSION_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `OPENAI_API_KEY`. Не выводите `.env` или полный `docker compose config` с подставленными секретами в публичный лог. Аккаунты/пароли передаются отдельно. Начальный локальный запуск без внешних consumers:

```sh
docker compose up -d --build --wait db migrate api web
```

Portable cloudflared для Windows x64: загрузите официальный исполняемый файл в ignored `.tooling`; установка службы не требуется. [Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) выдаёт временный URL и прекращает работу вместе с процессом.

```powershell
New-Item -ItemType Directory -Path .tooling -Force | Out-Null
Invoke-WebRequest https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile .tooling/cloudflared.exe
& ./.tooling/cloudflared.exe tunnel --url http://127.0.0.1:5173
```

Сохраните только hostname выданного URL в `TUNNEL_HOSTNAME` без scheme/порта/пути; `PUBLIC_BASE_URL` в `.env` — точный `https://<hostname>`, `SESSION_COOKIE_SECURE=true`. Задайте `DEMO_AS_OF` календарным днём демонстрации. `--allowed-mail` не применять: интерактивная email-проверка не подходит Telegram webhook. Приложение сохраняет собственные сессии, CSRF/Origin и проверку webhook secret.

```sh
docker compose stop ai-worker worker
docker compose -f compose.yaml -f compose.tunnel.yaml up -d --build --force-recreate --wait api web
docker compose -f compose.yaml -f compose.tunnel.yaml run --rm seed-demo
```

Seed спрашивает пароль или берёт локальный `DEMO_PASSWORD` (не менее восьми символов). В контейнер монтируется `data/demo:ro`; приватные фото пишутся в реальный `photo_data`, тот же volume читает API/ИИ. Runtime аналитики не читает `expected_anomalies.json`. При смене `DEMO_AS_OF` используйте новую отдельную демо-БД: повтор с изменённой датой не является обновлением прежних 500 нарядов.

После readiness и разрешения живой приёмки:

```sh
docker compose -f compose.yaml -f compose.tunnel.yaml up -d --force-recreate --wait worker
docker compose -f compose.yaml -f compose.tunnel.yaml exec api .venv/bin/python -m app.modules.telegram.manage set-webhook
docker compose -f compose.yaml -f compose.tunnel.yaml exec api .venv/bin/python -m app.modules.telegram.manage info
```

При каждом новом URL пересоздайте API, web, notification worker и используемый AI consumer, затем повторите `set-webhook`. Tunnel overlay заменяет лишь `${TUNNEL_HOSTNAME}` через [NGINX_ENVSUBST_FILTER](https://github.com/nginx/docker-nginx/blob/master/mainline/alpine-slim/20-envsubst-on-templates.sh); `$uri`/`$remote_addr` сохраняются. Чужой Host получает 421, healthcheck использует правильный Host. `X-Forwarded-Proto=https` фиксирован только в overlay; `X-Forwarded-For`/`X-Real-IP` берутся из `$remote_addr`, `Forwarded`/`CF-Connecting-IP`/`True-Client-IP` удаляются. API доверяет только Nginx `172.30.42.10`.

Два iPhone через один host tunnel могут иметь общий серверный IP и общую квоту входа/CSRF. Не подменяйте заголовки и не отключайте rate limit; при 429 дождитесь указанного `Retry-After`. Первую живую приёмку выполнить на двух iPhone; Android остаётся отдельным обязательным замером.

## T10: live AI worker с суммарным лимитом $2

Обычный `ai-worker` должен быть остановлен, включая нативные процессы вне Compose. В tunnel overlay он исключён из обычного `up` профилем `unbudgeted-ai`; этот профиль на живой бюджетной приёмке не включать. `--ordinary-worker-stopped` подтверждает проверку оператором, но не останавливает сторонний процесс автоматически. После проверки readiness и оплаты запускается только один foreground consumer:

```sh
docker compose stop ai-worker
docker compose -f compose.yaml -f compose.tunnel.yaml build ai-demo-worker
docker compose -f compose.yaml -f compose.tunnel.yaml run --rm --no-deps ai-demo-worker
```

Лимит всего запуска и его перезапусков — $2; ledger/frozen config/OS lock хранятся в `live_budget`. Дополнительно берётся PostgreSQL advisory lock. До каждого paid I/O сохраняется полный консервативный резерв; output caps совпадают с существующим provider. Неизвестный расход после ошибки/crash остаётся зарезервированным; повторный старт с неразрешённой записью требует аудита и отказывается от новых вызовов. Ошибка provider, неизвестная цена или недостаточный резерв останавливают consumer; автоматического перехода к обычному worker нет. Ledger не удалять, volume не пересоздавать ради нового лимита, лимит на restart не увеличивать. Цены берутся из существующей таблицы T07 с зафиксированной датой, неизвестная модель запрещена. Мастер принимает работу независимо от доступности ИИ.

Нативный эквивалент (правильные env и PRIVATE photo path настраивает оператор):

```sh
cd services/api
uv run python -m app.workers.budgeted_reviews --live --ordinary-worker-stopped --ledger ../../.tooling/t10-live/budget.json --budget-usd 2 --max-seconds 600
```

PhotoService хеширует сохранённые санитизированные байты. Старые загрузки, где хеш относился к исходнику до удаления EXIF/пережатия, могут потребовать повторной загрузки; проверка целостности не обходится автоматически.

## T10: резервная копия и восстановление отдельно

На время согласованной копии остановите все consumers и API, чтобы БД, фото и бюджет представляли один снимок. Резервная копия внутренняя: DB содержит данные сессий/привязок, её не публикуют и не коммитят. Используйте ignored `artifacts/backup/`.

```sh
docker compose stop api worker ai-worker
docker compose exec db pg_dump -U qosthub -Fc -f /tmp/qosthub.dump qosthub_demo
docker compose cp db:/tmp/qosthub.dump artifacts/backup/qosthub.dump
docker compose run --no-deps --name qosthub-photo-backup --entrypoint tar api -C /workspace/data/photos -czf /tmp/photos.tgz .
docker cp qosthub-photo-backup:/tmp/photos.tgz artifacts/backup/photos.tgz
docker rm qosthub-photo-backup
docker compose -f compose.yaml -f compose.tunnel.yaml run --no-deps --name qosthub-budget-backup --entrypoint tar ai-demo-worker -C /workspace/data/live-budget -czf /tmp/live-budget.tgz .
docker cp qosthub-budget-backup:/tmp/live-budget.tgz artifacts/backup/live-budget.tgz
docker rm qosthub-budget-backup
```

Создайте папку копии заранее. Foreground budgeted worker остановите до снимка и убедитесь, что он завершился; `.env` в архивы не включается. Затем верните API/notification worker с актуальным tunnel overlay; обычный AI consumer остаётся выключен.

Для пробного восстановления используйте проект `qosthub-restore`, `compose.restore.yaml` и локальную `.env.restore` с отдельным стендом. Его порты 55433/8001/5174, подсеть `172.30.43.0/24`, volumes отдельные; consumers отключены, чтобы не повторять Telegram/paid calls. Не подключайте к нему volumes рабочего проекта.

```sh
docker compose -p qosthub-restore --env-file .env.restore -f compose.yaml -f compose.restore.yaml up -d db
docker compose -p qosthub-restore --env-file .env.restore -f compose.yaml -f compose.restore.yaml cp artifacts/backup/qosthub.dump db:/tmp/qosthub.dump
docker compose -p qosthub-restore --env-file .env.restore -f compose.yaml -f compose.restore.yaml exec db pg_restore -U qosthub --exit-on-error -d qosthub_demo /tmp/qosthub.dump
docker compose -p qosthub-restore --env-file .env.restore -f compose.yaml -f compose.restore.yaml build api web
docker compose -p qosthub-restore --env-file .env.restore -f compose.yaml -f compose.restore.yaml run --rm --no-deps --volume ./artifacts/backup:/backup:ro --entrypoint tar api -C /workspace/data/photos -xzf /backup/photos.tgz
docker compose -p qosthub-restore --env-file .env.restore -f compose.yaml -f compose.restore.yaml up -d --wait api web
```

Архив монтируется read-only в restore-контейнер; `/tmp` другого контейнера не разделяется автоматически. Сверьте число нарядов/решений, открытие сохранённых приватных фото, компонент рейтинга и новую загрузку. Запуск `migrate` использует актуальный код и сохранённый alembic head; восстановленный ledger хранится отдельно для аудита, его копию не превращают во второй платный запуск. Запишите SHA/среду/фактический результат в `docs/verification.md`. Документация этих команд сама по себе не подтверждает восстановление.
