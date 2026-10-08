# T19 — дизайн-система НарядAI, этап 0

2026-10-08. Владелец A / Codex. Исходная ветка `codex/t19-design-system`, база `main@3af3261`, code `9cff43c`. T19 включена в main через merge `38c4289` и интеграцию `3ccd2b8`; [CI main `798081f` PASS](https://github.com/Ak1tava/QostHubHack/actions/runs/37781852772). Статус и передача — [plans.md](../plans.md#task-registry). Повторный аудит веток подтвердил ancestry и отсутствие неперенесённых изменений T19; обновление публичного стенда этим не подтверждается.

## Реализовано

- [Токены](../apps/web/src/ui/tokens.css): тёплая светлая и тёмная темы, navy/orange, семантические оттенки, типографика, размеры, движение. Вторичный текст затемнён относительно исходного промта; оранжевые кнопки используют тёмный текст для контраста.
- [Компоненты](../apps/web/src/ui/components.tsx): StatusBadge, PriorityChip, StatusDot, KpiTile, DeadlineBar, BigActionButton, ReasonChips, BottomSheet, Drawer, Toast, EmptyState, Skeleton, OfflineBanner, AiCard. Диалоги удерживают Tab/Shift+Tab, закрываются Escape и возвращают фокус. Есть reduced-motion, состояния disabled/pending/empty/no-data.
- [UI-kit](../apps/web/src/ui/UiKitPage.tsx) на `/ui-kit`: самостоятельная витрина с явно отмеченными демонстрационными данными, без монтирования auth-приложения и запросов API. RU/KZ (код `kk`), сохранение темы/языка, работа при недоступном storage.
- [Словарь статусов](../apps/web/src/ui/status.ts) типизирован текущими API-схемами. Совместимые подписи колонок сохранены. SUBMITTED, AI_REVIEW и CLOSED раздельны; вердикт ИИ не назван человеческой приёмкой; просрочка — дополнительная метка.
- Палитра подключена к существующему приложению через токены; компоненты используются в списке исполнителей, приоритетах доски и вердикте ИИ. PWA theme/background и HTML theme-color согласованы. Сервер, generated contracts, бизнес-store, права и команды не менялись. Изменение маршрутизации ограничено независимой витриной; прежний App остаётся на остальных путях.

## Фактические проверки

Команды из `apps/web`; Node 24.19.0. Использованы уже установленные зависимости основного checkout через локальный junction `node_modules`; package/lock-файлы не менялись. В этой оболочке npm отсутствует в PATH, поэтому CLI запущены непосредственно через Node.

| Проверка | Команда | Результат |
| --- | --- | --- |
| Исходная frontend-регрессия до изменений | `node node_modules/vitest/vitest.mjs run` | 18 файлов, 86 PASS |
| Новые компоненты, App, ReviewPanel | `node node_modules/vitest/vitest.mjs run src/ui/system.test.tsx src/App.test.tsx src/features/work-orders/ReviewPanel.test.tsx` | 9 PASS |
| Полный frontend после изменений | `node node_modules/vitest/vitest.mjs run` | 19 файлов, 90 PASS |
| Типы клиента | `node node_modules/typescript/bin/tsc --noEmit` | PASS, exit 0 |
| Типы browser-тестов | `node node_modules/typescript/bin/tsc --noEmit --project tsconfig.e2e.json` | PASS, exit 0 |
| Production PWA | `node node_modules/vite/bin/vite.js build` | PASS; service worker сгенерирован, 11 precache entries |
| Browser | `node node_modules/@playwright/test/cli.js test ui-kit.spec.ts --workers=2 --retries=0` | 13 PASS, 3.8 s, Chromium, без retries |
| Whitespace | `git diff --check` | PASS |
| Независимое ревью | Аудит diff и повторная проверка focus trap | После исправления aliases замечаний P1/P2 нет |

Для браузера: `PLAYWRIGHT_BROWSERS_PATH=C:/Users/white/Documents/ChatGPT/qoshackhub/.tooling/playwright`, `E2E_BASE_URL=http://127.0.0.1:5175`. Preview: `node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 5175 --strictPort`.

[Browser-тесты](../tests/e2e/ui-kit.spec.ts) проверяют 8 комбинаций RU/KK × light/dark × 390/1440px; отсутствие overflow и API-запросов у витрины; текстовый контраст ≥4.5:1 для статусов/KPI/основных кнопок/переключателей; touch targets ≥56px; storage persistence/отказ storage; reduced-motion; оба диалога и уведомление. Существующие вход, смена и отчёт проверены на 320/390/768/1440px с локальными API-фикстурами, без команд изменения данных.

Выявленные и устранённые дефекты: семантические aliases наследовали светлые значения внутри dark; Tab из последнего контрола native dialog уходил в BODY. Browser-проверка фокуса прошла после исправления. Первичный запуск browser был заблокирован отсутствующим браузером в стандартном каталоге; использован имеющийся Chromium проекта. Замер контраста перенесён на сохранённую тему после reload, чтобы не измерять середину CSS-перехода.

Скриншоты (локальные ignored артефакты): [desktop](../artifacts/t19/ui-kit-desktop.png), [mobile KK dark](../artifacts/t19/ui-kit-mobile-dark.png). Визуально просмотрены desktop RU light и mobile KK dark.

## Границы

Полный перевод рабочих экранов остаётся T17; сейчас переведены новые компоненты/витрина. Казахские термины требуют проверки носителем. Inter/Manrope заданы в font stack, файлы шрифтов не скачивались; при их отсутствии используется системный шрифт, казахские буквы проверены в браузерном образце.

Новые backend-возможности из промтов отложены в разделе T19 плана. UI-kit не является готовой картой оборудования или новым рабочим процессом. Браузерные API-фикстуры проверяют представление данных, не заменяют живой E2E; backend/телефоны/платный ИИ/нагрузка в этой задаче не проверялись.

Следующий этап редизайна: поэкранная адаптация PWA на этих компонентах в рамках существующих `allowed_actions`/`allowed_decisions`. T19 уже интегрирована; отдельное повторное слияние её ветки не нужно.
