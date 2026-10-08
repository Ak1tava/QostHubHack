# T12/T15: проверка реализации

2026-10-08. Владелец A / Codex; база `cd9bc97`, проверенный code [`63bb120`](https://github.com/Ak1tava/QostHubHack/commit/63bb120). Ветка `codex/t12-t15` интегрирована в main fast-forward через `ededbe2`; пользователь разрешил интеграцию и push main после проверок. T12 DONE, T15 REVIEW с перечисленными ниже оставшимися данными.

**[CI main `798081f` — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37781852772):** API1711/Vitest128/E2E34/T15validator8, целевые lifecycle182/T08-T10 70/Telegram68 PASS. Контракты, build, миграции, Compose/Nginx/recovery, новый reset login counters, оба worker/restart и protected-photo persistence после пересоздания API PASS. После этого изменены только Markdown-отметки о проверках.

## Результат

T12: два фиксированных шаблона `visible_leak` и `visible_element`, version 1. При создании сервер сохраняет независимый snapshot. Все три обязательных ответа и по одному фото до/после проверяются до записи отчёта, материалов, событий и receipt. Сохранённые ответы доступны исполнителю и мастеру; неполный шаблонный отчёт не допускается к приёмке. Legacy payload/receipt совместимы; QR и голосовые черновики сохраняются. Миграция0006 добавляет только snapshot/ответы.

T15: [50 кандидатов с конкретными ссылками](../evals/t15/README.md), [описание фотопроверки](T15-photo-pipeline.md), frozen registry split26dev/24eval и offline-валидатор. Проверены50 media endpoints,20 страниц,6 семейств источников. Отдельная проверка прав исключена пользователем; originals в Git отсутствуют. Хеш закрепляет ссылки/метаданные, а не изменяемые удалённые байты.

## Фактические проверки

Чистое окружение без OpenAI/Telegram ключей, отдельный PostgreSQL на loopback55482. API, Nginx, fake-ASR и no-key review worker запускались из production build; API/test/migration базы разделены. Настройки и фотографии синтетических проверок находятся только в ignored `.tooling/t12-t15`.

| Команда | Результат |
| --- | --- |
| `python -m pytest -q -p no:cacheprovider --tb=short` в `services/api` с отдельными TEST/MIGRATION URLs | **1711 PASS**,393.42с |
| `pytest tests/test_ai_review_migrations.py tests/test_migrations.py tests/test_acceptance_throttles.py tests/test_photo_persistence_guard.py -q` | **46 PASS**,5.85с |
| `node node_modules/vitest/vitest.mjs run` в `apps/web` | **128 PASS**,21 файл |
| `node node_modules/typescript/bin/tsc --noEmit`; `tsc -p tsconfig.e2e.json --noEmit` | PASS |
| `node node_modules/vite/bin/vite.js build` | production/PWA build PASS |
| `python -m app.export_openapi`; `openapi-typescript packages/contracts/openapi.json --output packages/contracts/api.generated.ts`; `git diff -- packages/contracts` | PASS, drift отсутствует |
| `alembic upgrade head`; `alembic check`; migration roundtrip/backfill в pytest | PASS; старый snapshot NULL, старые answers[] |
| `node node_modules/@playwright/test/cli.js test --workers=2 --retries=0` | **34 PASS**,29.8с, свежая PostgreSQL, без retries/skips |
| `node evals/t15/validate.mjs` |50 записей,50 media locators,5 категорий, errors=[] |
| `node --test --test-isolation=none evals/t15/test-validator.mjs` | **8 PASS** |
| `git diff --check` | PASS |

Новый E2E проверяет шаблон → серверный422 без изменения версии/отчёта → checklist и before/after → сохранённые ответы исполнителю и мастеру. Полный E2E также включает существующие права, lifecycle, QR/voice, no-key review, отчёты, PWA и адаптивность.

## Исправления по фактическим сбоям и ревью

- Старый migration test вставлял современный ORM default в схему0004. Использована отражённая историческая таблица; проверка запрета ошибочной старой оценки сохранена.
- E2E-селекторы шаблона/описания уточнены по доступной роли; действия ждут серверный ответ и новую историю перед следующей командой. Это устраняет подтверждённый409 из-за ещё не обновлённой UI-версии.
- [Предыдущий CI main](https://github.com/Ak1tava/QostHubHack/actions/runs/37776355036) исчерпал общий login-IP budget между браузерными и worker-проверками. Добавлен отдельный reset только для `CI=true`, loopback, точных demo database names и синтетического login prefix.22 теста, включая реальный PostgreSQL429→reset→вход и сохранение сессий/пользователей. Производственные лимиты неизменны.
- Независимые ревью T12 и CI/migration delta не выявили P1/P2. В T15 исправлено обещание фиксации удалённых фото: закрепляется только реестр.

## Оставшаяся часть T15

T15 остаётся REVIEW: мастерская разметка, настоящие normal/ambiguous контрольные фотографии и полные report inputs не готовы. Часть кандидатов — стадии ремонта, все50 не объявлены независимыми подтверждёнными поломками. Eval не покрывает дробилки/подшипники; пиксельные дубли не проверены. Это подготовка оценки, не минимальный обучающий датасет и не подтверждение производственной точности.

Model IDs/prompt/AI rules не менялись; новых платных calls, повторного used holdout, отправок Telegram и обновления публичного стенда не было.
