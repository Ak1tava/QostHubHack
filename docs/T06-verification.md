# Проверка Т06 — 2026-10-05

Ветка: feat/T06-telegram, база main 7bc2b3ac4eace725ddf8bf6288d820041249474b. Main не изменялась. Т09 находится в отдельной ветке; Т06 не требует её слияния. Итоговый commit SHA определяется командой git log -1 --format=%H после фиксации этой ветки.

## Среда

Windows, Python3.12, PostgreSQL18.4 на localhost:55432, отдельные qosthub_test_t06 и qosthub_migration_test_t06. Использованы существующий locked Python runtime и npm12.2.0 с npm ci по неизменённому package-lock.json. Пакеты и lock-файлы не менялись. Docker отсутствует; контейнерный запуск не заявляется проверенным.

На этой машине команда проверки использует сохранённый runner work/runtime/t06-run.py и Python из существующей локальной .venv. Runner задаёт TEST_DATABASE_URL/MIGRATION_TEST_DATABASE_URL, cwd services/api и отдельные временную папку/pytest cache в workspace. Эквивалент для обычной среды: из services/api выполнить uv run --locked pytest -q с явно заданными отдельными тестовыми PostgreSQL URL. Fixtures очищают только тестовые БД; производственную БД использовать нельзя.

## Фактические результаты

- Исходная версия:1152 PASS,1 setup error в test_ci_diagnostics_redact_file_and_environment_secrets из-за WinError5 в внешней папке pytest Temp. После задания workspace basetemp затронутый тест:1 PASS. Затем cache_dir тоже перенесён в отдельную папку. Код приложения и утверждения теста для этой ошибки не менялись.
- Целевые Т06 до ревью:55 отдельных случаев проверены. Основной прогон linking/deadlines/recovery/client:52 PASS69.72s; добавленные точные границы3/10/30 минут и проверки доступа плюс linking/export/appintegration:23 PASS36.42s (часть тестов повторяется между прогонами; числа не складываются).
- Исправления ревью:66 целевых тестов PASS142.28s, включая11 новых регрессий. RED9FAIL/2PASS подтвердил stale ORM, задержку health4.032s при DB lock, необработанные DB errors и отсутствие5 labels. Повторное scoped code review PASS; исходные4 Important устранены, Minor о heartbeat отложен. Детали: docs/T06-review.md. Redirect fixture после корректного чтения POST body и Content-Length0:3 отдельных PASS; прежние timeout/assertions сохранены.
- Новый код имел подтверждённые RED→GREEN для отсутствующих маршрутов/worker, HTTP-клиента, переноса сроков RETRY/BLOCKED при reprioritize, управляемых часов/lease и FK-lock конфликта, а также запрета HTTP redirect. Не все55 случаев выполнялись индивидуально в RED; это не утверждается.
- test_empty_postgres_migration_roundtrip:1 PASS2.74s. Проверены установка0001 с существующими данными, upgradehead0003, сравнение metadata, downgradebase и повторный upgrade.
- OpenAPI экспортирован с намеренно невалидным DATABASE_URL без соединения; TypeScript сгенерирован openapi-typescript7.13.0. Vitest13/13 PASS, TypeScript typecheck PASS, Vite/PWA production build PASS.
- Независимый smoke повторён после исправлений — PASS: новая отдельная мигрированная тестовая БД, production ASGI/API вход/создание/link/webhook/dedup/unlink/status; реальный subprocess app.workers.main обработал outbox, сохранил задания, восстановился после перезапуска и отменил задания после API cancel. Внешних Telegram-запросов не было; синтетическая БД и subprocess после проверки удалены/остановлены.
- Compose YAML разобран js-yaml; worker ждёт healthy db и успешную migrate, команда python -m app.workers.main. Docker compose config и запуск контейнеров НЕ ПРОВЕРЕНЫ: Docker отсутствует на машине.
- Ruff F/I для новых файлов PASS, форматирование новых файлов выполнено; существующие файлы вне Т06 не форматировались. git diff --check PASS.
- Полный предварительный pytest:1207 PASS,1 FAIL за596.70s. Сбой локального redirect-теста — ConnectionAbortedError WinError10053; это не считается зелёной проверкой. После исправлений выполнен полный прогон окончательного дерева: **1219 PASS за616.07s, exit0**.

## Не закрытая живая приёмка

BLOCKED: пользователь сообщил, что бот ещё не создан. Нет подтверждённых токена/публичного HTTPS/двух телефонов; в текущей main отсутствует карточка Т04. Настоящее сообщение Telegram и переход в авторизованную карточку не проверены. Инструкция и перечень живых действий: docs/T06-telegram.md. До интеграции и этой приёмки Т06 не отмечается DONE.

Повтор внешнего сообщения при неопределённом сетевом исходе возможен; exactly-once и прочтение не заявляются. Уже начатая доставка может завершиться одновременно с отменой/отключением привязки; действия PWA не откатываются. Статусы API показывают подтверждение Telegram, ошибки, блокировку и отмену задания.
