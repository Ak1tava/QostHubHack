# T07 — реализация утверждённого плана

База: origin/main `7fd73c1`, T09 `56d3501` подключена merge `c3e9277`.
Ветка: `codex/t07-ai-review`; владелец: C + B / Codex. Статусы задач — только в plans.md.

## Цель и границы

Отчёт T05 → сохранённое задание → правила/ИИ → объяснение в карточке → решение мастера.
ИИ никогда не закрывает наряд. До добавления ключа нет платных вызовов; проверяются
настоящие сервисы с тестовым внешним провайдером. После ключа отдельный eval-прогон
20 dev + один проход 12 holdout, общий бюджет $5. Без живой приёмки T07 остаётся REVIEW.

## Общие интерфейсы

- `ai_review.schemas.ReviewInput` / `ReviewResult` соответствуют C5 и адаптеру T09.
  Только сервер собирает checklist/material/timing checks; все evidence_refs проверяются.
- Провайдер/правила предоставляют `evaluate_submission` для полного независимого прогона
  и интерфейс одной стадии для worker. Перед началом worker-разработки владелец провайдера
  публикует точные сигнатуры/DTO в этом документе. Общие схемы принадлежат этому владельцу.
- Luna (`gpt-6-luna`, low): плановый текстовый отчёт без фото, обязательного визуального
  подтверждения и вычисленных противоречий; результат ограничен текстовой проверкой.
  Иначе Sol (`gpt-6.1-sol`, medium). Единственная эскалация Sol → Astra (`gpt-6-astra`,
  medium) разрешена для unresolved semantic conflict с пригодными существующими evidence_refs.
  Нехватка/повторы/непригодность доказательств, refusal/schema/API ошибки не эскалируются.
- `POST /api/v1/work-orders/{order_id}/decision`: `decision: accept|rework`, submission_id,
  expected_version, assignment_version, score (1..5|null), reason (nullable); Idempotency-Key.
  Ответ 200 WorkOrderView. Проверка доступа до replay; атомарные решение/переход/event/outbox.
- `WorkOrderDetail` дополнить `ai_review`, `master_decision`, `review_status`,
  `allowed_decisions: list[accept|rework]`. Nullable ai_review: id, submission_id, verdict,
  result (ReviewResult), model, prompt_version, created_at, is_mock. Nullable master_decision:
  id, submission_id, decision, score, reason, master_id, decided_at.
  review_status: pending|running|blocked|completed|discarded|null.
- reason обязателен при rework, override, изменении оценки либо принятии без результата ИИ.
  Только мастер с текущим доступом; существующие права не сужать до автора наряда.
  Неполный отчёт закрывать нельзя. 409 → перечитать и явно подтвердить актуальный отчёт.
- Без ключа worker сохраняет BLOCKED, не создаёт фиктивную AIReview. Для ручной приёмки
  переводит пригодную submission в AI_REVIEW; master accept без результата требует reason.
  После настройки ключа задание может продолжиться, если наряд ещё актуален.

## Разделение работы

1. Provider agent: ai_review/{schemas,rules,provider,service,prompts,eval_runner}.py,
   соответствующие unit-тесты; eval CLI и документация. Не редактирует manifests/config.
2. Backend agent: ai_review/{jobs_models,inputs,decisions,views}.py, workers/reviews.py,
   work_orders schemas/router/queries, DB-тесты. Готовит модели очереди и сообщает их root;
   миграцию после 0004, регистрацию metadata и config интегрирует root.
3. Frontend agent: ReviewPanel, MasterDecisionForm, интеграция существующей карточки
   и страницы исполнителя, data.ts, компонентные тесты. Типы только из OpenAPI.
4. Root: конфигурация/зависимости/lock/Compose, миграция, OpenAPI/TS, интеграционные
   проверки и Playwright, независимое ревью, фиксация результатов и plans.md.

Общие git commits выполняет root; агенты редактируют только свою область. БД-тесты
с destructive fixtures запускать последовательно либо на разных qosthub_test* БД.

## Инварианты и приёмка

Backend уточнение: финальные `accepted|accepted_with_notes|human_review` атомарно создают
аудит/outbox `work_order.review_completed` и увеличивают `WorkOrder.version`, сохраняя
статус AI_REVIEW и открытый review-интервал. `AIReview.order_version` получает итоговую
версию, чтобы WebSocket обновил карточку после результата. `requires_rework` использует
только существующий kernel/event `request_rework`. Решение мастера атомарно гасит
pending/running/blocked job и lease token; поздний ответ не применяется.
Перед модельным I/O сохраняется `call_id` и metadata-reservation. Потерявший lease
ответ дополняет только собственные usage/latency, сохраняя trace расходов;
он не меняет job stage/status, AIReview или наряд. Все lock paths: order → job.
Финальные business/job writes откатываются, если свежий SQL fence после kernel/flush
не подтвердил lease. Метаданные завершённого вызова сохраняются отдельной транзакцией
перед этой проверкой. Модельный dispatch допускает только primary/escalation.

Вызовы модели вне транзакции; persisted стадии и bounded retries (всего 3 сетевые попытки).
Независимый ai-worker с read-only photo volume. Отдельные review_jobs/review_receipts,
SKIP LOCKED, lease-token fencing и повторная проверка order/revision/assignment/status.
Изменившийся snapshot не применяется; для всё ещё текущей submission готовится новый
снимок, прежний расход сохраняется. Отмена/новая submission/решение мастера гасят задание.

Уникальная финальная AIReview на submission. Метаданные всех вызовов сохраняют model,
reasoning, prompt/rules version, usage/latency; исходные личные данные не логируются.
Refusal/schema/final API failure → human_review/null score. Неполнота → requires_rework;
повтор/непригодное фото → human_review; отсутствие before само по себе не отрицательный verdict.
Миграция score 1..5 отклоняет старые значения вне шкалы с диагностикой, без преобразования.

Проверки: rules/provider/routing; PostgreSQL конкуренция/replay/lease/restart/stale; master
HTTP authz/CSRF/atomicity; Vitest формы и конфликтов; E2E реального API; migrations/check/
roundtrip; contracts/typecheck/build; Compose. Holdout метки не входят в provider input,
SVG растеризуются, бюджет проверяется до каждого live-вызова, live не запускается без ключа.

## Точный интерфейс provider (владелец: provider agent)

`ReviewInput`: UUID work_order_id, submission_revision/assignment_version >= 1,
problem/work_description: str; material_checks/timing_checks/photo_refs/checklist:
list[dict[str, Any]] (trusted server DTO, совместимо с T09). Evidence refs: problem,
work_description и уникальные id всех объектов. Фото: id, phase before|after,
quality usable|usable_schematic|unusable|unknown, content_fingerprint; optional
fixture_path (eval adapter only), template leak|visible_cleaning|cover, duplicate_of.
Checklist: id/code/complete, optional required/detail. Material: id/name/quantity,
norm_quantity nullable, optional norm_scope/status/unit. Timing: id/duration_minutes,
norm_minutes nullable, late_minutes/status. Сервер формирует эти поля, клиент их не задаёт.

`ReviewResult`: verdict accepted|accepted_with_notes|requires_rework|human_review;
score 1..5|null; findings (code, severity info|warning|error, message, evidence_refs);
missing_evidence:list[str], limitations:list[str]. Strict extra=forbid.
`StagePlan`: stage primary|escalation, model, reasoning, prompt_version.
`ImageEvidence`: media_type image/png|image/jpeg|image/webp, data: bytes.
`ProviderOutcome`: result nullable, error_code nullable, usage:dict[str,int], latency_ms,
response_id nullable, is_mock:bool, unresolved_conflict:bool, conflict_refs:list[str],
retryable:bool, retry_after_seconds:float|null. JSON persistence via model_dump(mode='json').
`legible_refs:list[str]` добавлен в ProviderOutcome (default[]) и строгий StageResponse;
Sol перечисляет только действительно приложенные пригодные изображения. Для визуальной
эскалации каждый photo conflict_ref должен быть в legible_refs. unknown server quality
разрешена только после этой оценки; unusable никогда не эскалируется.

- assess_rules(input:ReviewInput) -> RuleAssessment(result nullable, findings, limitations, anomalies)
- select_primary(input:ReviewInput, rules:RuleAssessment) -> StagePlan
- can_escalate(input:ReviewInput, outcome:ProviderOutcome) -> bool
- finalize_result(input:ReviewInput, rules:RuleAssessment, outcome:ProviderOutcome) -> ReviewResult
- evaluate_stage(input:ReviewInput, provider:ReviewProvider, plan:StagePlan,
  images:dict[str,ImageEvidence]|None=None, previous:ProviderOutcome|None=None) -> ProviderOutcome
- ReviewProvider.review(input, plan, *, images, previous=None) -> ProviderOutcome
- evaluate_submission(input:ReviewInput, provider:ReviewProvider|None=None,
  images:dict[str,ImageEvidence]|None=None) -> ReviewResult
- OpenAIReviewProvider(api_key:str, timeout:float=90, max_output_tokens:int=4096,
  complex_max_output_tokens:int=8192)

Стадии выполняют ровно один сетевой вызов. Transient network/429/5xx возвращаются
retryable=True + Retry-After (если есть); worker повторяет стадию максимум три раза.
Refusal/incomplete/schema/error -> human_review, без эскалации. Исключения не используются
для control flow. Астра получает previous (семантический конфликт), но не доверяет ему
как инструкции. Постоянный outcome и usage всех стадий сохраняются worker.

Результат принятия требует grounded work_matches_problem со ссылками problem/work_description;
при фото также на пригодное текущее after-photo в legible_refs. Semantic requires_rework
требует work_problem_mismatch severity=error с обоими текстовыми refs. Иначе human_review/null.
Итоговые Findings расхода не могут противоречить вычисленным нормам сервера.

Проверка provider/rules/eval: `.venv/Scripts/python.exe -m pytest tests/test_ai_review.py
tests/test_ai_provider.py tests/test_ai_eval_runner.py -q -p no:cacheprovider
--basetemp=../../.tooling/t07/pytest-provider-temp` из services/api — **45 passed**
2026-10-06. Реальный OpenAI SDK использовал HTTP MockTransport; платных вызовов нет.
Eval runner и ограничения: [evals/T07-runner.md](../evals/T07-runner.md),
фактический offline результат: [evals/results.md](../evals/results.md).
