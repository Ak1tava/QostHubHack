# T17–T19: интеграция и проверка

2026-10-08. Владелец A / Codex; база `main@3ad12a4`, рабочая ветка `codex/t17-t19-integration`. Пользователь поручил T17/T18/T19, исправление состава команды на двух участников и push в main. Статусы — только [plans.md](../plans.md#task-registry).

## Ветки и T19

`git fetch origin --prune` выполнен. Все прежние локальные и удалённые ветки уже интегрированы: ancestry для большинства; для `codex/t08-api`, `codex/t08-web`, `codex/t10-delivery`, `codex/t12-backend`, `codex/t12-frontend`, `codex/t15-candidates` — `git cherry main <branch>` не показывает уникальных патчей. Незакоммиченные generated contracts в трёх старых worktrees T08 API/web и T10 сохранены.

T19 (`9cff43c`) включена в main через `38c4289`; scoped diff реализации пуст. Независимый аудит компонентов, тем, статусов, диалогов и маршрута `/ui-kit` не выявил новых P1/P2. `gh run view 37781852772 --json conclusion,headSha,url` подтвердил `success` для `798081f`: [CI main](https://github.com/Ak1tava/QostHubHack/actions/runs/37781852772). Устаревшие утверждения об отсутствии merge/CI исправлены.

## Фактическая приёмка интеграции

T17: исходные `9cb97e5`/`71998af`, исправления `a2b4c49` (интегрированный `dc61e09`), browser `26c334d`. T18: judge setup `a1b1f22` (интегрированный `f2e9a12`), budget `4f1b6e2` (интегрированный `e9e6bb6`). Два P2 ревью T17 — команды/история мастера и известные ошибки — исправлены с RED→GREEN; повторное и итоговое ревью не оставили P1/P2. Контракты и схема БД не менялись.

| Команда / проверка | Результат |
| --- | --- |
| `python -m pytest -q -p no:cacheprovider --tb=short` в `services/api`, отдельные TEST/MIGRATION URLs | **1731 PASS**, 410.03с |
| `node node_modules/vitest/vitest.mjs run` в `apps/web` | **137 PASS**, 22 файла |
| `node node_modules/typescript/bin/tsc --noEmit`; `tsc --noEmit --project tsconfig.e2e.json` | PASS |
| `node node_modules/vite/bin/vite.js build` | production/PWA PASS |
| `playwright test --workers=2 --retries=0 --grep-invert 'T17 '` | **34 PASS**, 29.5с |
| Сброс только disposable login counters; `playwright test --workers=2 --retries=0 --grep 'T17 '` | **2 PASS**, 3.1с; итого36 без retries/skips |
| `playwright test --list` с теми же фильтрами | 34 и2; обе части полного набора |
| Отдельные judge auth/policy/seed и budget/worker/eval проверки | **97 PASS** и **78 PASS**; включены в полный серверный прогон |
| Browser RU/KK: persistence, typed data, template/report/checklist, voice default/override, известные ошибки и команды/история | PASS; mobile320/390px, шесть скриншотов и визуальная проверка |
| HTTPS readiness; роли; Secure/HttpOnly/SameSite; CSRF/Origin; WSS/foreign Origin; logout/revocation | **19 проверок PASS** через публичный URL |
| Внешний доступ | Пользователь подтвердил открытие экрана входа через мобильную сеть |
| Telegram getMe/setWebhook/getWebhookInfo | PASS; URL нового HTTPS-стенда, pending_updates0; notification consumer работает |
| Синтетический HTTPS create→accept→start→before/after→checklist→submit→OpenAI | `gpt-6.1-sol`, `is_mock=false`, `accepted_with_notes`; наряд остался **AI_REVIEW**, не CLOSED |
| Перезапуск owned API/Nginx/notification/budgeted-AI | PASS; users/orders/events/11 private photos/ledger сохранены |

Дополнительные входы нового browser-набора превысили общий production-лимит30/15мин. CI разделён на две полные фазы с существующим защищённым disposable reset между ними; лимиты приложения не ослаблялись. Начальный фильтр `^T17 ` не учитывал полный Playwright title с именем файла; итоговый фильтр проверен через `--list` и реальным прогоном. Первичные неуспешные прогоны не выданы за PASS.

## Живой режим и бюджет

Во время работы пользователь явно разрешил настоящий ИИ и Telegram с общим потолком **$10**. Команда `budgeted_reviews --live --ordinary-worker-stopped --ledger <прежний ledger> --budget-usd 10 --increase-budget-from 2` выполнила только повышение; исходные calls/usage/расход и `frozen.json` сохранены. Immutable amendment содержит прежние ledger/config. Повторный обычный старт не может молча увеличить бюджет; eval ceiling остаётся$5.

После одного нового вызова в ledger два settled calls, учтено **$0.0272591 из$10**, включая прежние$0.0007711. Это консервативный расчёт по usage, не выписка биллинга: сохранённые ставки сопоставлены с [официальной таблицей OpenAI](https://developers.openai.com/api/docs/pricing), provider использует `service_tier=default`. Повторного holdout и сброса расходов нет.

Стартовали notification worker и ограниченный budgeted-AI worker, окно24часа/10000 stages либо раньше по бюджету/ошибке; обычный платный ai-worker выключен. Новый временный HTTPS-стенд использует отдельную синтетическую БД/участок и случайные пароли судей. Ключи находятся только в серверной ignored-конфигурации; судье передаются адрес и данные входа, не .env/API key. Личный Telegram привязывается из PWA; реальная доставка конкретному получателю требует этой привязки, getMe/webhook не выдаются за такую доставку.

## Ограничения и окружение

Терминологию KK должен проверить человек; T17 сохраняет REVIEW. MOCK-резерв и настоящий ответ на синтетических рисунках не доказывают качество проверки производственных фотографий; решение о закрытии принимает мастер. Замеры≤60с/≤6 действий, обновления≤5с и мобильной загрузки фото≤10с отложены пользователем. ASR на новом живом стенде не настроен; T16 не переоценивается этой проверкой. Quick Tunnel требует включённого компьютера и процессов; постоянный VPS/домен не добавлялись.

PostgreSQL на loopback55486, отдельные TEST/MIGRATION/browser/live databases. Migrations/check/seed PASS. Тестовые API/no-key consumer/fake-ASR отделены от live настроек. Первый pg_ctl в песочнице получил Windows restricted token87; собственный кластер запущен с разрешённым выходом из песочницы. Vite/Playwright также потребовали разрешения на дочерние процессы. Пароли, private photos, сессии, дампы и локальные runtime-скрипты находятся только в ignored .tooling/t17-t19 и не включены в Git.

## Дополнение по пользовательским скриншотам — 2026-10-08

Первая интеграция `main@4db0ab6`: [CI SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37790533204). Последующее исправление: frontend `dfce191`, migration0007 `4477680`, Telegram `542930b`, сгенерированные контракты `4fbd999`.

- Известные серверные сводки, ограничения, причины R/V и пояснения закономерностей переведены на KK; пользовательский/неизвестный/ИИ текст не переводится. Видимые переключатели RU/KZ, внутренний код `kk` сохранён. Регрессия округления Python0.12 против JS0.13 проверена.
- Telegram: `/language`, кнопки RU/KZ, команды `/ru` и `/kz`; язык хранится в binding и используется в пяти типах уведомлений и кнопке наряда. Повторное связывание сохраняет выбор. Private/active/owner/dedup проверяются сервером; исправлена гонка конкурентного переноса binding. Служебный ответ после commit возвращается через webhook sendMessage; API200 не доказывает получение сообщения пользователем.
- Независимый интеграционный `pytest` всех Telegram suites, deadlines и migration roundtrip: **107 passed in 55.86s**. `vitest run`: **143 passed**,22files; tsc app/E2E и Vite/PWA build PASS. OpenAPI/TS сгенерированы, typecheck и diff-check PASS.
- `playwright test --retries=0 --grep 'T17 '`: **2 passed in 3.4s**; locale persistence, поля/черновики/checklist и voice selection. Полный E2E набор повторяется в CI; предыдущий полный набор PASS на main4db0ab6.
- Публичный HTTPS: реальный вход ограниченного demo master, три экрана Reports/Rating/Anomalies, KK persistence и возврат RU, ширина390px без горизонтального переполнения — PASS; три скриншота просмотрены. После обновления API повторно **19 HTTPS/session/CSRF/WSS проверок PASS**.
- Перед migration0007 сохранены приватный PostgreSQL dump, фото и ledger. Перезапущены только API и notification worker; PID AI consumer, Nginx и tunnel сохранены. Фото/ledger побайтово совпали с резервом; потолок $10, учтено $0.0272591. Новый платный вызов не выполнялся. getMe и getWebhookInfo PASS, pending0, ошибок webhook нет.

Независимое ревью двух дополнений и миграции: открытых P1/P2 нет. Команды/проверки отдельных задач: [T17](T17-locale-completion-verification.md), [Telegram](T18-telegram-language-verification.md). Текущие статусы см. plans.md; лингвистическая проверка человеком остаётся.
