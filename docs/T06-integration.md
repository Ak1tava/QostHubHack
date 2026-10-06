# Интеграция T06 в main

Дата: 2026-10-06. Владелец интеграции: A / Codex.
База main `16f5f0862670a0e9b39f512e8d9b39721007c3cc`;
исходная ветка Богдана / Codex `feat/T06-telegram`,
коммит `17f59eab8cb926cc543ce0474227618ff28fcd01`.
Рабочая ветка `codex/t06-integration`; обе истории сохраняются.

## Совместимость

- В общем app сохранены auth/catalog/work_orders, realtime и photos T04/T05,
  дополнительно подключён Telegram router. OpenAPI/TypeScript перегенерированы.
- Опубликованная main-миграция 0003 для фото не менялась. Telegram-миграция
  получила revision 0004, down_revision 0003; graph имеет одну голову.
- Worker генерирует HTTPS-кнопку /orders/{id}, совместимую с PWA и обычным
  восстановлением сессии. API нарядов остаётся /api/v1/work-orders.
- Compose запускает настоящий отдельный worker после успешных миграций.
  Его receipts не используют published_at outbox и не мешают будущему T07.
- Актуальные статусы T04/T05 и нерелевантные записи plans.md сохранены;
  T09 не включается в эту интеграцию.

Для БД из первоначальной T06 с её собственной 0003 нельзя вслепую применять
новую цепочку. Опубликованная main-БД 0003 — другая схема. Перенос данных
такой отдельной developer-БД требует резервной копии и отдельного решения;
синтетические проверки выполняются на новой выделенной БД. Данные автоматически
не сбрасываются и revision существующей main не переименовывается.

## Проверки

Локально macOS, Python 3.12.14, Node 24.19.0/npm 12.2.0; lock-файлы сохранены.

- RED перед исправлением: tests/test_t06_integration.py → 2 FAIL:
  две головы Alembic 0003 и неверный /work-orders/{id} в подготовленном сообщении.
- После исправления integration + Telegram HTTP client: 11 PASS. Первый запуск
  client redirect-теста был отклонён sandbox при bind loopback; разрешённый
  повтор выполнил настоящий локальный HTTP redirect-тест без изменения продукта.
- API без PostgreSQL: 1035 PASS, 8 DB-тестов исключены.
- Vitest: 47 PASS; typecheck/build и production PWA PASS.
- OpenAPI экспортирован без БД; TypeScript сгенерирован из объединённых routers.
- Compose/workflow YAML разобраны; git diff --check PASS.

Полные PostgreSQL/миграционные/production-проверки выполняются CI актуального
PR head. Добавлена проверка сохранности уже существующего фото при 0003→0004
и downgrade/upgrade T06. Smoke production API создаёт синтетические наряды,
настоящий worker сохраняет jobs/receipts, отсутствие токена даёт BLOCKED,
контейнер worker перезапускается, задания не дублируются, отмена API приводит
к CANCELLED. Внешних Telegram-запросов в этой проверке нет.

Первый CI [37443746251](https://github.com/Ak1tava/QostHubHack/actions/runs/37443746251)
на `6a48f25` завершился SUCCESS: PostgreSQL 1330, целевые T06 68, Vitest 47,
миграции/контракты/worker restart/dedup/cancel и фото PASS. Однако Playwright
дал 13 PASS + 1 flaky: первый выбор before-фото не создал preview, retry прошёл.
Это не объявляется чистой браузерной приёмкой.

Изолированный headless Chromium с настоящим PhotoUpload и compressPhoto
воспроизвёл механизм: setInputFiles не проверяет disabled, обработчик правильно
игнорирует недоступный ввод; после ожидания enabled preview появился. В E2E
добавлено ожидание готовности input до выбора файла; прежний timeout preview
и проверки результата сохранены. Абсолютная причина единственного CI-сбоя
не выводится только из этого воспроизведения. CI запускает весь Playwright
с --retries=0; повторный отказ блокирует merge, состояние подготовки выводится
в ограниченной синтетической диагностике без токенов/паролей. Код продукта
для этой проверки не менялся.

## Подтверждённая приёмка и интеграция

[CI 37447310167 — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37447310167)
на head `b5e2f1c18120d6060c258aa2049ba20f2b2d01eb`, Ubuntu 24.04:

- Полный PostgreSQL pytest 1330 PASS, 105,38 с; целевые T06 68 PASS, 15,59 с.
- Vitest 47 PASS; typecheck/build, повторная генерация контрактов без дрейфа PASS.
- Production Playwright 14 PASS, 20,4 с, --retries=0; skipped/flaky отсутствуют.
- Graph/migration roundtrip сохраняет существующие фото; metadata drift отсутствует.
- Compose/Nginx/IP isolation, восстановление БД и volumes PASS.
- Настоящий worker: API/outbox → persisted BLOCKED/no-token → restart без дубликатов
  → новый наряд после restart → CANCELLED/receipts после API отмены: PASS.
- Protected-photo capture/recreation/check PASS: anonymous 401, auth 200/no-store,
  UUID/URL/SHA-256/339774 байта/1800×1200 совпали после пересоздания API.

[PR №6 MERGED](https://github.com/Ak1tava/QostHubHack/pull/6), main merge
`81d1c3e4ce845d05ba7d947f949e6f06d3411fa7`; дерево совпадает с проверенным head.
Исходный `17f59ea` и предыдущая main `16f5f08` сохранены в истории.
После merge обновлены только plans.md/readme.md и этот отчёт;
итоговая main проходит отдельный CI. Локально нет PostgreSQL/Docker:
для полной приёмки использована настоящая изолированная среда GitHub Actions.

## Решения и ограничения ревью

Использован существующий T06/C4-план, без перепроектирования функций;
интеграция выполнена в отдельной ветке чистого checkout. CLI-авторизация
по-прежнему отсутствует: применён GitHub connector с проверкой SHA всех
импортированных/изменённых объектов; локальная история shallow. Опубликованная
photo revision 0003 сохранена, цена изменения цепочки для T06-only developer-БД
описана выше. Общие contracts/plans восстановлены из актуальной main,
генерируемые файлы пересозданы. Дополнительная цена реального worker smoke и
no-retry browser gate — время CI; отказ блокирует merge. T09 не интегрирована.

Ревью выполнено отдельным проходом исполнителя; существенных регрессий в
проверенном диапазоне не найдено. Наследованный minor о heartbeat/операционных
метриках worker остаётся отдельным улучшением из docs/T06-review.md:
проверенный restart не заменяет мониторинг остановившегося consumer.

## Границы

Это интеграция серверной реализации T06. Настоящий бот, token/webhook/публичный
HTTPS и переход на двух телефонах не подтверждены. Отдельный UI привязки
Telegram и отображения статусов доставки в PWA пока отсутствует. T06 сохраняет
REVIEW после интеграции кода; живая приёмка BLOCKED, DONE не заявляется.
Сетевые повторы и возможное завершение уже начатой доставки после отмены
сохранены как ограничения исходного решения (docs/T06-telegram.md).

Ревью интеграции проводится отдельным проходом исполнителя; независимое
повторное ревью не заявляется, поскольку AGENTS.md требует явного выбора
подагентов пользователем. Историческая проверка исходной ветки —
docs/T06-verification.md и docs/T06-review.md.
