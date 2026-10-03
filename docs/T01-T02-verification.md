# Проверка интеграции Т01–Т02 — 2026-10-03

Ветка `codex/t01-t02-integration` сохраняет истории Т01 `bff99ab` и серверной Т02 `4ce5aca` через merge `2c2a207`. Изменения интеграции: настоящий app.main, типизированный клиент входа/сессии, migrations в образе, migration-service, локальная qosthub_demo, ограниченное доверие Nginx и приёмка с двумя отдельными тестовыми БД.

Фактически выполнено локально (Python 3.12.14, uv 0.12.22, Node 24.19.0, npm 12.2.0):

| Команда | Результат |
| --- | --- |
| `pytest tests/test_app_integration.py -q` до подключения | 4 FAIL: отсутствие маршрутов, handlers и dispose в lifespan |
| `uv run --locked pytest tests/test_app_integration.py tests/test_health.py tests/test_export_openapi.py -q` | 12 PASS; предупреждение Starlette устранено закреплением httpx2 2.13.1 через uv |
| `DATABASE_URL=invalid-url uv run --locked python -m app.export_openapi` | PASS, без БД |
| `npm --prefix apps/web run generate:api` | PASS, настоящие auth/catalog/shift схемы |
| `npm --prefix apps/web run test -- --run` | Vitest 13/13 PASS |
| `npm --prefix apps/web run typecheck` | PASS, включая браузерные тесты |
| `npm --prefix apps/web run build` | PASS, production PWA |
| `python -m compileall -q services/api/app infra tests`; `git diff --check` | PASS |

В Windows использованы локально установленные исполняемые файлы и `.venv`; переносимые команды приведены выше. Старые lock-пины сохранены; добавлены только httpx2 и его зависимости. Docker локально отсутствует: PostgreSQL, миграционный roundtrip, контейнеры, IP-лимиты, recovery/persistence и production Playwright ещё не проверены для этого head; результат и ссылка на CI будут записаны после фактического завершения.

Ревью интеграции выполняется самостоятельно: AGENTS.md разрешает подагентов только при явном выборе этого способа, которого здесь нет. Это не подтверждение запуска вторым участником. До получения такого подтверждения T01 сохраняет REVIEW после интеграции; T02 может стать DONE после полной приёмки и слияния.
