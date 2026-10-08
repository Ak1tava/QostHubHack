# T13 / T16 — проверка реализации 2026-10-08

Реализация `237f9bd`, [draft PR №12](https://github.com/Ak1tava/QostHubHack/pull/12). Ветка `codex/t13-t16-delivery`, база `origin/main 3af3261`. Владелец A / Codex; независимые backend/frontend/Telegram агенты, общие контракты и интеграция — последовательно. Срок пользователя: **2026-10-08 23:00 Asia/Qyzylorda**. До интеграции T13/T16 имеют статус REVIEW. Main и работающий публичный стенд этой работой не обновляются.

## Результат

- T13: понятные Telegram-уведомления с событием, номером, приоритетом, оборудованием/участком, исполнителем/бригадой, местным сроком; просрочка и последний комментарий только текущего назначения. Прежние binding/outbox/lease/retry/права сохранены. [Описание](T13-implementation.md).
- T16: запись/файл RU/KK в создании наряда и отчёте, редактируемый черновик и явная вставка. Локальный **Whisper large-v3-turbo**, отдельный процесс, авторизация/CSRF, 10 MiB / 60 секунд, временное аудио, понятные ошибки. Автоостановка на 59-й секунде оставляет запас на AAC padding; серверный лимит остаётся строгим. [Установка, модель и ограничения](T16-implementation.md).
- CI использует явно отдельный `compose.speech-test.yaml` с synthetic HTTP ASR и `is_mock=true`. Production-профиль `compose.speech.yaml` использует настоящую локальную модель; её подготовка — отдельная явная команда с фиксированной revision.

## Фактические локальные проверки

Изолированный worktree, Python 3.12.14, Node 24.19.0, PostgreSQL на loopback:55460, production Vite/PWA за настоящим Nginx:5196, API:8015, synthetic ASR:8017. Тестовые БД отделены от рабочего стенда и друг от друга. Секреты/аудио/модель/логи находятся только в ignored `.tooling`/`.env`.

| Проверка / команда | Фактический результат |
| --- | --- |
| `python -m pytest -q -p no:cacheprovider` с отдельными `TEST_DATABASE_URL` и `MIGRATION_TEST_DATABASE_URL` | **1635 PASS**, 356,11 с; весь API и migration roundtrip. Сбор тестов был до добавления двух AAC-регрессий ниже. |
| `python -m pytest tests/test_speech.py tests/test_speech_internal.py -q -p no:cacheprovider` | **48 PASS**, 6,83 с после AAC-регрессий. Настоящие WAV/WebM/Opus/OGG/MP3/MP4-AAC, auth/CSRF, границы, cancellation, local-only model, no-fetch, lock. |
| Telegram/deadlines suite, полная команда в T13-implementation | **80 PASS**, 38,43 с, до общей API-проверки. |
| `node node_modules/vitest/vitest.mjs run` из `apps/web` | **110 PASS**, 19 файлов. |
| `node node_modules/typescript/bin/tsc --noEmit`, затем `--project tsconfig.e2e.json`, `node node_modules/vite/bin/vite.js build` | **PASS**, production PWA и service worker созданы. Прямые команды эквивалентны package scripts; локальный npm wrapper не настроен для вложенного `npm run`. |
| `node node_modules/@playwright/test/cli.js test --workers=2 --retries=0` | **18 существующих сценариев PASS**. Новый speech-тест сначала выявил неверные локаторы самого теста, исправлен и повторён отдельно. |
| `node node_modules/@playwright/test/cli.js test speech.spec.ts --workers=1 --retries=0` | **1 PASS**, 2,5 с: RU создание → настоящий наряд/API/БД → приём/работа → KK отчёт, редактирование/вставка, отсутствие автоматической отправки, silence422. |
| Настоящий `LocalWhisperService`, CPU int8, открытые RU/KK записи | **PASS**: «Добрый день!» / «Қазақстан Республикасы», `is_mock=false`; cold model load 3,000 с, inference 5,968 / 6,018 с. |
| Public FastAPI TestClient с настоящими session/CSRF → реальный HTTP ASR:8018 → настоящая модель | **2 PASS**, 15,78 с: master RU / worker KK, 200/no-store/`is_mock=false`; отдельный ASR остановлен после проверки. |
| Настоящий Nginx → API → synthetic HTTP ASR | **PASS**: WAV **6 720 044 байта / 35 с → 200**, файл >10 MiB → ErrorResponse413; оба no-store. |
| `docker-compose --env-file .env.example -f compose.yaml -f compose.speech[-test].yaml config --quiet` с временными dummy environment | **PASS** для обоих overlay; локальный Docker runtime отсутствует, запуск контейнеров здесь не заявляется. |
| `python -m app.export_openapi`, `npm --prefix apps/web run generate:api`; `git diff --check` | **PASS**, OpenAPI/TypeScript сгенерированы из публичного API. |

Начальные ошибки стенда (путь Chromium, disposable account prefix/PIN, native expiry env, незапущенный no-key review worker) исправлены до повторной браузерной проверки; платные вызовы для этого не нужны. Неудачные прогоны не выдаются за успешные.

## Ревью и оставшаяся приёмка

Независимое итоговое ревью одобрено после двух исправлений: MIME для разрешённых файлов без `File.type` и запас автоостановки для MP4/AAC. Для каждого есть RED → GREEN; явный неподдерживаемый MIME по расширению не переопределяется, реальный контейнер по-прежнему проверяет сервер. Новых существенных замечаний нет.

Живые Telegram-отправки/webhook, платный OpenAI/holdout, production deployment и merge не выполнялись. Физические Safari/Chrome, микрофон/HTTPS/мобильная сеть, шум цеха, производственные термины и длинная речь требуют отдельной приёмки. Короткий настоящий RU/KK smoke подтверждает работоспособность модели, не её производственную точность. GitHub CI выполняет полный Linux/Compose прогон, включая оба worker restart и сохранность приватных фото; актуальный результат — [PR №12 Checks](https://github.com/Ak1tava/QostHubHack/pull/12/checks). Локальный результат выше не подменяет статус CI.

Локальные подробности: `.tooling/t13-t16/{pytest-integration.log,vitest-final.log,e2e-final.log,speech-e2e-agent.log,backend-aac-suite.log,proxy-speech.log,whisper-real-smoke.json,whisper-public-http-smoke.json}`. Эти файлы не публикуются; source/license сведения открытых записей приведены в T16-implementation.
