# T07 — проверка и передача

2026-10-06. Владелец C + B / Codex, ветка `codex/t07-ai-review`,
[draft PR №7](https://github.com/Ak1tava/QostHubHack/pull/7), код `87a5512`.
База `origin/main` 7fd73c1; T09 56d3501 подключена merge c3e9277 без замены
актуальных статусов T04–T06. Статус задачи определяется только [plans.md](../plans.md).

## Реализация

Responses API/Pydantic, серверные правила и модельная маршрутизация:
Luna low для простого планового текста, Sol medium для основной проверки,
один переход на Astra medium при неразрешённом противоречии с пригодными доказательствами.
Фото передаются байтами; внешних публичных URL нет. ИИ не закрывает наряд.

Отдельный ai-worker, outbox receipts и persisted stages/calls. Lease-token fencing,
максимум три сетевые попытки, проверки revision/version/назначения и атомарная
приёмка мастером. Поздний ответ сохраняет расходы, но не меняет наряд.
Без ключа — blocked/api_key_missing, AIReview не выдумывается.

Карточка показывает результат, доказательства и решение мастера. Причины проверяет
сервер; после 409 требуется новое подтверждение. При обрыве ответа повторяются
тот же command и Idempotency-Key. Миграция 0005 останавливается при исторической
оценке вне 1–5, сохраняя исходную оценку; автоматической конвертации нет.

## Фактические проверки

Локально использовались PostgreSQL 17.11 и отдельные disposable test/migration/demo
БД на loopback; ключ модели отсутствовал. Windows Python запущен с PYTHONUTF8=1.
Секреты и локальные журналы хранятся только в игнорируемой `.tooling/t07`.

| Проверка | Команда | Результат |
|---|---|---|
| Полный API / PostgreSQL | `pytest -q -p no:cacheprovider --tb=short` | 1467 PASS, 281.51s |
| Backend T07 / PostgreSQL | `pytest tests/test_review_policy.py tests/test_master_decision.py tests/test_review_worker.py -q` | 54 PASS |
| Провайдер/правила/evals | `pytest tests/test_ai_review.py tests/test_ai_provider.py tests/test_ai_eval_runner.py -q` | 47 PASS |
| Миграции / PostgreSQL | `pytest tests/test_ai_review_migrations.py tests/test_migrations.py -q` | 5 PASS |
| Полный Vitest | `npm --prefix apps/web run test -- --run` | 54 PASS, 15 файлов |
| TypeScript и production build | `npm --prefix apps/web run build` | PASS |
| Браузерный production preview + настоящий API/worker | `playwright test --retries=0 --workers=1` | 15 PASS, без повторов |
| Согласованность контрактов | `python -m app.export_openapi`, `npm --prefix apps/web run generate:api` | оба SHA256 неизменны |
| Offline dev и отсутствие ключа | команды из [evals/results.md](../evals/results.md) | 20 dev, 0 вызовов/$0; live exit 2, holdout не использован |

Docker локально отсутствует; контейнерная приёмка выполнена в
[CI 37497053891 — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37497053891),
head `87a5512`. Полный PostgreSQL pytest: **1467 PASS** (199.51s),
production Playwright: **15 PASS** без retries (26.7s). Миграции/Alembic check,
контракты/TypeScript/Vitest/build, Compose/Nginx/IP isolation, outage/recovery,
сохранность БД и приватных фото при пересоздании API — PASS.

`DATABASE_URL="$PHOTO_ACCEPTANCE_DATABASE_URL" services/api/.venv/bin/python infra/verify_review_worker.py`
— **PASS**: реальные API/ai-worker, blocked без ключа, restart, повторная доставка
того же outbox submit, отсутствие двойной оценки и отмена. Аналогичная проверка
существующего Telegram worker тоже PASS. Платных запросов не было.
После первоначальной приёмки добавлено ограниченное повторение Windows atomic
replace и продолжение dev с сохранением результатов/расходов. Проверка на
тестовом провайдере: **65 PASS**, включая 18 recovery-тестов. Сетевой вызов не
начинается до сохранения резерва и не повторяется из-за сбоя записи. Holdout-resume
запрещён. Изменения IO/recovery независимо просмотрены без блокирующих замечаний.

Свежая [CI 37504054292 — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37504054292),
head `332f5fe`: **1485 PostgreSQL pytest PASS** (163.51s), **54 Vitest PASS**,
**15 production Playwright PASS** без retries (27.3s). Контракты/typecheck/build,
миграции/Alembic check, Compose/Nginx/recovery, restart/redelivery/cancel
AI worker и сохранность фото при пересоздании API — PASS. После этого head
меняется только Markdown-запись результатов CI.

## Живой прогон после ключа

2026-10-06: 20 dev + один проход 12 holdout, общий расход по консервативным тарифам
**$0.6868455**. Dev accuracy 55%, holdout 50%; положительных вердиктов нет,
25/32 human_review. API/refusal/schema ошибок нет; сервер отклонил сомнительные
доказательства/формулировки. Счётчики ложных принятий и возвратов равны нулю,
но качество принятия работ этим не подтверждается. T07 остаётся REVIEW.

Все версии/hashes, ошибки, latency, usage и расходы — [evals/results.md](../evals/results.md)
и [полный отчёт](../evals/reports/T07-live-2026-10-06.json). Повтор holdout запрещён;
дополнительные dev-запросы пользователь отклонил. Prompt/правила не менялись.
Ключи перенесены из tracked `.env.example` в ignored `.env`, в Git не сохранены.

Независимый reviewer GPT-6 Astra выявил две ошибки: tuple/list в JSON freeze и
истечение lease внутри финализации. Обе воспроизведены RED→GREEN; повторное
ревью исправлений не выявило блокирующих проблем. Дополнительно проверены rollback
после kernel flush, сохранность позднего usage и запрет dispatch неизвестной стадии.
Context7 `/openai/openai-python` использован точечно для `responses.parse` и raw response;
поведение SDK проверено настоящим HTTP MockTransport, без платных запросов.

## Запуск после добавления ключа

До добавления ключа остановить фоновую обработку: `docker compose stop ai-worker`
(если стек уже запущен). Лимит $5 относится к eval; обычные фоновые проверки не
учитываются в его ledger. Затем добавить OPENAI_API_KEY в корневую `.env` именно
этой ветки/развёртывания. Настройки уже есть в [.env.example](../.env.example).

Живой eval запускать последовательно из `services/api` после `uv sync --locked`:

Эта последовательность уже выполнена 2026-10-06. Текущий holdout использован;
повторять его нельзя. Сохранённые результаты перечислены выше.

```sh
uv run --locked python -m app.modules.ai_review.eval_runner --live --split dev
uv run --locked python -m app.modules.ai_review.eval_runner --freeze
uv run --locked python -m app.modules.ai_review.eval_runner --live --split holdout
```

Общий предел $5, резерв перед каждым вызовом, единый budget ledger в `.tooling/t07/evals`.
Holdout — один проход; не удалять ledger/freeze/marker ради повторной настройки.
Синтетические PNG из SVG не подтверждают качество на производственных фотографиях.
Метрики и ограничения: [evals/T07-runner.md](../evals/T07-runner.md).

После ограниченного прогона обычный стек запускается отдельно:

```sh
docker compose up --build -d --wait
```

Это применяет миграцию и запускает отдельный ai-worker с read-only photo volume.
При изменении только ключа пересоздать worker: `docker compose up -d --force-recreate ai-worker`.
Если миграция сообщает об оценках вне диапазона, решение о корректировке истории
принимает владелец данных; миграция их не пересчитывает.
До интеграции и подтверждённой живой приёмки задача остаётся REVIEW.
