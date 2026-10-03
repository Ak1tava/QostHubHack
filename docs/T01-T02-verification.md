# Проверка интеграции Т01–Т02 — 2026-10-03

Ветка `codex/t01-t02-integration` сохраняет истории Т01 `bff99ab` и серверной Т02 `4ce5aca` через merge `2c2a207`. Изменения интеграции: настоящий app.main, типизированный клиент входа/сессии, migrations в образе, migration-service, локальная qosthub_demo, ограниченное доверие Nginx и приёмка с двумя отдельными тестовыми БД.

Фактически выполнено локально (Python 3.12.14, uv 0.12.22, Node 24.19.0, npm 12.2.0):

| Команда | Результат |
| --- | --- |
| `pytest tests/test_app_integration.py -q` до подключения | 4 FAIL: отсутствие маршрутов, handlers и dispose в lifespan |
| `.venv/Scripts/python.exe -m pytest tests/test_app_integration.py tests/test_health.py tests/test_export_openapi.py -q` из `services/api` | 12 PASS; предупреждение Starlette устранено закреплением httpx2 2.13.1 через uv |
| `.venv/Scripts/python.exe -m app.export_openapi` из `services/api`, env `DATABASE_URL=invalid-url` | PASS, без БД |
| `npm --prefix apps/web run generate:api` | PASS, настоящие auth/catalog/shift схемы |
| `npm --prefix apps/web run test -- --run` | Vitest 13/13 PASS |
| `npm --prefix apps/web run typecheck` | PASS, включая браузерные тесты |
| `npm --prefix apps/web run build` | PASS, production PWA |
| `python -m compileall -q services/api/app infra tests`; `git diff --check` | PASS |

В Windows npm запускался через `node` и ранее установленный `npm-cli.js`; команды npm в таблице обозначают соответствующие вызовы CLI 12.2.0. Старые lock-пины сохранены; добавлены только httpx2 и его зависимости. Повторная штатная генерация обоих контрактов дала идентичные байты. Docker локально отсутствует; полная приёмка выполнена в GitHub Actions.

[CI 37132211539 — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37132211539), актуальный на момент проверки [head 00c199b](https://github.com/Ak1tava/QostHubHack/commit/00c199be8a4491685b66c3849169783e5eac668d), [интеграционный PR №2](https://github.com/Ak1tava/QostHubHack/pull/2):

| Фактическая команда CI | Результат |
| --- | --- |
| `uv run --locked pytest -q` | **66 PASS**, включая права, CSRF/Origin, expiry, конкурентные запросы и PostgreSQL constraints; пустая миграционная БД upgrade/check/downgrade/upgrade |
| `DATABASE_URL=invalid-url uv run --locked python -m app.export_openapi`; `npm --prefix apps/web run generate:api`; `git diff --exit-code -- packages/contracts` | PASS, генерация без БД и без diff |
| `npm --prefix apps/web run test -- --run`; `npm --prefix apps/web run build` | Vitest **13 PASS**, typecheck и production build PASS |
| `docker compose config --quiet`; `docker compose up --build -d --wait --wait-timeout 120`; `docker compose exec -T api .venv/bin/alembic check` | PASS: migration-service завершился до API, schema drift отсутствует |
| `python infra/verify_proxy.py` | PASS: два настоящих клиента имеют отдельные IP-лимиты; меняющиеся forwarded headers не обходят 60/min; прямой недоверенный peer не подменяет IP |
| `python infra/verify_stack.py` | PASS: readiness 200 → 503 → 200, liveness доступен при остановке БД; аккаунты, кластер PostgreSQL и файлы фотохранилища сохранены после пересоздания контейнеров |
| `npm --prefix apps/web run test:e2e` | Playwright **9 PASS** через production Nginx: PIN с ведущими нулями, HttpOnly, reload, logout → 401, неверные данные/CSRF/422/429/сеть, настоящая серверная expiry, PWA и offline без кеша приватных ответов/SPA HTML вместо API |

Тестовые базы `qosthub_test_ci` и `qosthub_migration_test_ci` отделены от `qosthub_demo`. Эфемерные пароли, cookie и POST auth не включены в Git/диагностику. Повторная проверка финального head PR и CI main записываются после завершения.

Ревью интеграции выполняется самостоятельно: AGENTS.md разрешает подагентов только при явном выборе этого способа, которого здесь нет. Это не подтверждение запуска вторым участником. До получения такого подтверждения T01 сохраняет REVIEW после интеграции; T02 может стать DONE после полной приёмки и слияния.
