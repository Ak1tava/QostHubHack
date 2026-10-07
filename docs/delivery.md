# Комплект сдачи и ограничения T10

Статусы проекта ведутся только в `plans.md`. Этот файл — перечень результата и оставшейся приёмки; утверждение «реализовано» не означает подтверждённое живое демо.

| Результат | Место | Что проверять при сдаче |
| --- | --- | --- |
| Русская PWA с ролями/нарядами | `apps/web`, `services/api` | Полный цикл/чужие UUID через настоящий API/БД, production build |
| Telegram привязка и доставка | `features/telegram`, `modules/telegram` | Одноразовая ссылка, статус/unlink, собственная доставка worker; реальный бот/webhook ещё требует live |
| До пяти исходных фото мастера | `CreateOrderPage`, `modules/photos` | Только собственный ISSUED наряд, версии, частичная ошибка без второго наряда; worker/ИИ видят сохранённые фото |
| Отчёты/рейтинг/закономерности | `features/reports`, `modules/analytics` | API/SQL совпадают, чужие оценки недоступны; отсутствующие R/V/подтверждения явно «нет данных» |
| Синтетическая история | `app.seed_demo`, `data/demo` | 500 нарядов за три месяца, дата демо, реальные private files; expected answers только для тестов |
| HTTPS overlay | `compose.tunnel.yaml`, `infra/nginx.tunnel.conf.template` | Точный Host/421, Secure cookie, webhook, доверие proxy; Docker/Nginx и live tunnel требуют стендовой проверки |
| Live worker ≤$2 | `app.workers.budgeted_reviews` | Обычный worker выключен, persistent ledger/lock, неизвестный резерв не освобождается; CI/fake tests не являются paid проверкой |
| Backup/restore | `docs/runbook.md`, `compose.restore.yaml` | Фактическая копия БД+private photos+ledger и восстановление отдельно; запуск consumers на restore выключен |
| Сценарий защиты | `docs/demo.md` | Живые 7 минут, два iPhone, отдельный Android, ≤60сек/≤6действий/≤5сек/≤10сек |
| Презентация/резервное видео | [presentation.pptx](delivery/presentation.pptx), [reserve.webm](delivery/reserve.webm) | 8 editable slides; резерв17.44с с явно обозначенным сохранённым настоящим ИИ-ответом |
| Проверка и точный SHA | [verification.md](verification.md) | Code109b418; PostgreSQL1578/Vitest79/E2E17 PASS, ограничения и фактические проверки отдельно |

Не включать `.env`, API/Telegram ключи, сессии, внутренние дампы и производственные фото в публичный комплект. Docker Desktop устанавливает пользователь; без него контейнерный запуск/overlay/restore не заявляются проверенными. Живые Telegram, paid worker/PWA, физические телефоны и мобильная сеть не подменяются автоматическими тестами. До их прохождения T04–T07/T10 сохраняют незавершённую живую приёмку.
