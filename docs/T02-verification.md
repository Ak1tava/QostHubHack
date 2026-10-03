# Проверка серверной T02

Дата: 2026-10-03. Ветка: feat/T02-data-auth. База: 8a26387c0348a6add95378c7d4bc16c80e47bc86 (chore/parallel-foundation). Проверенный код и этот отчёт находятся в одном коммите; SHA коммита определяется git log -1 --format=%H.

## Среда

Windows; Python 3.12.15, uv 0.12.22; настоящий локальный PostgreSQL (embedded-postgres 18.4.0-beta.17); зависимости API из исходного uv.lock. pytest/httpx/httpx2 предоставлены через uv --with, manifests и lock-файлы A не менялись.

Локальная копия восстановлена через авторизованный GitHub connector: содержимое каждого blob, дерева и исходного коммита сверено по Git SHA. Локальный репозиторий shallow на исходном коммите; CLI-авторизация GitHub не работала. Push и merge не выполнялись.

## Фактические результаты

- Первое поведенческое RED: tests/test_authz.py — 404 вместо 401 на GET /api/v1/auth/me до появления auth router.
- Первые auth/model проверки: 37 passed.
- Расширенный pytest -q: 54 passed, 0 failed, без warnings; 121.26 секунды после исправлений ревью. Включены auth, модели, миграции и конкурентные запросы.
- Четыре регрессии ревью сначала воспроизвели ошибки (RED), затем прошли: expiry /me, нагрузка другого участка, блокировка роста IP-ключей и очистка истёкших ограничителей.
- Настоящий HTTP через локальный uvicorn: csrf → login → me → catalog → shift → logout → 401 — PASS; реальные cookie и PostgreSQL, секреты не печатались.
- Ruff format и check --isolated --select F,I — PASS.
- alembic upgrade head на новой пустой PostgreSQL БД — exit 0.
- alembic check — No new upgrade operations detected, exit 0.
- alembic downgrade base — exit 0; отдельный test_empty_postgres_migration_roundtrip подтвердил пустые таблицы, upgrade, совпадение metadata, downgrade и повторный upgrade.

Обычные команды из services/api:

~~~sh
uv run --locked --with pytest --with httpx --with httpx2 pytest -q
uv run alembic upgrade head
uv run alembic check
~~~

Для первого запуска здесь использовался локальный work/runtime/verify.cjs: он задаёт TEST_DATABASE_URL/MIGRATION_TEST_DATABASE_URL только одноразовым локальным БД и запускает указанную uv-команду. URL и пароли не включены в Git. Для воспроизведения на другой машине нужны собственные одноразовые PostgreSQL БД и переменные из T02-integration.md.

## Границы результата

Маршруты проверены через настоящее ASGI-приложение с TestClient, SQL и PostgreSQL; состояние БД и HTTP-контракты не заменены заглушками. tests/t02_app.py позволяет поднять тот же набор routers через uvicorn для локального HTTP.

Общий app.main, frontend, генератор типов и Docker принадлежат A и не изменены. Проверка входа через LoginPage ещё не выполнена: A должен подключить routers и frontend. Карточки/фотографии/WS появятся в T03/T05/T04; соответствующие HTTP-проверки доступа выполняются тогда. Статус серверной части — REVIEW, не DONE всего интегрированного приложения.
