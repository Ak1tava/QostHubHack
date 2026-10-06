# Результаты T07

2026-10-06: живой eval **BLOCKED**, OPENAI_API_KEY отсутствует. Платные вызовы: 0,
потрачено $0. Holdout не запускался и не помечен использованным; конфигурация для
живого holdout ещё не заморожена.

Фактически выполнено из `services/api`:

```powershell
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --split dev
.venv/Scripts/python.exe -m app.modules.ai_review.eval_runner --live --split holdout
```

Первый: exit0, 20 dev, mode=rules_only. Verdict accuracy 0.50; required findings
recall 0.71875; false acceptance 0; false rework 0; human_review 16;
forbidden findings 0; invalid evidence refs 0;
вызовы/токены/стоимость 0. JSON: `.tooling/t07/evals/dev.results.json`.
Второй: exit2, сообщение BLOCKED до создания провайдера и holdout marker.

Эти метрики проверяют правила и human-review fallback без модели, не качество
Sol/Luna/Astra. SVG синтетические; живую приёмку они не заменяют. После ключа
выполнить dev, freeze и единственный holdout по [инструкции](T07-runner.md), затем
добавить сюда фактические usage/latency/стоимость и ошибки всех модельных вызовов.
