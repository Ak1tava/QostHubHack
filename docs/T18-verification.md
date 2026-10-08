# T18 — проверка локальной реализации

Владелец A / Codex backend agent; ветка `codex/t18-judge-access`, base `3ad12a4`. Объём: `app.judge_demo`, отдельные поведенческие тесты и инструкция судье. Статус до интеграции — REVIEW; `plans.md` обновляет основной агент.

Решение: использовать пять синтетических сценариев T09 с отдельными UUID, участком, бригадой и парой аккаунтов, вместо выдачи судьям T09 аккаунтов с доступом ко всем демоучасткам. Локальный `SyntheticJudgeProvider` всегда возвращает MOCK / `human_review`, без оценки ремонта и сетевых вызовов; сохраняется `usage.is_mock=true`, поэтому существующий ReviewPanel показывает явную метку. Общие контракты и production worker не менялись.

TDD: первоначальный `pytest tests/test_judge_demo.py -q -k unsafe_target` → 4 FAIL: `app.judge_demo` отсутствовал. Отдельный RED для публичной метки и provider: `-k 'test_provider or server_access'` → 3 FAIL (`is_mock=False`, provider отсутствовал); после реализации → 10 PASS. Проверки выполнялись в disposable PostgreSQL на loopback55487, вне живого стенда, без OpenAI/Telegram ключей.

Финальная команда (из `services/api`, переиспользованный Python venv, изолированный `TEST_DATABASE_URL`): `python -m pytest -p no:cacheprovider tests/test_judge_demo.py tests/test_authz.py tests/test_seed_demo.py tests/test_review_policy.py -q --tb=short` → **97 passed in 87.38s**, exit0. Отдельный T18 прогон → **11 passed in 10.77s**. Проверены реальные серверные права master/worker, чужой UUID, scoped users/areas, rotation/revocation сессии, CSRF, MOCK/evidence, запрет worker приёмки, явное решение мастера и сохранение истории при повторе setup. `git diff --check` → exit0.

Живой URL/HTTPS/WSS/внешняя сеть/ready/restart проверяются основным агентом на изолированном стенде; здесь эти результаты не заявлены. Платных вызовов, изменений производственных данных и сброса ledger не было. [Код](../services/api/app/judge_demo.py), [поведенческие проверки](../services/api/tests/test_judge_demo.py), [инструкция](T18-judge-guide.md). Отдельное новое разрешение пользователя активировать OpenAI/Telegram с общим лимитом $10 реализуется и проверяется следующим commit; прежние расходы сохраняются.

Ограничение: свежие отчёты судей не получают предустановленный MOCK автоматически. Без consumer они ожидают; стандартный no-key worker даёт честный `human_review` о недоступном provider. Готовый объяснимый MOCK в №04 служит независимым резервным примером.
