# Результаты T07

2026-10-06: выполнены **20 dev + единственный проход 12 holdout** через настоящие
Responses API. Общий расход по usage и консервативным тарифам: **$0.6868455**
из лимита $5; это оценка стоимости, а не выписка биллинга. Все 19 вызовов settled.

| Метрика | Dev | Holdout |
|---|---:|---:|
| Примеров | 20 | 12 |
| Совпадение вердикта с меткой | 55% | 50% |
| Recall обязательных findings | 81.25% | 84.21% |
| human_review | 15 | 10 |
| accepted / accepted_with_notes | 0 / 0 | 0 / 0 |
| requires_rework | 5 | 2 |
| Ложные принятия / возвраты | 0 / 0 | 0 / 0 |
| API/refusal/schema errors | 0 | 0 |
| Несуществующие refs в итоговом результате | 0 | 0 |
| Вызовы Sol / Astra / Luna | 11 / 1 / 0 | 6 / 1 / 0 |
| Input / output tokens | 38043 / 5226 | 22232 / 3692 |
| Reasoning tokens (входят в output) | 1547 | 1656 |
| Call latency p50 / p95, ms | 10625 / 17375 | 11141 / 20907 |
| Расход этой части, USD | 0.3996795 | 0.2871660 |

Положительных вердиктов нет, поэтому нулевой счётчик ложных принятий не подтверждает
качество принятия. 25/32 примера ушли мастеру. Guard-коды: `completion_unverified`
14, `invalid_provider_evidence` 4; также встречаются непригодные изображения и
смысловые противоречия. Исходные findings модели были отброшены защитой, поэтому
точная причина нарушения refs/формулировок по сохранённому финальному результату
не подтверждена. Guard-проверки не ослаблялись, prompt не изменялся.

IO/recovery исправление проверено в [CI 332f5fe — SUCCESS](https://github.com/Ak1tava/QostHubHack/actions/runs/37504054292):
1485 PostgreSQL pytest, 54 Vitest, 15 Playwright и Compose/worker recovery PASS.

Подробный отчёт со всеми кейсами, usage/latency/cost каждого вызова и frozen config:
[reports/T07-live-2026-10-06.json](reports/T07-live-2026-10-06.json).
Luna в этом живом наборе не вызывалась; её маршрутизация проверена unit-тестами.

Заморожены prompt `t07-v1`, rules `t07-rules-v1`, модели/reasoning и схема.
Корпус: `e31bcf758f4aa7d83382c7e27cb6467d40392b2e6dadf1bea8faf0532ff51929`.
Source: `99ae25a63a104310c83083c3c6ca834a5d57748d9a5909ff7308179c0bcefd3a`.

Первый dev прервался на Windows sharing violation при записи бюджета до вызова
Astra. 9 завершённых кейсов сохранены; `--resume-dev` выполнил оставшиеся.
Оплаченный primary незавершённого кейса учтён, его повтор также входит в общий
расход. Переход source hash зарегистрирован в `previous_configs`; изменения
касались IO/recovery runner, а не prompt/правил/маршрутизации. После user-выбора
выполнить только holdout дополнительных диагностических запросов не было.

Фактические команды (из `services/api`, Windows PYTHONUTF8=1):

```powershell
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --live --split dev
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --live --split dev --resume-dev --resume-from-source-hash 92f2685478fcfd752ceb98cc1c79c19d28268b45fa27a2eeb068c0ae5b1dac75
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --freeze
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --live --split holdout
```

Первый exit1 (IO), продолжение/freeze/holdout exit0. Holdout marker сохранён;
не удалять и не повторять этот набор. Синтетические PNG не заменяют реальные
производственные фотографии; качество ИИ остаётся неприёмочным, T07 — REVIEW.

## До добавления ключа

Фактически выполнено из `services/api`:

```powershell
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --split dev
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --live --split holdout
```

Первый: exit0, 20 dev, mode=rules_only. Verdict accuracy 0.50; required findings
recall 0.71875; false acceptance 0; false rework 0; human_review 16;
forbidden findings 0; invalid evidence refs 0;
вызовы/токены/стоимость 0. Этот offline результат предшествовал живому прогону.
Второй: exit2, сообщение BLOCKED до создания провайдера и holdout marker.

Эти метрики проверяют правила и human-review fallback без модели, не качество
Sol/Luna/Astra. SVG синтетические; производственную приёмку они не заменяют.
Правила дальнейших прогонов — [инструкция](T07-runner.md).
