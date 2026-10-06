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

## Проверка PR и интеграция

[CI 37438252785 — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37438252785)
на head `f4a68b46311fd75c15c0fe05d8aefbd915820968`, Ubuntu 24.04:

- Целевые lifecycle/evidence/idempotency/authz: 182 PASS, 87,11 с.
- Полный PostgreSQL pytest: 1262 PASS, 107,02 с; миграционный roundtrip и metadata drift PASS.
- Vitest 47 PASS; typecheck/build и повторная генерация OpenAPI/TS без diff PASS.
- Production Playwright через Nginx: 14 PASS, 21,4 с; нет skipped/flaky.
- Compose/migration-service, подмена IP, остановка/восстановление БД и volumes: PASS.
- Настоящее приватное фото: anonymous GET 401, авторизованный GET 200/no-store;
  после пересоздания API совпали UUID, URL, SHA-256, 339774 байта и 1800×1200.
  Loopback GET 7,56/17,38 мс не является замером мобильной загрузки.

[PR №5 MERGED](https://github.com/Ak1tava/QostHubHack/pull/5),
main merge `24d05babca7f660664e451ff30e85e72c635357a`.
Дерево merge совпало с проверенным head; исходные T04/T05 сохранены как предки.
После merge обновлены только readme.md, plans.md и этот отчёт.
На локальном Mac нет PostgreSQL/Docker; для них использована настоящая среда CI.
Итоговая main проходит отдельную автоматическую приёмку.

## Решения и ревью

Использованы существующий plans.md и утверждённые реализации T04/T05 без
перепроектирования; работа велась в отдельной интеграционной ветке первоначально
пустого checkout. CLI не имел GitHub-авторизации, поэтому применён connector
с проверкой SHA; локальная история shallow. Полная контейнерная приёмка выполнена
в CI. Ревью всего diff выполнено отдельным проходом самим исполнителем:
AGENTS.md допускает подагентов только после явного выбора пользователя.
Независимого повторного ревью не заявляем.

T04/T05 остаются REVIEW, критерии не снимаются молча. T06/T09 и их известные
миграционные/URL/storage пересечения не включены в этот PR и требуют отдельной
интеграции. Дополнительная цена настоящего photo persistence — время CI;
отказ проверки блокирует интеграцию. Отложенный minor: экран очереди получает
все разрешённые страницы при обновлении; для большего объёма нужна отдельная
оптимизация, текущая демонстрация ограничена малым набором.

## Оставшаяся приёмка

Фото мастера при выдаче (R02: до пяти фото) пока не реализованы: текущий API
и экран разрешают before/after только ответственному исполнителю. Это
остаётся незавершённым критерием T04/T05, не объявляется выполненным.

Физические телефоны, реальные касания/время выдачи и загрузка фото на
мобильной сети не проверены. T04/T05 сохраняют REVIEW до выполнения
оставшихся критериев; успешная интеграция кода не заменяет эти замеры.
Черновик отчёта не восстанавливается после F5; уборка файлов-сирот после kill
между записью файла и commit не реализована. Ограничения исходных реализаций
сохранены в T04-verification.md и T05-verification.md.
