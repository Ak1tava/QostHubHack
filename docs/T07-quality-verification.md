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

- services/api: `.venv/bin/python -m pytest tests/test_ai_quality.py tests/test_ai_quality_eval.py tests/test_ai_review.py tests/test_ai_provider.py tests/test_ai_eval_runner.py tests/test_ai_eval_recovery.py -q -p no:cacheprovider --tb=short`: **83 PASS**.
- `python -m app.export_openapi`, `npm --prefix apps/web run generate:api`, `git diff --exit-code -- packages/contracts`: PASS, публичные файлы не изменились.
- Node 24.19.0: `npm --prefix apps/web run test -- --run`: **54 PASS**; `npm --prefix apps/web run build`: typecheck/production/PWA PASS.
- Полный локальный pytest: **1166 PASS, 330 setup errors, 2 FAIL**. Все 332 ограничения — отсутствующие TEST_DATABASE_URL/MIGRATION_TEST_DATABASE_URL/PostgreSQL; два failure: test_upgrade_rejects_legacy_score_without_reinterpreting_history и test_empty_postgres_migration_roundtrip. Это не полная успешная приёмка; PostgreSQL/worker/PWA проверяются CI.
- Воспроизведения RED→GREEN сохранены для отрицания перерасхода, неизвестных кодов, следа до guard, общего бюджета/резерва, prompt freeze, неизвестного usage, связи доказательств и утечки контрольных фото.

## Живые результаты до контроля

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

CI и единственный новый holdout ожидаются; пользователь разрешил провести holdout
сегодня после технических проверок. T07 не DONE; финальные результаты будут добавлены сюда.
