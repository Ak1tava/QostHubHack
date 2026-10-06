# T07 — проверка и передача

2026-10-06. Владелец C + B / Codex, ветка `codex/t07-ai-review`.
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

Docker локально отсутствует. В CI добавлена `infra/verify_review_worker.py`:
настоящие API/worker, blocked без ключа, restart, повторная доставка того же
outbox submit, отсутствие двойной оценки и отмена. Результат Compose фиксируется
после CI; успешная проверка синтаксиса скрипта не считается запуском Compose.

Независимый reviewer GPT-6 Astra выявил две ошибки: tuple/list в JSON freeze и
истечение lease внутри финализации. Обе воспроизведены RED→GREEN; повторное
ревью исправлений не выявило блокирующих проблем. Дополнительно проверены rollback
после kernel flush, сохранность позднего usage и запрет dispatch неизвестной стадии.
Context7 `/openai/openai-python` использован точечно для `responses.parse` и raw response;
поведение SDK проверено настоящим HTTP MockTransport, без платных запросов.

## Запуск после добавления ключа

Добавить OPENAI_API_KEY в корневую `.env` именно этой ветки/развёртывания.
Настройки моделей/reasoning уже есть в [.env.example](../.env.example).

```sh
docker compose up --build -d --wait
```

Это применяет миграцию и запускает отдельный ai-worker с read-only photo volume.
При изменении только ключа пересоздать worker: `docker compose up -d --force-recreate ai-worker`.
Если миграция сообщает об оценках вне диапазона, решение о корректировке истории
принимает владелец данных; миграция их не пересчитывает.

Живой eval запускать последовательно из `services/api` после `uv sync --locked`:

```sh
uv run --locked python -m app.modules.ai_review.eval_runner --live --split dev
uv run --locked python -m app.modules.ai_review.eval_runner --freeze
uv run --locked python -m app.modules.ai_review.eval_runner --live --split holdout
```

Общий предел $5, резерв перед каждым вызовом, единый budget ledger в `.tooling/t07/evals`.
Holdout — один проход; не удалять ledger/freeze/marker ради повторной настройки.
Синтетические PNG из SVG не подтверждают качество на производственных фотографиях.
Метрики и ограничения: [evals/T07-runner.md](../evals/T07-runner.md).
До интеграции и подтверждённой живой приёмки задача остаётся REVIEW.
