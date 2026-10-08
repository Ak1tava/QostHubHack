# T17 — языки интерфейса

Владелец: A / Codex frontend; ветка `codex/t17-ui-language`, база `3ad12a4`.
Локальный статус REVIEW; реестр и интеграцию обновляет основной агент.

Реализован общий LocaleProvider на инфраструктуре T19: русский по умолчанию, видимый RU/Қазақша, сохранение `naryadai.locale` после render, защита от отказа storage, html lang. UI-kit использует тот же контекст; отдельная theme preference сохранена.

Основные экраны, навигация, выдача/исполнение/отчёт/решение мастера, отчёты/аналитика, оборудование/Telegram, статусы, пустые состояния и известные API errors локализованы явными UI call sites. Неизвестные ошибки и details, имена/описания/документы, объяснения и ограничения ИИ/аналитики сохраняются буквально. Фиксированные шаблоны переводятся только по известному id/version=1 и checklist ids; initial_description не изменяется. Язык речи наследует UI до ручного выбора; переключение UI не сбрасывает поля или черновики.

## Фактические проверки (2026-10-08)

- RED: `node node_modules/vitest/vitest.mjs run src/ui/locale.test.tsx` — ошибка отсутствующего `./locale`, до реализации.
- `node node_modules/vitest/vitest.mjs run` — 22 файла, **133/133 PASS**, exit 0. Пять новых тестов: RU default, persistence/input retention/remount, denied/invalid storage, voice override, known/unknown errors и ограничение template translation.
- `node apps/web/node_modules/typescript/bin/tsc --noEmit --project apps/web/tsconfig.json` — PASS, exit 0.
- `node apps/web/node_modules/typescript/bin/tsc --noEmit --project apps/web/tsconfig.e2e.json` — PASS, exit 0.
- `node node_modules/vite/bin/vite.js build` из apps/web — PASS, exit 0; 101 модуля, generateSW, 11 precache entries.
- `git diff --check HEAD^ HEAD` после коммита `9cb97e5` — PASS, exit 0.

Vitest/build запускались с разрешением для дочерних процессов: sandbox давал spawn EPERM. Зависимости используются через junction на существующие `.worktrees/t12-t15/apps/web/node_modules`; manifests/lock/контракты не менялись. Исходные root deps не содержали qrcode, поэтому первая typecheck завершилась TS2307 до подключения полного каталога.

Первый `git -c core.autocrlf=false diff --check` вернул exit 1: изменение настройки нормализации включило все исходные CRLF файлами в diff и пометило CR как whitespace. Проверка нормализованного коммита штатным `git diff --check HEAD^ HEAD` проходит.

После полной Vitest/build проверки изменена только подпись заголовка колонки (тот же tx, что select/aria-label) и убраны пустые строки; typecheck/diff check повторены. Браузерные T17 E2E, mobile long KK labels, визуальное ревью и общий production acceptance выполняет основной агент после интеграции; здесь не заявляются PASS. Казахская терминология требует человеческого ревью. Платные API и Telegram не вызывались этим агентом.

Код: `apps/web/src/ui/locale.tsx`, `appMessages.ts`, `locale.test.tsx`, подключённые экраны и `design.css`.

## Исправления независимого ревью — round 1

Два P2 из `t17-t18-task-review.md` подтверждены четырьмя новыми behavioral тестами. Команды/выбранное действие/история мастера используют переводы известных карт; неизвестное событие сохраняется буквально. Telegram helper возвращает только authored сообщения, перевод происходит при render. Фото/период/срок выбрасывают локальный `UiError` с фиксированным ID; неизвестные Error/ApiError сохраняют сообщение даже при совпадении с текстом известной ошибки. Состояние фото/выдачи хранит Error, поэтому уже показанные ошибки меняют язык без сброса полей.

- RED: `node node_modules/vitest/vitest.mjs run src/ui/locale.test.tsx` — 4 FAIL / 5 PASS (9 tests); фактические падения map/history, Telegram, compressPhoto и period validation.
- GREEN: `node node_modules/vitest/vitest.mjs run src/ui/locale.test.tsx src/features/work-orders/OrderDetailsPage.test.tsx src/features/work-orders/CreateOrderPage.test.tsx src/features/work-orders/PhotoUpload.test.tsx src/features/telegram/TelegramPage.test.tsx src/features/reports/Reports.test.tsx src/features/reports/data.test.ts src/lib/compressPhoto.test.ts src/lib/time.test.ts` — **9 файлов / 56 PASS**, exit 0; locale содержит 9 tests.
- `node apps/web/node_modules/typescript/bin/tsc --noEmit --project apps/web/tsconfig.json` — PASS, exit 0.
- `node apps/web/node_modules/typescript/bin/tsc --noEmit --project apps/web/tsconfig.e2e.json` — PASS, exit 0.
- `git diff --check` — PASS, exit 0.

Полный suite/build/browser после round 1 повторяет основной агент в общей интеграционной ветке. E2E не редактировались этим агентом.
