# T15: фактическая фотопроверка и границы выводов

Inspection по коду base `cd9bc97`, 2026-10-08. Model/prompt/rules не менялись; новые provider calls и прежний used holdout не запускались. Новый реестр — [50 кандидатов](../evals/t15/README.md), а не размеченный production benchmark.

## От наряда до вердикта

| Этап | Фактический вход/действие | Код |
| --- | --- | --- |
| Загрузка | Проверяются права, текущие версии и состояние наряда. Мастер прикладывает `before` к выданному наряду; исполнитель — доступные фото своей работы. JPEG/PNG/WebP, MIME должен совпадать с декодированным форматом; максимум5MiB,8192px по стороне,16MP. | [photos/service.py](../services/api/app/modules/photos/service.py) |
| Нормализация | PIL проверяет/декодирует файл, применяет EXIF orientation и копирует пиксели в чистое изображение. EXIF/текстовые метаданные не сохраняются. После повторного кодирования считаются SHA-256 нормализованных байтов и64-bit dHash из серого9×8 изображения. | `photos/service.py::_normalize` |
| Immutable report | `ReviewInput`: work_order_id, submission_revision, assignment_version, problem, work_description, material_checks, timing_checks, photo_refs, checklist. Материалы, нормы и время строит сервер. Выбираются фото текущего submission плюс ранее полученные `before` его исполнителя/мастера этого наряда, не позднее submitted_at. | [ai_review/inputs.py](../services/api/app/modules/ai_review/inputs.py) |
| Snapshot | Persisted job хранит `base_input`, `input`, `rules`, `plan`, версии наряда/назначения/отчёта. При изменении snapshot работа возвращается на prepare в пределах restart limit; superseded result отбрасывается. Lease token проверяется перед сохранением результата. | [workers/reviews.py](../services/api/app/workers/reviews.py) |
| Чтение медиа | Проверяется принадлежность фото выбранному наряду/отчёту и SHA-256 файла. Минимальная сторона160px; фото преобразуется в RGB, thumbnail≤1600×1600 и JPEG quality85 для provider. Ошибка чтения/хеша/размера даёт quality=`unusable`. Исходная quality=`unknown` не является подтверждением качества. | `inputs.py::read_images` |
| Дубли | Историческое совпадение content_hash или **точное** совпадение perceptual_hash отмечается duplicate_of; одинаковые fingerprints внутри ReviewInput также блокируют уверенное принятие. Это не поиск всех похожих фото и не доказательство идентичности оборудования. | `inputs.py::build_input`, [rules.py](../services/api/app/modules/ai_review/rules.py) |
| Server rules | Пустое описание/обязательное emergency-after фото/неполные поля дают requires_rework. Дубликат или unusable фото — human_review. Нормы расхода и время оцениваются сервером; при отсутствии нормы превышение не выдумывается. Тексты и подписи остаются недоверенными данными. | `rules.py::assess_rules`, version=`t07-rules-v1` |
| Provider | Только подходящая плановая работа без фото/обязательного фото/аномалий идёт text-only в light. Остальное — primary; complex escalation допустима при unresolved conflict с валидными evidence refs, а не вместо повторения failed call. Текущие defaults: gpt-6-luna / gpt-6.1-sol / gpt-6-astra; StagePlan prompt=`t07-v3`. | [service.py](../services/api/app/modules/ai_review/service.py), [provider.py](../services/api/app/modules/ai_review/provider.py) |
| Изображения в request | Для каждого photo-ref отправляется текстовый идентификатор и image data URL detail=high. Provider требует все заявленные image refs; не скачивает произвольные URL из отчёта. Лимиты адаптера:20 images,10MiB на image; формат декодированного изображения проверяется вновь. | `provider.py::request_content`, `image_data_url` |
| Evidence refs → результат | Ссылки должны принадлежать ReviewInput. Для положительного work_matches_problem нужны одновременно `problem` и `work_description`; при наличии фото также читаемый after-ref. Для отрицательного requires_rework нужен work_problem_mismatch severity=error с обеими текстовыми ссылками. Невалидные ссылки/неподтверждённый результат/запрещённые выводы переводятся в human_review. Арифметические и нормативные объяснения остаются серверными. | `service.py::finalize_result` |
| Сохранение и мастер | AIReview хранит результат, model/prompt_version, latency, calls/usage/rules_version. requires_rework переводит наряд в REWORK; прочие AI verdict обновляют текущую проверку. Мастер отдельно принимает/возвращает/отклоняет; нужны причины для rework, переопределения неподдержанного accept и изменения рекомендованной оценки. AI accepted не закрывает наряд. | `workers/reviews.py::_save_final`, [decisions.py](../services/api/app/modules/ai_review/decisions.py) |

Snapshot фиксирует серверные факты, но не подтверждает место/дату съёмки или подлинность сцены. content_hash — хеш нормализованных байтов, а не оригинального upload; JPEG для provider снова преобразован. Нормализованные EXIF-free фото всё ещё могут содержать лица, документы и иные данные в пикселях.

## Значение вердиктов

- `accepted`: описание соответствует задаче и требуемые видимые доказательства пригодны; мастер ещё должен принять решение. `accepted_with_notes` сохраняет дополнительные неблокирующие замечания.
- `requires_rework`: нужно дополнить обязательные доказательства или исправить подтверждённое несоответствие работ заявке. Пользовательское «rework» в интерфейсе соответствует этому AI verdict, а мастерская команда называется `rework`.
- `human_review`: нет достаточной основы для уверенного вывода — например, дубликат, плохое изображение, несопоставимые ракурсы, чужой объект, конфликт, неизвестные evidence refs или ошибка provider. Score отсутствует; нужен мастер.

Фото показывает доступную поверхность и установленность видимых деталей. Оно не доказывает давление, герметичность после испытания, момент затяжки, соосность, толщину, электробезопасность, скрытые трещины, внутреннее состояние закрытого узла, причину дефекта или безопасность запуска. Сухой кадр после ремонта течи не заменяет контроль под нагрузкой. Разные интернет-снимки нельзя объединять в before/after одного наряда.

## Что уже измерено, а что ещё нет

Готовые опубликованные traces находятся в [T07-live-2026-10-06.json](../evals/reports/T07-live-2026-10-06.json) и [T07-quality-2026-10-07.json](../evals/reports/T07-quality-2026-10-07.json). Это исторические результаты со своими frozen_config, корпусами и ограничениями; их метрики нельзя переносить на50 новых интернет-кандидатов. Файлы изучались только как сохранённые артефакты; использованный holdout повторно не исполнялся.

Для T15 подтверждены страницы/конкретные media endpoints и полнота реестра; visual/master labels, нормальные/неоднозначные контрольные снимки и полные реальные report inputs ещё отсутствуют. Перед новым измерением мастер размечает видимый факт и допустимость evidence, независимо задаёт ожидаемый verdict и фиксирует инструкции разметки. Нужны FP/FN на подтверждённых случаях, доля human_review, latency/cost по сохранённым фактическим traces; до этого production accuracy не заявляется.
