# T05 — фактическая проверка

Дата: 2026-10-04. Владелец: A + B / Codex. Ветка: `codex/t05-execution-evidence`, база — запушенная T04 `f74c42a`. Статус REVIEW, head — `git log -1 --format=%H` в этой ветке. В main T04/T05 ещё не интегрированы; DONE не заявляется.

Код: [отчёты](../services/api/app/modules/work_orders/submissions.py), [фото](../services/api/app/modules/photos/service.py), [private storage](../services/api/app/modules/photos/storage.py), [миграция 0003](../services/api/migrations/versions/0003_photo_evidence.py), [экран исполнителя](../apps/web/src/features/work-orders/ExecutionPage.tsx), [очередь](../apps/web/src/features/work-orders/MyOrdersPage.tsx), [форма](../apps/web/src/features/work-orders/SubmissionForm.tsx).

## Выполненные проверки

Команды API выполнялись из `services/api`, npm — из корня worktree. Локальные Windows sandbox ограничения временных файлов и дочерних процессов потребовали разрешённого выполнения проверок за пределами sandbox; права продукта не ослаблялись.

| Проверка | Команда | Фактический результат |
| --- | --- | --- |
| Приёмка T05 после финального исправления ошибок API | `uv run --locked --offline pytest tests/test_submissions.py tests/test_photos.py tests/test_authz.py tests/test_app_integration.py -q -p no:cacheprovider --basetemp=../../.tooling/pytest-final --tb=short` | **126 PASS**, 83,35 с |
| Полный серверный прогон с миграциями/T03/T04 | `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp=../../.tooling/pytest-full --tb=short` | **1244 PASS**, 164,04 с; до добавления одного regression-теста UUID фото |
| Обработчик 422 после замечания ревью | `.venv/Scripts/python.exe -m pytest tests/test_app_integration.py tests/test_export_openapi.py -q -p no:cacheprovider --tb=short` | **6 PASS**, 2,86 с; добавленный UUID-тест включён и в финальные 126 |
| Миграция 0003: upgrade/head, metadata drift и downgrade/upgrade | `.venv/Scripts/python.exe -m pytest tests/test_photos.py tests/test_migrations.py -q -p no:cacheprovider --basetemp=<isolated-temp> --tb=short` | **37 PASS**, 26,35 с, независимая БД подагента |
| Vitest, включая регрессии T04 и preview после загрузки | `npm --prefix apps/web run test -- --run` | **47 PASS**, 13 файлов, 1,75 с |
| Целевой браузерный сценарий T05 на production PWA | `npm --prefix apps/web run test:e2e -- execution.spec.ts --workers=1 --retries=0 --reporter=list` | **1 PASS**, 3,1 с |
| Полный production Playwright: вход/PWA/T04/T05 | `npm --prefix apps/web run test:e2e -- --workers=1 --retries=0 --reporter=list,json` | **14 PASS**, 24,70 с; 0 skipped/flaky |
| TypeScript приложения/E2E и production PWA | `npm --prefix apps/web run build` | **PASS**, JS gzip 96,81 КБ; service worker создан |
| Дрейф API-контрактов | `.venv/Scripts/python.exe -m app.export_openapi`, затем `npm --prefix apps/web run generate:api` | **PASS**, SHA-256 обоих generated файлов до/после совпадает |
| Реальное фото после перезапуска native API | Из корня: `services/api/.venv/Scripts/python.exe infra/verify_photo_persistence.py capture --state .tooling/photo-persistence-t05.json`; перезапуск только API; та же команда с `check` | **PASS**, auth GET 200 / anonymous 401, SHA-256 совпал |
| Воспроизводимость Python-зависимостей | `uv sync --locked --offline` | **PASS**, 41 resolved / 39 installed checked |
| Fresh-context ревью | Независимый обзор всего изменения и последнего UI delta | Существенных P1/P2 замечаний нет; несогласованный 422 фото исправлен и проверен |
| Проверка diff | `git -c core.safecrlf=false diff --check` | **PASS** |

Полный прогон и финальная приёмка используют `TEST_DATABASE_URL=postgresql+psycopg://qosthub@127.0.0.1:55405/qosthub_test_t05`, `MIGRATION_TEST_DATABASE_URL=postgresql+psycopg://qosthub@127.0.0.1:55405/qosthub_migration_test_t05`. Подагент фото использовал отдельные `qosthub_test_t05_photos` / `qosthub_migration_test_t05_photos`, чтобы concurrent fixtures не удаляли таблицы друг друга. Миграции production-проверки применены к отдельной `qosthub_demo_t05`.

Среда: Windows, Python 3.12.14, Node 24.19.0, PostgreSQL 17.11, Pillow 12.3.0. `uv` запускался установленным в корневой `.tooling/uv/bin/uv.exe`; `npm` — через `node <repo-root>/.tooling/npm/package/bin/npm-cli.js`. Эти runtime-каталоги, пароли/сессии и диагностические артефакты не входят в коммит.

Проверены сохранение работ/шифра/материалов и decimal(14,4), явное отсутствие материалов, отрицательные/нулевые/нечисловые количества, повтор и конкурентная отправка, конфликт ключа/версии/назначения, atomic rollback при отказе события, неизменность старой revision/фото, чужой наряд/автор/тип фото, неполный emergency-отчёт, MIME spoofing, декодирование/лимиты/EXIF/хеши, session/CSRF/brigade access, ожидание загрузки на блокировке наряда. Клиентские проверки закрепляют сохранение ввода при ошибке/live refresh, прежний body/key при retry, причины действий, пагинацию очереди, server timezone и сохранённые защищённые изображения.

RED/GREEN подтверждён фактически: отсутствующий submission endpoint вернул 404 вместо 201; HTTP фото также 404; компенсация storage при коллизии удаляла существующий файл; после успешного upload preview обращался к null.size; GET фото с неверным UUID возвращал стандартный detail вместо ErrorResponse. Для каждого поведения добавлена проверка, исправление прошло GREEN.

Playwright работает с production dist, native Uvicorn (`127.0.0.1:8005`), PostgreSQL `qosthub_demo_t05` и Vite preview/proxy `http://localhost:5175`. `CI=true`, `E2E_BASE_URL=http://localhost:5175`; синтетические E2E аккаунты создаёт `infra/seed_acceptance.py`. Для проверки истечения сессии задаются `E2E_DATABASE_URL` и абсолютный `E2E_PYTHON_PATH` native API. Браузерные артефакты не входят в коммит.

Целевой сценарий проверяет UI выдачи → очередь/принятие/старт/пауза/продолжение; before/after, canvas JPEG ≤500 КиБ и защищённое чтение; расход 1,25; commit 201 с потерянным ответом, HTTP retry с неизменными body/key после live SUBMITTED; чтение сохранённого отчёта и прямую ссылку. Горизонтального overflow при мобильной эмуляции нет. Это эмуляция браузера, без физического телефона и мобильной сети.

Диагностические повторы исчерпали штатные login throttles; лимитер сброшен только в выделенной синтетической `qosthub_demo_t05` после проверки current_database. Лимиты продукта не менялись. Незавершённые тестовые наряды отменены через авторизованный API мастера; E2E cleanup теперь передаёт Origin для CSRF.

Первый полный Playwright-прогон: 13 PASS / 1 FAIL — guard теста истечения сессии разрешал только demo/dedicated T04, исключая новую isolated T05 БД. В список явно добавлена `qosthub_demo_t05`; ограничения loopback, synthetic login и production DB не ослаблены. Повторный полный прогон дал 14 PASS без retries.

Проверка native persistence использовала реально загруженный JPEG **339 774 байта, 1800×1200**, private каталог `.tooling/acceptance-photos`. SHA-256 `ae2cbc5f606ad3f2f862ee9e2cb8cb646ff8773bf2a3d72ef1b64f741993218b` до/после совпал; `Cache-Control: no-store`, декодирование Pillow прошло. Защищённый loopback GET занял 2066/2075 мс — это чтение на локальной машине, не замер мобильной загрузки. API остановлен Windows `Stop-Process` после проверки собственных PID/path и запущен заново; PostgreSQL/web не перезапускались. Контейнерный volume persistence этим не подтверждается.

## Ограничения приёмки

- Замеры на физических телефонах и мобильной сети **НЕ ВЫПОЛНЕНЫ**. Проверить фото 300–500 КБ, визуальное качество после сжатия и загрузку ≤10 секунд с указанием устройства, сети, размера/пикселей. Локальный loopback и эмуляция не подтверждают эту метрику.
- Docker отсутствует: контейнерный Compose и volume persistence этой ветки **НЕ ВЫПОЛНЕНЫ**. CI дополнен целевыми T05 тестами; до push CI этой ветки не заявляется прошедшим.
- Транзакция компенсирует обычные ошибки БД/файловой записи. Аварийное завершение процесса между записью файла и commit может оставить приватный файл без строки БД; автоматическая уборка таких файлов в T05 не реализована.
- Draft и pending retry сохраняются при live refresh/reconnect в открытой странице. После F5 или закрытия вкладки незавершённый локальный ввод не восстанавливается.
- ИИ-проверка/возврат и приёмка мастером — T07; T05 сохраняет SUBMITTED и missing_evidence, используя ограничения закрытия T03.

Интеграция: сначала T04, затем T05; переносить только T05 delta и его строку/передачу в актуальный `plans.md`, сохраняя чужие статусы. До интеграции и проверки main статус REVIEW.
