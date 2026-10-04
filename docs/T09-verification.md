# Проверка Т09

Дата: 2026-10-04. База: main 7bc2b3ac4eace725ddf8bf6288d820041249474b. Ветка: feat/T09-demo-evals. До интеграции статус REVIEW.

Среда: Windows, Python 3.12.15, uv 0.12.22, настоящий локальный PostgreSQL, исходный uv.lock. Код main восстановлен через авторизованный GitHub connector с проверкой каждого blob, дерева и исходного commit SHA; CLI clone не прошёл авторизацию. Локальный checkout shallow. Изменений main не выполнялось.

## Выполненные проверки

- Полный исходный main: pytest -q → 1153 passed in 353.50s.
- Первый seed тест RED: команда app.seed_demo отсутствует. Calendar/count/determinism/history → GREEN.
- Откат файлов RED: PNG остались после rollback; добавлена очистка созданных текущей транзакцией файлов → GREEN.
- Историческая смена RED: повторный ремонт после ППР ссылался на предыдущую смену; исправлена привязка дня/ночной смены → GREEN.
- Целевой seed + eval: 20 passed in 177.28s до добавления теста конкуренции.
- Eval test-first: отсутствующий корпус → RED; несогласованное изображение плановой очистки → RED; исправлено; шесть проверок корпуса → GREEN.
- CLI на отдельной БД qosthub_test_t09_cli, миграции до head и alembic check: PASS, No new upgrade operations detected.
- Настоящая команда python -m app.seed_demo --seed 42 --as-of 2026-10-04 → created; повтор → unchanged. 500 нарядов, 17 пользователей, 0 исторических outbox.
- ASGI через production app/TestClient с этой PostgreSQL БД: csrf/login, список 500 нарядов, карточки и смена 17 пользователей → PASS. Это ASGI проверка, не испытание браузера/телефона.
- Ruff format/check --isolated --select F,I и git diff --check: PASS.

Независимое ревью выявило 3 важных замечания, исправленных одним проходом; также согласована пятибалльная шкала C6. Все 11 регрессий сначала дали RED, после исправлений — 11 passed in 15.51s. Повтор CLI/мигрированная PostgreSQL/ASGI после исправлений — PASS на новой отдельной qosthub_test_t09_final. Решения и границы — T09-review.md. Полный финальный pytest после исправлений: **1185 passed in 368.93s (0:06:08), exit 0**. Это 1153 исходных и 32 новых проверки. Ruff и git diff --cached --check после нормализации LF — PASS. Финальный коммит содержит этот отчёт; SHA определяется git log -1 --format=%H.

## Воспроизведение

Из services/api: uv run pytest tests/test_seed_demo.py tests/test_eval_cases.py -q; полный набор: uv run pytest -q. Нужны TEST_DATABASE_URL в одноразовую qosthub_test* и MIGRATION_TEST_DATABASE_URL в отдельную qosthub_migration_test* PostgreSQL БД. Fixtures изменяют только эти тестовые БД. Для CLI нужна отдельная qosthub_demo* БД, миграции, пароль вне Git и каталог файлов.

## Границы результата

Нет запросов к модели, результатов качества, latency или стоимости. Нет реальных фотографий и производственных персональных данных. Фото — синтетические схемы; eval не доказывает точность на реальных ремонтных изображениях. Frontend, HTTP-контракты, модели, миграции, manifests и контейнерная конфигурация не менялись. Seed запускается из checkout; инструкции для передачи data/demo контейнеру — T09-data.md. Т07/T08/T10 проверяются в своих задачах.
