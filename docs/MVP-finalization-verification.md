# Завершение MVP — фактические проверки

Дата начала: 2026-10-08, Asia/Qyzylorda. Владелец: A / Codex, `codex/mvp-finalization`, база `ad034bf`. Статус: IN_PROGRESS. План: [утверждённый объём](superpowers/plans/2026-10-08-mvp-finalization.md).

## Исходное состояние

- Рабочая копия main чистая; `ad034bf` отличается от проверенного `a2cdb16` только документацией.
- GitHub job `113372506662`, run `37795136435`: 1759 API, 143 Vitest, 34+2 E2E, contracts/types/build и production Compose acceptance PASS (подтверждено чтением фактического лога при предварительном аудите).
- Текущий native API `/health/ready` и публичный HTTPS `/health/ready`, `/` ответили200 при предварительном аудите; это не приёмка новых изменений.

## Среда новой проверки

- Четыре изолированных worktree: интеграция, RU-ASR, демонстрационные сценарии, native runtime.
- Отдельные PostgreSQL базы qosthub_test_mvp_final_speech/demo/api, qosthub_test_t14_mvp_final_browser и qosthub_migration_test_mvp_final; живые таблицы не используются destructive fixtures.
- `npm ci --no-audit --no-fund` по lock в интеграционном apps/web: PASS, 461 пакетов; старый неполный node_modules не переносился.

## Результаты реализации

| Проверка | Команда / фактический результат |
| --- | --- |
| Полный API, PostgreSQL | `python -m pytest -q -p no:cacheprovider --tb=short` из services/api: **1792 passed**, 428,99с. База реализации e52e9ed; последующие fixes проверены отдельно ниже |
| Web | `vitest run`: **148 passed**, 22 файла |
| Типы / PWA | `tsc --noEmit`, `tsc --noEmit --project tsconfig.e2e.json`, `vite build`: PASS, production PWA/sw создан |
| Контракты | `python -m app.export_openapi`, `npm run generate:api`, `git diff -- packages/contracts`: PASS, повтор без diff |
| Browser/API/БД | Playwright `--workers=2 --retries=0 --grep-invert 'T17 '`: **34 passed**, 27,1с; отдельный `--grep 'T17 '`: **2 passed**, 3,2с |
| Миграции | `alembic upgrade head`, `alembic check` на отдельной browser БД: PASS; новые миграции не требуются |
| Исправления seed/runtime | `pytest tests/test_judge_demo.py tests/test_native_runtime.py tests/test_tunnel_config.py tests/test_budgeted_worker.py -q`: **79 passed**, 25,87с; включая реальный PostgreSQL для budget guards |
| Презентация | 8 слайдов: import/edit/export и finalizer PASS; слайды3/4/8 визуально проверены, тема/макеты/шрифты сохранены |
| Казахские тексты | Отдельный агент-редактор: исправлены статусы доработки, подпись фото мастера, метка prepared-результата и русский ASR. Проверка человеком не выполнялась |

В первом browser-прогоне было 33PASS/1FAIL: защитный allowlist сценария истечения сессии не допускал выбранное имя тестовой БД. Изолированная БД переименована в разрешённый `qosthub_test_t14_*`, код/защита теста не ослаблялись; повтор34PASS. Для локальных фаз счётчики входа сброшены только в этой конкретной тестовой БД; живые throttles не менялись.

Независимое ревью: RU-ASR и prepared-provider без P1/P2. На runtime/интеграции найдены и исправлены импорт Docker worker, подтверждение готовности после locks/frozen, восстановление managed tunnel со сменой Host и Telegram seed-events. Для последнего получен RED (12 необработанных событий вместо0), затем GREEN; обычное событие реального restart продолжает создавать уведомления. Абсолютный expiry не добавлялся: утверждённый план и сохранённая конфигурация задают денежный потолок, `max-seconds` относится к одному процессу.

Настоящий Windows venv redirector подтвердил разные PID запускающего процесса и интерпретатора. Исправление `24c91e2` отслеживает проверенный direct child и wrapper отдельно, сохраняет проверку readiness token/PID и безопасную остановку обеих identities. Реальный скрытый subprocess start→ready→stop прошёл; узкое независимое ревью одобрено.

Финальный повтор той же целевой команды judge/native/tunnel/budget на `24c91e2`: **91 passed**, 26,18с, включая PostgreSQL и Windows-процессы. Новые live ASR/AI, restart стенда, isolated restore, запись, main и CI ещё не объявлены пройденными.

## CI и живая приёмка

- `af539f4` интегрирован в main. [CI37808776024 SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37808776024): все этапы, включая production Compose, browser и worker/photo recovery. Предыдущий run37806903190 прошёл API1819/Vitest148, но остановился на обязательной переменной `LIVE_AI_LEDGER_DIR` в syntax-only Compose validation; исправлен только параметр этой проверки, создание нового ledger не разрешалось.
- На текущем HTTPS запущен закреплённый native release: ASR/API/Nginx/notifications/budgeted reviews ready, прежние PostgreSQL и Quick Tunnel сохранены. Веса Whisper повторно проверены по SHA256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`.
- Русский ASR через HTTPS: **«Добрый день!»**, `is_mock=false`, `large-v3-turbo`, 8,765с на коротком контрольном аудио; `kk` →422 `speech_invalid_language`. Это не измерение производственной точности. Проверку своим голосом пользователь оставил себе; она не блокирует программный выпуск.
- Prepared-v2 setup → `created`, повтор → `unchanged`; через HTTPS подтверждены три вердикта, `is_mock=true`, Secure cookie и шесть разных доступных приватных фотографий.
- Первая фактическая копия:30 таблиц,11 файлов фото,3 файла budget/audit; восстановлены в новую БД/каталоги, SQL counts и SHA256 совпали, расходы остались $0.0272591/10, два settled calls. Ключи и external consumers в восстановленной среде отключены.
- При проверке восстановленного API обнаружен прежний дефект legacy-v1: nested storage keys не проходили защиту UUID-файлов. Исправление `1704df9` меняет только подготовку/явный повтор legacy setup: оригиналы, пароли, действия и пользовательские загрузки сохраняются; UUID path guard не расширяется. **98 targeted tests PASS**, 67,63с, включая настоящий Windows junction; независимое ревью одобрено. Обновление live и итоговая проверка исправленного восстановления ещё ожидаются.

## Границы приёмки

Физические телефоны и численные мобильные замеры отложены пользователем. Дообучение, новый размеченный benchmark и VPS исключены из текущего этапа. Подготовленные ИИ-результаты имеют явную метку и не доказывают производственную точность. Сбор50 сохраняется как заготовка без заявления о завершённой разметке. Платные вызовы допускаются только в прежнем совокупном бюджете $10 с сохранением ledger.
