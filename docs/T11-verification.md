# T11 и обновление стенда — 2026-10-08

Владелец A + B / Codex. Ветка `codex/t11-qr-stand` от `origin/main 3af3261`. Только обновление существующего стенда и QR; T12/T13 не выполнялись. T11 готов к ревью, без слияния в main и без публикации нового функционала на живом стенде.

## Работающий стенд

Windows, native Nginx 1.30.5 и существующий Cloudflare Quick Tunnel. API — loopback 8005, Nginx — 5182. Изолированный release `.tooling/stand-main-3af3261` получен через `git archive origin/main`; туда помещён production build main. Старый локальный launcher переключён на этот release. Туннель не перезапускался; PUBLIC_BASE_URL, прокси hostname, настройки cookie и webhook согласованы и сохранены.

Перед обновлением остановлены только mobile API и notification consumer. `pg_dump -Fc`, копии приватных фото, конфигурации, аккаунтов, бюджета и Nginx сохранены в ignored `.tooling/t11-live-backup/`. Сохранность повторно проверена после всех работ: содержимое 28 таблиц, 465 файлов фото, SHA256 live-конфигурации и budget.json совпадают. Сессии/throttle не включены в сравнение неизменности; полный dump содержит их. Reseed живой БД не выполнялся.

| Фактическая команда / проверка | Результат |
| --- | --- |
| `npm --prefix apps/web run build` из main, затем `alembic upgrade head` на сохранённой БД | PASS; миграционных изменений нет, 11 PWA precache entries |
| `.tooling/t11-deploy-main.ps1`, `nginx -t`, reload | PASS; API и статика из main, прежний notification worker восстановлен |
| `.tooling/t11-live-snapshot.py before/after` | PASS; повторный after в конце работы также PASS |
| `.tooling/t11-live-browser.cjs` на настоящем публичном HTTPS | PASS: вход, readiness 200, T14 navigation, 390 px без overflow |
| В браузере со старым установленным SW: `registration.update()` → «Обновить приложение» | PASS; bundle `index-CfMYtC4Q.js` заменён на `index-CM3NZMqH.js`, сессия сохранена |
| Anonymous `/auth/me`, `/work-orders`, `/photos/{id}` | 401; SW отдаётся с no-cache |
| Telegram `getWebhookInfo`, без отправок | URL совпадает с PUBLIC_BASE_URL, pending_updates=0, ошибок нет |
| Проверка процессов в конце работы | AI consumers отсутствуют; новые платные вызовы и holdout не выполнялись |

Секреты, cookies, chat_id, dump и фото не публикуются. Локальные диагностические скрипты/артефакты ignored. Откат: вернуть nginx-конфигурацию и launcher из backup, запустить прежний API из `t08-t10-integration`; БД/фото при откате кода не пересоздавать.

## QR

- [Сервер](../services/api/app/modules/catalog/equipment.py): карточка существующего оборудования, область доступа каталога, прежний actor/brigade scope нарядов до сортировки и LIMIT 10. Поля истории: дата, номер, краткое описание, статус и detail URL. Фотографии остаются в защищённом API.
- [PWA](../apps/web/src/features/equipment/EquipmentPage.tsx): `/equipment/{id}`, сохранение маршрута после входа, история, скачивание SVG QR/наклейки и печать наклейки. URL — только HTTPS origin из PUBLIC_BASE_URL; HTTP dev-конфигурация показывает понятное отсутствие QR.
- [Создание](../apps/web/src/features/work-orders/CreateOrderPage.tsx): мастер получает equipment/area из разрешённого каталога. Подменённый area_id не переопределяет участок оборудования; чужой equipment_id не выбирается. Прежние команды/CSRF/idempotency/версии сохранены.
- Генерация локальная через закреплённый `qrcode@1.5.4`, без внешнего QR-сервиса и без сканера. QR не содержит токенов. При смене временного Quick Tunnel адреса наклейки потребуется выпустить заново.

## Проверки ветки

Windows/Python 3.12/Node 24.19; настоящий PostgreSQL на loopback. Изолированные БД: `qosthub_test_t11`, `qosthub_migration_test_t11`, `qosthub_demo_t11`. Для API использовано имеющееся полное venv от T08/T10 с тем же uv.lock. Ключи OpenAI/Telegram не передавались тестовому стенду.

| Команда | Фактический результат |
| --- | --- |
| `pytest tests/test_equipment.py -q` | 15 PASS: четыре роли, чужое оборудование 404, anonymous 401, assignment/brigade before limit10, стабильная сортировка, пустая история, canonical URL, no-store |
| `pytest -q` с TEST_DATABASE_URL и MIGRATION_TEST_DATABASE_URL | **1593 PASS**, 349.02 с; включая права/photo, replay/version conflict, legacy missing_evidence, запрет неполного закрытия, upgrade/downgrade/metadata roundtrip |
| `alembic upgrade head` и `alembic check` в отдельной demo-БД | PASS, `No new upgrade operations detected` |
| `python -m app.export_openapi`; `npm --prefix apps/web run generate:api` | PASS; добавлены EquipmentDetail/EquipmentOrderView и endpoint, существующие контракты сохранены |
| `npm --prefix apps/web test -- --run` | **92 PASS**, 19 файлов |
| `npm --prefix apps/web run build` | PASS: оба TypeScript проекта, Vite и PWA, 11 precache entries |
| `npm --prefix apps/web run test:e2e -- --workers=2 --retries=0` | **19 PASS**, 24.3 с, без skips; реальные API/PostgreSQL/Nginx, включая истечение сессии, protected photos и workflow |
| `E2E_BASE_URL=https://localhost:5192 npm --prefix apps/web run test:e2e -- equipment.spec.ts --workers=1 --retries=0` | **1 PASS**, 14.1 с; отдельный локальный HTTPS с тестовым сертификатом, QR/оба скачиваемых SVG декодированы независимым jsQR, URL → вход → карточка → история → создание, replay 201/key conflict 409/stale version 409 |
| `python infra/verify_equipment_review.py` на отдельном HTTP/API/БД, без другого consumer | PASS: карточка → создание → исполнение → immutable submission/replay → injected fake provider → обновлённая история. Mock помечен, наряд остаётся AI_REVIEW, платных calls 0 |
| Снимки Playwright 360/390 px и print media | PASS; визуально проверены карточка/печать, горизонтального overflow нет |

Перед повторным полным E2E reset выполнялся только в одноразовой `qosthub_demo_t11`: накопленные прошлые тестовые назначения и IP-throttle мешают воспроизводимому прогону. Предварительные неуспешные запуски выявили ошибки тестовой обвязки (селектор, allowlist тестовой БД, повторный fixture); итоговые команды выше прошли. Проверки native запуска не заменяют Docker runtime или физические телефоны.

Самостоятельное ревью выполнено по требованиям и diff; подагенты не запускались по прямому указанию пользователя. Модели, prompts и правила ИИ не менялись. Численные мобильные замеры и физическое сканирование камерой отложены; проверено независимое декодирование QR и переход браузером.
