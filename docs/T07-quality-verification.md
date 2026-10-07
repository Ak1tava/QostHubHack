# T07 — стабилизация качества

2026-10-07. A / Codex; codex/t07-quality-mvp от e4dbc5f. Main не менялась.
Реализация исходной T07/T09 унаследована; эта передача относится к доработке качества.

## Изменения

Внутренний enum provider, шесть few-shot примеров, раздельная ответственность
модели/серверных расчётов. Сохранены проверки refs и пригодного after; все ссылки
положительного вывода должны находиться в одном finding. Human review объясняет
недостаток подтверждения. Локальная диагностика включает ответ до guard и причину;
производственные логи эти ответы не записывают. Публичные C5/OpenAPI сохранены.

Новый корпус/бюджет/воспроизведение: ../evals/quality/README.md.
Чужие фотографии и ключи не включены в Git.

## Фактические проверки до CI

- services/api: `.venv/bin/python -m pytest tests/test_ai_quality.py tests/test_ai_quality_eval.py tests/test_ai_review.py tests/test_ai_provider.py tests/test_ai_eval_runner.py tests/test_ai_eval_recovery.py -q -p no:cacheprovider --tb=short`: **85 PASS**.
- `python -m app.export_openapi`, `npm --prefix apps/web run generate:api`, `git diff --exit-code -- packages/contracts`: PASS, публичные файлы не изменились.
- Node 24.19.0: `npm --prefix apps/web run test -- --run`: **54 PASS**; `npm --prefix apps/web run build`: typecheck/production/PWA PASS.
- Первый полный локальный pytest до финальных регрессий: **1166 PASS, 330 setup errors, 2 FAIL**. Все 332 ограничения — отсутствующие TEST_DATABASE_URL/MIGRATION_TEST_DATABASE_URL/PostgreSQL; два failure: test_upgrade_rejects_legacy_score_without_reinterpreting_history и test_empty_postgres_migration_roundtrip. Это не полная успешная приёмка; PostgreSQL/worker/PWA проверяются CI.
- Воспроизведения RED→GREEN сохранены для отрицания перерасхода, неизвестных кодов, следа до guard, общего бюджета/резерва, prompt freeze, неизвестного usage, связи доказательств и утечки контрольных фото.

## Живые результаты до контроля

Первый промпт t07-v2 использовал условные id; второй t07-v3 уточняет выбор
настоящих photo:<UUID> по phase. Лимит двух версий соблюдается. Результаты
v3: **4/4 good положительных**, **0/2 bad принятых**, **2/2 ambiguous human_review**.
Семь новых вызовов Sol, второй и последний промпт; после этого настройки заморожены.

Sol: good **3/4** положительных, bad **0/2** принятых, ambiguous **2/2** human_review.
Семь платных вызовов; $0.1847010 по консервативным тарифам. Один good передан мастеру
как photo_subject_mismatch; guard не ослаблен ради принятия этого примера.

Astra на тех же двух good: первый API error с неизвестным usage, второй accepted.
Сравнение не показывает преимущество Astra, основной остаётся Sol. Подтверждённый
расход всех успешных dev/comparison вызовов $0.3325685; отдельный неизвестный резерв
$2.9877375, всего учтено **$3.3203060 из $8**. Резерв не обнулялся.

Первое сравнение остановилось до отправки из-за чрезмерного byte-based резерва.
В новом фотопрогоне резерв уточнён по документированной токенизации Astra; старый
T09 ledger и его алгоритм резервирования не менялись. Повтор первого API error не выполнялся.

## Финальная техническая приёмка

[CI 37601848738 — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37601848738),
код **229375cdbff86458f9eca900c6c3c38b13369075**: полный PostgreSQL pytest **1505 PASS**
(251.97s), целевые жизненный цикл/права/фото **182 PASS**, Telegram **68 PASS**, Vitest
**54 PASS**, production Playwright **15 PASS** без retries (30.9s). Контракты,
typecheck/build, миграции, Compose/Nginx/IP/recovery и сохранность фото — PASS.
Настоящие API/AI worker: blocked без ключа, restart/redelivery/dedup/cancel — PASS;
PWA прошла сценарий ручной приёмки с конфликтом версии и потерянным ответом.
В CI платных модельных запросов нет; новые настоящие модельные запросы проведены
отдельно этим eval-runner, а не через production worker. Живой сквозной прогон
оплаченной модели через worker/PWA на физических телефонах остаётся приёмкой T10.

Финальное ревью — отдельный самостоятельный проход; подагенты не запускались
по AGENTS.md. Последняя локальная целевая проверка — **85 PASS**; Ruff F/I и
`git diff --check` PASS. После проверенного кода финальный коммит добавляет отчёт,
Markdown и сортирует только импорты тестов; application code не меняется.

## Единственный новый holdout — LIVE

Пользователь разрешил выполнить контроль 2026-10-07 после CI. Команда из services/api:
`.venv/bin/python -m app.modules.ai_review.quality_eval --live --split holdout`, exit 0.
Перед этим `--freeze`, exit 0. Конфигурация/медиа/промпт **t07-v3** зафиксированы,
marker сохранён. Старый T09 holdout не запускался.

- good: **4/4** положительных;
- bad: **0/4** принятых: один requires_rework от модели, два от правил комплектности,
  один human_review после API error; не выдаём этот сбой за успешное распознавание;
- ambiguous: **4/4 human_review**, score=null;
- неверных итоговых refs **0**, автоматических CLOSED **0**;
- критерий демонабора **PASS**. Совпадение всех вердиктов с метками 11/12; одна
  разница связана с API error. Это не измерение производственной точности.

Полный обезличенный сводный результат: [T07-quality-2026-10-07.json](../evals/reports/T07-quality-2026-10-07.json).
Raw структурированные ответы и причины каждого guard остаются в ignored .tooling.
Всего в новом корпусе 2 контрольных ремонтных проекта; варианты снимков коррелируют.

Расход успешных вызовов по консервативным usage-тарифам **$0.7473730**; неизвестный
usage двух API errors удерживает резерв **$3.5194500**. В едином журнале учтено
**$4.2668230 из дополнительных $8**. Ни резерв, ни предыдущие расходы не обнулялись.
Это оценка по usage/резерву, не выписка биллинга. Новых вызовов после контроля нет.

T07 — **REVIEW**, [draft PR №8](https://github.com/Ak1tava/QostHubHack/pull/8).
Main не изменялась; интеграция и живая приёмка полного продукта остаются отдельно.

## Интеграция в main — 2026-10-07

[PR №8 MERGED](https://github.com/Ak1tava/QostHubHack/pull/8), merge `2a83c4ef7e9a42c6c8577c3cfd45c698854e0a05`.
[CI последнего head a832552 — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37608069734); application code сохранён.
Команды: `git fetch`, `git merge --ff-only origin/main`, проверка включения `a832552`
и равенства дерева merge/head — PASS. История T09/T07 сохранена merge-методом.
T09 DONE, T07 REVIEW до оставшейся живой приёмки. Бюджет/freeze/holdout marker
и приватные медиа скопированы в ignored .tooling/t07-quality основного checkout,
чтобы переход в main не сбрасывал расходы или запрет повторного контроля.
Итоговая main проходит свой CI; новых модельных запросов не выполнялось.
