# T17 — завершение локализации аналитики и RU/KZ

2026-10-08. Владелец A / Codex frontend. Ветка `codex/t17-locale-completion`, база `4db0ab6`; REVIEW до интеграции основным агентом. Backend, OpenAPI, manifests и plans.md не менялись.

`features/reports/analyticsCopy.ts` содержит отдельные точные переводы системных limitations/reasons и fixed type+title/description из analytics queries/rating/anomalies. Числовой префикс R reason переводится только при полном совпадении авторского шаблона. Unknown copy, имена/специальности, пользовательский текст и текст ИИ сохраняются исходными; общий tx(serverText) не добавлен.

Сводка отчёта переводится только для канонического префикса, совпадающего со всеми DTO counts, и точного суффикса downtime/no-data. Округлённые часы проверяются против DTO seconds в интервале двухзначного округления; исходные цифры сохраняются. Это учитывает разницу Python `:.2f` и JS `toFixed`: 450 секунд даёт серверное 0.12, а JS 0.13. Несогласованные числа или неизвестный формат оставляют исходный summary. Час длительности отображается как `сағ` для kk, RU поведение сохранено.

Главный переключатель теперь RU/KZ, UI-kit уже использует RU/KZ. Значение locale и html lang остаётся `kk`, storage key прежний. Голосовой выбор, поля и черновики не менялись. T17 E2E селекторы кнопки адаптированы с Қазақша на KZ.

## Фактические проверки

- RED: `node node_modules/vitest/vitest.mjs run src/features/reports/Reports.test.tsx src/ui/locale.test.tsx` — 5 FAIL / 29 PASS: RU/KZ label, summary, downtime summary, rating reasons, anomaly copy.
- Дополнительный RED для KK часа — 1 FAIL; RED для Python450→0.12 — 1 FAIL.
- GREEN: `node node_modules/vitest/vitest.mjs run src/features/reports/Reports.test.tsx src/ui/locale.test.tsx src/features/reports/data.test.ts` — 3 файла / 39 PASS, exit 0.
- Финальный `node node_modules/vitest/vitest.mjs run` — **22 файла / 143 PASS**, exit 0; включены voice/draft/input/unknown-data регрессии.
- `node apps/web/node_modules/typescript/bin/tsc --noEmit --project apps/web/tsconfig.json` — PASS, exit 0.
- `node apps/web/node_modules/typescript/bin/tsc --noEmit --project apps/web/tsconfig.e2e.json` — PASS, exit 0.
- `node node_modules/vite/bin/vite.js build` из apps/web — PASS, exit 0; 103 модуля, generateSW, 11 precache entries.
- `git diff --check` — PASS, exit 0.

Независимое узкое ревью (`t17_t18_review`): исходный P2 по округлению подтверждён и исправлен; повторное ревью PASS, новых material P1/P2 нет. Проверка чисел/unknown templates проведена behavioral тестами на реальных компонентах; браузерные E2E после этой правки выполняет основной агент при общей приёмке. Человеческая проверка казахских формулировок остаётся. Платные API/Telegram этим агентом не вызывались.

Зависимости: junction на существующие `.worktrees/t12-t15/apps/web/node_modules`; тесты/build запускаются с разрешением для дочерних процессов.
