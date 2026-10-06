# Интеграция T04–T05

Дата: 2026-10-06. Владелец: A / Codex. Ветка `codex/t04-t05-integration`.
База main: `7bc2b3ac4eace725ddf8bf6288d820041249474b`.
Сохранены исходные коммиты T04 `f74c42a556b3ab32e6cd78353b2ded4ee80f4f35`
и T05 `ef165618283a34e3e8efd5febbba4793eef5c04d`; T05 содержит T04 как родителя.

## Объём

Панель смены, выдача/канбан/карточка мастера, защищённый WebSocket,
очередь/действия исполнителя, неизменяемые отчёты и материалы,
приватные фотографии, сжатие и миграция 0003. HTTP закрытия и ИИ остаются T07.
T06/T09 не включаются в эту интеграцию.

Приёмка GitHub Actions дополнена проверкой настоящего фото из браузерного
сценария: авторизованное чтение через Nginx, отказ анонимному клиенту,
пересоздание API-контейнера с сохранением volume и повторная сверка UUID,
URL, байтов, SHA-256 и размеров. Скрипт допускает только CI=true,
loopback и явно разрешённые демо-БД; driver overrides запрещены.
DATABASE_URL для чтения с хоста задаётся только Python-процессу,
чтобы Compose продолжал подключать API к контейнеру db.

## Фактическая локальная проверка

Среда: macOS, Node 24.19.0, npm 12.2.0, Python 3.12.14, uv 0.12.22.
Зависимости установлены по неизменённым lock-файлам. Репозиторий восстановлен
через авторизованный GitHub connector с проверкой всех blob/tree/commit SHA;
git fsck прошёл. Локальная история shallow на main `7bc2b3a`.

- `npm --prefix apps/web run test -- --run`: 47 PASS.
- `npm --prefix apps/web run build`: typecheck приложения/E2E и production PWA PASS.
- Из services/api: `.venv/bin/python -m pytest tests/test_work_order_rules.py tests/test_work_order_models.py tests/test_work_order_internal.py::test_internal_kernel_exists tests/test_work_order_lifecycle.py::test_work_order_routes_are_registered_without_database tests/test_app_integration.py tests/test_health.py tests/test_export_openapi.py tests/test_ci_diagnostics.py -q -p no:cacheprovider -k 'not test_db' --tb=short`: 1016 PASS, 8 PostgreSQL-тестов намеренно исключены.
- `.venv/bin/python -m pytest tests/test_photo_persistence_guard.py -q -p no:cacheprovider --tb=short`: 17 PASS. RED воспроизведён на существующем CLI: Compose-БД qosthub_demo отклонялась; после исправления GREEN.
- Первый API-запуск из корня дал 2 FAIL/1014 PASS: subprocess не находил app. Правильная команда из services/api прошла; продуктовый код для этого не менялся.

На локальном Mac нет PostgreSQL и Docker. Полные pytest, миграции,
production Playwright, Nginx, Compose/recovery и настоящий photo persistence
проверяются GitHub Actions на актуальном PR head. До результата CI PASS не заявляется.

## Оставшаяся приёмка

Физические телефоны, реальные касания/время выдачи и загрузка фото на
мобильной сети не проверены. T04/T05 сохраняют REVIEW до выполнения
оставшихся критериев; успешная интеграция кода не заменяет эти замеры.
Черновик отчёта не восстанавливается после F5; уборка файлов-сирот после kill
между записью файла и commit не реализована. Ограничения исходных реализаций
сохранены в T04-verification.md и T05-verification.md.
