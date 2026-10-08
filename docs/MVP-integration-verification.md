# Проверка интеграции T11/T13/T16/T19 — 2026-10-08

Статус: **REVIEW** до CI/оставшейся приёмки. Пользователь разрешил push непосредственно в main; main обновлён fast-forward до интеграции `3ccd2b8`. Владелец: A / Codex. Исходная ветка `codex/mvp-integration`, база `main 3af3261`; объединены T11 `4729ac7`, T13/T16 `577cfbc`, T19 `9cff43c`. Интеграционные коммиты: `9733f16`, `0a86a5b`, `38c4289`; дополнительный тест QR + голос: `9123b6d`.

## Результат интеграции

- QR-карточка и история оборудования, предзаполнение наряда, голосовой черновик RU/KK, формат Telegram и UI-kit находятся в одной ветке.
- Конфликт тестов CreateOrderPage разрешён сохранением обоих сценариев. Общий тест подтверждает, что вставка голоса сохраняет оборудование/участок из QR, а наряд создаётся только после явной отправки.
- Seed создаёт учётные записи для обоих сценариев `t11-qr` и `t16-speech`. Регистрации API, generated contracts и CI сохраняют equipment/speech, проверку workers и приватных фото.
- Plans.md объединён точечно с сохранением статусов исходных задач. Локальные изменения документации сохранены и согласованы при fast-forward main; исходная копия дополнительно остаётся в stash. Публичный стенд не обновлён.

## Проверки

Среда: Windows, существующие Node 24/Python 3.12, отдельный PostgreSQL на loopback:55480. Три новые БД для API, миграций и браузера; API:8020, fake ASR:8021, Nginx:5198. Чистый ignored `.env`, случайные тестовые credentials, assertions отсутствия OpenAI/Telegram keys. Реальные данные и работающий стенд не используются.

| Команда / проверка | Фактический результат |
| --- | --- |
| `python -m app.export_openapi`; `node node_modules/openapi-typescript/bin/cli.js ../../packages/contracts/openapi.json --output ../../packages/contracts/api.generated.ts`; `git diff --exit-code -- packages/contracts` | PASS: повторная генерация не меняет контракт |
| `node node_modules/typescript/bin/tsc --noEmit`; `node node_modules/typescript/bin/tsc --noEmit --project tsconfig.e2e.json` | PASS |
| `node node_modules/vitest/vitest.mjs run` | 120 PASS, 21 файл, 14.97 с |
| `node node_modules/vitest/vitest.mjs run src/features/work-orders/CreateOrderPage.test.tsx` после усиления общего QR + speech сценария | 10 PASS, 1.28 с |
| `node node_modules/vite/bin/vite.js build` | PASS, production PWA / service worker |
| `python -m pytest -q -p no:cacheprovider --basetemp ../../.tooling/mvp-integration/pytest-final` из `services/api` с отдельными `TEST_DATABASE_URL` / `MIGRATION_TEST_DATABASE_URL` | 1654 PASS, 402.96 с; включает migration roundtrip, equipment/speech/Telegram и права |
| `python -m alembic upgrade head`; `python -m alembic check`; `python infra/seed_acceptance.py` | PASS на отдельной demo-БД; `No new upgrade operations detected` |
| `node node_modules/@playwright/test/cli.js test --workers=2 --retries=0` через ignored `e2e.ps1` | 33 PASS, 30.2 с, без retries/skips: реальные API/PostgreSQL/Nginx, fake ASR, no-key review, QR/deep link, speech RU/KK, UI-kit, права и основной цикл |
| Независимое read-only ревью стыков исходных веток | P1/P2 не обнаружены; проверены формы, маршруты/CSS, контракты, dependencies, CI/seed |

Сбой первого frontend-запуска: sandbox запрещал дочерние процессы (`spawn EPERM`); повтор с разрешённым запуском PASS. Первый PostgreSQL cluster получил WIN1252 из Windows locale: fixture с кириллицей упала. Причина воспроизведена (`85 passed, 1 error`), исправлена только кодировка новых disposable БД на UTF8; продуктовый код не менялся.

## Ограничения и передача

Первоначальный approval review отклонил публикацию ветки без явного разрешения. Затем пользователь прямо указал «пушь в мейн сразу»: разрешена отправка интеграции в `https://github.com/Ak1tava/QostHubHack`, ветка `main`, без draft PR. CI нового main ожидается после push; deployment этим поручением не выполняется.

Оплаченный OpenAI, повтор holdout и реальные Telegram-отправки не выполнялись. T12/T15/T17/T18 этим этапом не реализованы. Физические телефоны, мобильные замеры, качество производственной речи, HTTPS QR и Docker runtime требуют отдельной приёмки; предыдущие проверки исходных веток не подменяют общую проверку.

После проверки остановлены только созданные этим этапом процессы; порты 55480/8020/8021/5198 освобождены. Настройки durability PostgreSQL не ослаблялись.

Логи текущего прогона: ignored `.tooling/mvp-integration/`, `apps/web/vitest-integration.log`, `apps/web/vitest-qr-speech.log`, `apps/web/build-integration.log`, `apps/web/playwright-report/`, `apps/web/test-results/`; credentials и сырые браузерные артефакты не публикуются.
