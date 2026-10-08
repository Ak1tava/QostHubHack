# T18 — проверка локальной реализации

Владелец A / Codex backend agent; ветка `codex/t18-judge-access`, base `3ad12a4`. Объём: `app.judge_demo`, отдельные поведенческие тесты и инструкция судье. Статус до интеграции — REVIEW; `plans.md` обновляет основной агент.

Решение: использовать пять синтетических сценариев T09 с отдельными UUID, участком, бригадой и парой аккаунтов, вместо выдачи судьям T09 аккаунтов с доступом ко всем демоучасткам. Локальный `SyntheticJudgeProvider` всегда возвращает MOCK / `human_review`, без оценки ремонта и сетевых вызовов; сохраняется `usage.is_mock=true`, поэтому существующий ReviewPanel показывает явную метку. Общие контракты и production worker не менялись.

TDD: первоначальный `pytest tests/test_judge_demo.py -q -k unsafe_target` → 4 FAIL: `app.judge_demo` отсутствовал. Отдельный RED для публичной метки и provider: `-k 'test_provider or server_access'` → 3 FAIL (`is_mock=False`, provider отсутствовал); после реализации → 10 PASS. Проверки выполнялись в disposable PostgreSQL на loopback55487, вне живого стенда, без OpenAI/Telegram ключей.

Финальная команда (из `services/api`, переиспользованный Python venv, изолированный `TEST_DATABASE_URL`): `python -m pytest -p no:cacheprovider tests/test_judge_demo.py tests/test_authz.py tests/test_seed_demo.py tests/test_review_policy.py -q --tb=short` → **97 passed in 87.38s**, exit0. Отдельный T18 прогон → **11 passed in 10.77s**. Проверены реальные серверные права master/worker, чужой UUID, scoped users/areas, rotation/revocation сессии, CSRF, MOCK/evidence, запрет worker приёмки, явное решение мастера и сохранение истории при повторе setup. `git diff --check` → exit0.

Живой URL/HTTPS/WSS/внешняя сеть/ready/restart проверяются основным агентом на изолированном стенде; здесь эти результаты не заявлены. Платных вызовов, изменений производственных данных и сброса ledger не было. [Код](../services/api/app/judge_demo.py), [поведенческие проверки](../services/api/tests/test_judge_demo.py), [инструкция](T18-judge-guide.md). Judge setup commit: `a1b1f22`.

Ограничение: свежие отчёты судей не получают предустановленный MOCK автоматически. Без consumer они ожидают; стандартный no-key worker даёт честный `human_review` о недоступном provider. Готовый объяснимый MOCK в №04 служит независимым резервным примером.

## Разрешённое повышение live бюджета до $10

Пользователь отдельно разрешил OpenAI/Telegram и общий лимит $10. `budgeted_reviews` получил scoped live ceiling $10; generic `BudgetLedger` для eval остаётся ≤$5. Обычный restart не меняет сохранённый лимит. Новая команда `--increase-budget-from 2 --budget-usd 10` только фиксирует повышение, не конструирует OpenAI provider и не требует ключа.

До изменения ledger берутся файловый и advisory DB locks, проверяются старый лимит, полностью settled calls, отсутствие provider errors/halt, расход и прежний frozen config. Неизменяемый `*.budget-amendment.json` сохраняет полный прежний ledger/config; атомарно изменяется только `limit_usd`. Calls, usage, reserved/charged суммы и расходы не сбрасываются. `frozen.json` остаётся байт-в-байт прежним. Частичная запись между amendment и ledger блокирует restart до аудита; повышение не восстанавливает неизвестные расходы и не снимает halt.

TDD RED: `pytest tests/test_budgeted_worker.py -q -k 'amendment or live_cap10'` → **8 FAIL**: cap2 и отсутствующие amendment функции. GREEN всей budget suite → **23 passed in 7.13s**. Финальная команда: `python -m pytest -p no:cacheprovider tests/test_budgeted_worker.py tests/test_review_worker.py tests/test_ai_eval_runner.py tests/test_ai_eval_recovery.py -q --tb=short` → **78 passed in 33.36s**, exit0. Включена CLI-проверка amendment-only без ключа/provider calls, реальные DB/file lock коллизии, исторические calls/config, crash recovery и сохранение generic eval ceiling. `git diff --check` → exit0.

Производственный ledger не изменялся этим агентом; его фактическое повышение и live probe выполняет основной агент после интеграции. [Изменение бюджета](../services/api/app/workers/budgeted_reviews.py), [проверки](../services/api/tests/test_budgeted_worker.py).

## Фактический живой режим после интеграции

[Итоговая проверка T17–T19](T17-T19-verification.md): HTTPS/WSS/session/CSRF и внешний доступ PASS, подлинный gpt-6.1-sol ответ сохранён, Telegram webhook/consumer включены. Старый ledger повышен2→10 явной reviewed-командой без сброса; два settled calls,$0.0272591 учтено. Перезапуск сохранил данные/11 фото/ledger. Полный PostgreSQL1731/Vitest137/E2E36 PASS. Получателю нужно привязать свой Telegram в PWA; фактическая доставка ему до этого не заявляется.
