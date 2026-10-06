# T05 — план реализации

Спецификация: карточка T05 и C1–C3 в `plans.md`. Владелец A + B / Codex, ветка `codex/t05-execution-evidence`, база — запушенная T04 `f74c42a`. Пользователь поручил реализацию существующего плана и разрешил подагентов; повторное проектирование и согласование той же задачи не требуется.

- [x] Отчёты: сначала HTTP-тесты, затем `submissions.py`, схема запроса и маршрут. Проверять исполнителя/версию, каталог, материалы, принадлежность фото, повтор команды. Создание revision, расхода, события и outbox — одна транзакция через `apply_internal`; прежние revision неизменяемы.
- [x] Фотографии (независимый подагент): сначала тесты, затем private filesystem storage, проверка фактического изображения/MIME/5 МБ, защищённое чтение. Нужные поля Photo — миграция 0003. Пользовательское имя не участвует в пути; хеш и perceptual hash — сигналы повторного использования. Полномочия проверяются сервером.
- [x] Исполнитель (независимый подагент): `/my-orders`, `/orders/:id/execute`, действия C2 с причинами, сжатие фото, отчёт/материалы и сохранение ввода при ошибке. Типы только из OpenAPI; T04 сохраняется.
- [x] Интеграция: зависимости/lock, routers, OpenAPI/TS, настройки proxy/body limits и проверки миграций. Поведенческие API, Vitest/build и браузерный сценарий; fresh-context ревью, исправления, запись фактических результатов.

Контракты: multipart `POST /work-orders/{order_id}/photos` (`file`, `type`, опциональный `captured_at`) → PhotoView; `GET /photos/{photo_id}` после проверки доступа. JSON `POST /work-orders/{order_id}/submissions` с `expected_version`, `assignment_version`, `work_description`, `fault_code_id`, `materials`, `no_materials_used`, `after_photo_ids`, `comment`, заголовком Idempotency-Key → SubmissionView (201). Неуспешная команда не занимает ключ.

Границы: ИИ и человеческая приёмка остаются T07; неполный отчёт допускается к проверке с missing_evidence, закрытие продолжает блокировать ядро T03. Ручные замеры на телефонах/мобильной сети и Docker persistence нельзя выдавать за локальные автоматические проверки. До интеграции статус REVIEW.

Распределение файлов: root — submissions/router/schema/queries/state_machine, общие manifest/main/OpenAPI/документы; photos agent — только новый photos модуль, Photo в models.py, 0003 и test_photos.py; web agent — только apps/web/src и новый E2E-сценарий. Общие файлы/контракты меняет root.
