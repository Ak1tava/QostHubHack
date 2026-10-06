# T07: запуск оценки

Перед добавлением ключа остановить запущенный `ai-worker` (`docker compose stop ai-worker`),
чтобы обычные фоновые проверки не расходовали средства параллельно ограниченному eval.
Его лимит $5 учитывает только вызовы runner. Из `services/api` (uv sync включает dev dependency resvg-py):

```powershell
uv run python -m app.modules.ai_review.eval_runner --split dev
uv run python -m app.modules.ai_review.eval_runner --live --split dev
uv run python -m app.modules.ai_review.eval_runner --freeze
uv run python -m app.modules.ai_review.eval_runner --live --split holdout
```

Первый запуск проверяет только серверные правила. Для двух `--live` нужен
OPENAI_API_KEY в окружении/.env. Без ключа exit2, нет провайдера, платных вызовов
и отметки начала holdout. Не добавляйте ключ в git. Подмена провайдера в unit-тестах
использует is_mock; production и live CLI никогда не создают фиктивный успешный ИИ-отчёт.

20 dev используются для настройки, затем `--freeze` фиксирует корпус, исходники
provider/rules/runner, schema/prompt/rules version, модели/reasoning/output caps,
SDK/rasterizer version и цены. Holdout — ровно один проход 12 заранее отложенных
примеров. Изменившаяся конфигурация или корпус не принимаются. Отметка начала
holdout создаётся эксклюзивно до первого вызова; прерванный проход также считается
использованным. Не удаляйте её ради повторной настройки по ответам holdout.

Единые ledger/lock/freeze/holdout находятся в `.tooling/t07/evals`, независимо от
`--output-dir`; этот аргумент меняет только назначение результатов. Dev и holdout
делят бюджет $5. Перед каждым вызовом, включая Astra, runner сохраняет резерв
полного bounded output (4096/8192 с reasoning), upper bound текстовых токенов
(UTF8 bytes, schema, wrapper margin) и каждого изображения. SVG преобразуются
resvg-py в PNG ≤1024px; пути, scenario/variant/метки/ответы не передаются провайдеру.
В модели находятся только C5 данные, server findings, реальные пиксели и id.

Резерв изображений — консервативный max(32768,2×PNG bytes) input tokens на фото.
Он рассчитан для поддерживаемых моделей/ограниченного размера; неизвестная модель
останавливает runner до запроса. Long-context Standard/cache-write upper rates с 10% запасом на
regional uplift проверены 2026-10-06 по [официальным ценам](https://developers.openai.com/api/docs/pricing).
Кеш-скидки игнорируются; тариф default задаётся SDK. Перед живым прогоном при изменении
тарифа обновите PRICES и заново зафиксируйте конфигурацию до использования holdout.

Usage после вызова уменьшает резерв до консервативной оценки стоимости; без usage
(timeout/unknown transport/crash) весь резерв остаётся расходом. Если фактические
токены нарушили оценочную границу, дальнейшие вызовы останавливаются для проверки.
Резерв — оценка, не гарантия выставленного OpenAI счёта при изменении внешних тарифов.

`dev.results.json` / `holdout.results.json` содержат каждый вызов: stage/model/reasoning,
prompt version, usage (включая reasoning/cached), latency, ошибку, response id,
резерв/оценку стоимости; raw source/секреты не логируются. Агрегаты: verdict accuracy,
recall обязательных findings, false acceptance, false rework, human_review, forbidden findings, несуществующие refs,
ошибки, model counts, tokens, p50/p95 latency и накопленная стоимость/резерв.
Rules-only точность описывает готовность серверной части, а не качество ИИ.

Детерминированная часть не передаёт неполные/повторные/заведомо непригодные доказательства
модели. Поле quality из fixtures — синтетическая серверная разметка для этих проверок;
production unknown декодируемого фото не означает визуальную пригодность. Sol задаёт
legible_refs после анализа реально переданных пикселей, и Astra доступна только для
нерешённого содержательного противоречия с существующими пригодными refs. Каждая stage
выполняет один SDK-вызов без внутренних retries, store=False. API/schema/refusal/incomplete
ошибки не эскалируются. Worker отвечает за максимум три сетевые попытки задания.

Схемы двух визуальных шаблонов и очистки SYNTHETIC не заменяют производственные
фото и экспертную разметку. Проверка attack-фраз в правилах — поясняющий heuristic;
защита не зависит от его полноты. Инструкции из текста/подписей/картинок всегда
считаются данными; сервер отдельно проверяет переходы и приёмку. Для смысловых
запрещённых утверждений нужны ручная проверка сообщений и настоящие фотографии.
