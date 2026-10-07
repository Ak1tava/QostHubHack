# Новая фотопроверка T07 — дополнительный лимит $8

Это отдельный корпус. Старые 12 holdout T09 и их журнал $5 не запускаются и не изменяются.

Источники/хеши: sources.json. Rezitech и ACCA — dev; Corrocoat и Westin — holdout.
8 исходных кадров из четырёх опубликованных проектов, 8 dev и 12 контрольных случаев
(4 good, 4 bad, 4 ambiguous). Варианты на одинаковых снимках коррелируют и не являются
12 независимыми ремонтами. Тексты нарядов синтетические, источники не подтверждают
производственные нормы. Публичная доступность снимков не означает права на их
распространение: лицензию перераспространения не подтвердили, все медиа только в ignored .tooling.

Подготовка из services/api:

```sh
uv run --locked --with pypdf python ../../evals/quality/prepare_media.py
```

Источник проверяется SHA256; изменение исходного файла требует пересмотра корпуса.
Из PDF извлекаются только кадры без подписей. Коллаж Westin разделяется на два кадра.
JPEG нормализованы <=1024px, EXIF/URL/подписи сайта не передаются модели.
Ссылки имеют настоящий формат worker photo:<UUID>; условные имена из few-shot
не используются как входные id. Для v3 это закреплено регрессией.
Намеренное размытие — отдельные помеченные производные для проверки отказа от вывода.

Ключ — только корневой ignored .env. Последовательность из services/api:

```sh
uv run --locked python -m app.modules.ai_review.quality_eval --live --split dev
uv run --locked python -m app.modules.ai_review.quality_eval --live --split comparison
uv run --locked python -m app.modules.ai_review.quality_eval --freeze
uv run --locked python -m app.modules.ai_review.quality_eval --live --split holdout
```

Без --live dev проверяет только правила; comparison/holdout не имитируют модель.
Максимум два разных промпта; после freeze dev/comparison закрыты. Holdout — единственный
проход, без resume. Нельзя удалять frozen.json, marker или budget.json ради повторения.
После ошибки сравнение пропускает уже начатый пример, включая неизвестный usage.
Все вызовы, включая автоматическую эскалацию, учитываются в одном fixed журнале
.tooling/t07-quality/budget.json. До holdout расход/резерв <=$5, общий <=$8.
Неизвестный usage удерживает полный резерв. Геометрический резерв Astra <=1024px:
1300 токенов/фото против документированных <=1229; остальные модели — 32768.
Тарифы — консервативные long-context/cache-write +10%, а не выписка биллинга.
https://developers.openai.com/api/docs/guides/images-vision
https://developers.openai.com/api/docs/pricing

Локальные отчёты сохраняют структурированный ответ до проверки, итоговый ReviewResult,
причину отклонения и usage каждого этапа. Raw ответы/секреты в Git не публикуются.
Критерии: >=3/4 good положительных, 0 принятых bad, 4/4 ambiguous human_review.
C5 и OpenAPI не менялись. Нет автоматического CLOSED или подтверждения скрытых узлов.
