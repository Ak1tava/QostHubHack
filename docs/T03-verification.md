# Проверка T03

Владелец B / Codex, ветка `codex/t03-work-order-lifecycle`, база `01669c6`.
Источник статуса задачи — реестр `plans.md`. HTTP T05/T07 и доставка outbox не входят в эту работу.

## Фактические проверки

| Проверка | Результат |
| --- | --- |
| API route test до реализации | RED: отсутствовал `/api/v1/work-orders` |
| Матрица правил/схемы до реализации | RED: отсутствовали правила/схемы |
| `.venv/Scripts/python.exe -m pytest tests/test_work_order_rules.py tests/test_work_order_models.py tests/test_work_order_internal.py::test_internal_kernel_exists tests/test_work_order_lifecycle.py::test_work_order_routes_are_registered_without_database tests/test_app_integration.py tests/test_health.py tests/test_export_openapi.py -q -p no:cacheprovider -k 'not test_db' --tb=short` из services/api | PASS: 1014, 8 DB-тестов исключены; после sync по uv.lock без предупреждений |
| `DATABASE_URL=invalid-url python -m app.export_openapi`; `npm --prefix apps/web run generate:api`; `npm --prefix apps/web run typecheck` | PASS: экспорт без БД, генерация TS, оба проекта TypeScript |
| Независимое ревью подагентом production diff | Существенных замечаний нет; PostgreSQL ещё не проверен |
| Целевая команда T03, полный pytest, PostgreSQL concurrency и migration roundtrip | Ожидают CI; локальные тестовые БД не настроены |

## Матрица переходов, закреплённая тестами

| Действие | Исходные состояния | Результат | Роль / условие |
| --- | --- | --- | --- |
| create | новое | ISSUED | master, валидное назначение |
| accept | ISSUED, QUEUED | ACCEPTED | ответственный worker |
| queue | ISSUED, ACCEPTED | QUEUED | ответственный worker, добавление в конец |
| reject | ISSUED, ACCEPTED, QUEUED | REJECTED | worker, причина |
| reassign | ISSUED, ACCEPTED, QUEUED, REJECTED, PAUSED | ISSUED | master, причина, новое назначение |
| start | ACCEPTED | IN_PROGRESS | worker, нет другого активного |
| pause | IN_PROGRESS | PAUSED | worker, причина |
| resume | PAUSED | IN_PROGRESS | worker, нет другого активного |
| submit | IN_PROGRESS | SUBMITTED | worker, новая revision в транзакции T05 |
| begin_review | SUBMITTED | AI_REVIEW | только служебный вызов |
| request_rework | AI_REVIEW | REWORK | актуальный AIReview либо решение master, причина |
| restart | REWORK | IN_PROGRESS | worker, нет другого активного |
| close | AI_REVIEW | CLOSED | решение master, полнота отчёта |
| override_close | REWORK | CLOSED | решение master, причина, полнота отчёта |
| cancel | все нетерминальные | CANCELLED | master, причина |
| reprioritize | все нетерминальные | без изменения | master, новый приоритет |

`CLOSED`/`CANCELLED` терминальны. Публичные команды проверяются при каждом запросе, включая повтор ключа после переназначения. PostgreSQL-тесты проверяют независимые Session, одинаковые/разные ключи, два наряда одного исполнителя и rollback при сбое outbox.

Порядок блокировок: idempotency → наряд → пользователи по UUID. Для наряда/пользователей используется FOR NO KEY UPDATE: он сериализует команды, оставаясь совместимым с FK KEY SHARE при записи идемпотентности. Уникальный частичный индекс дополнительно запрещает второй IN_PROGRESS по coalesce(assignee_id,responsible_id).
