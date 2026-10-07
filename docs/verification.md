# T08/T10 — фактическая проверка ветки

Проверено 2026-10-07–08, Asia/Qyzylorda. Основа main `99929ba`; code checkpoint `109b418b2a7ed4936d2936eb3e54d741ac836508`, ветка `codex/t08-t10-integration`. Новые функции ещё не в main.

| Проверка | Команда / фактический результат |
| --- | --- |
| Сервер, настоящий PostgreSQL17 | services/api: `PYTHONUTF8=1 TEST_DATABASE_URL=<qosthub_test> MIGRATION_TEST_DATABASE_URL=<qosthub_migration_test> python -m pytest -q -p no:cacheprovider --tb=short` — **1578 PASS**, 342.82с |
| Frontend | `npm --prefix apps/web run test -- --run` — **79 PASS**, 18 файлов |
| Типы/build/PWA | `npm --prefix apps/web run build` — **PASS**, оба tsc/Vite/service worker, 11 precache entries |
| Настоящий API/PWA/БД | `npm --prefix apps/web run test:e2e -- --workers=2 --retries=0` — **17 PASS**, 21.9с, без skips; real session expiry включена E2E_DATABASE_URL/E2E_PYTHON_PATH |
| Миграции | `python -m alembic upgrade head`, `python -m alembic check` на новой demo БД — **PASS**, полный pytest включает roundtrip |
| Compose overlays | Portable Compose5.6.0: `docker-compose --env-file <disposable-env> -f compose.yaml -f compose.tunnel.yaml config --quiet`, аналогично restore overlay — **PASS**; контейнеры не запускались |
| Настоящий Nginx1.30.5 | `nginx -t` и отдельный localhost echo-backend: другой Host→**421**, forged XFP/XFF/CF/Forwarded/True-Client-IP не проходят — **PASS** |
| Native backup/restore | `pg_dump -Fc`, `pg_restore --exit-on-error` в отдельную qosthub_demo_restored: work_orders/submissions/master_decisions/photos **8/5/4/3 совпадают**, private-photo SHA256 исходной/восстановленной копии соответствует БД |
| HTTPS | Публичная `/health/ready`→ready; cookie **Secure, HttpOnly, SameSite=Lax** |
| Telegram | Существующий бот getMe PASS, username исправлен только в ignored live environment по ответу Telegram; setWebhook configured, фактический URL соответствует PUBLIC_BASE_URL, pending_updates0, delivery_error=false |
| Настоящий ИИ | **gpt-6-luna / accepted / is_mock=false**, один сохранённый вызов учтён **$0.0007711** по консервативной таблице ставок; отдельный persistent budget ≤$2. По новому указанию пользователя платный consumer остановлен 2026-10-08 |
| iPhone | Пользователь подтвердил установленную PWA и вход на обоих iPhone. Полный цикл и численные замеры **отложены пользователем** |
| Материалы | [presentation.pptx](delivery/presentation.pptx): **8 editable slides**, package/layout/font/import validation PASS, все слайды просмотрены. [reserve.webm](delivery/reserve.webm): **17.44с**, настоящая HTTPS/API запись с явно подписанным ранее сохранённым настоящим ИИ-ответом |
| Независимое ревью | T08 server/web и T10 прошли scoped review/fix/re-review; whole-branch `109b418` — **approved**, новых существенных P1/P2 нет |

Среда: Windows/Python3.12.14/Node24.19.0; PostgreSQL в отдельном ignored cluster. Production PWA использовалась с настоящим API/БД; публичный mobile стенд — native Nginx + Cloudflare Quick Tunnel. Docker Desktop/daemon отсутствует. Секреты/PIN/сессии/dump/private images/ledger и provider diagnostics только в ignored .tooling/.env; данные и роли синтетические.

Исправлены: normalized SHA256 фото (actual JPEG+EXIF→AI bytes), отмена медленного отчёта live polling, обрезание linked downtime до создания наряда, видимость чужих Telegram recipients, foreign-assignee404, потеря advisory lock budgeted worker (pinned connection/PID/lock ownership и sticky halt/audit, real terminate_backend regressions), UTF-8 чтение корпуса на Windows и недостаточный Nginx map hash bucket. На native Windows CLI используется PYTHONUTF8=1.

## Оставшаяся приёмка

Android на реальном устройстве; создание ≤60с/≤6 действий, обновление ≤5с, фото ≤10с на измеренной мобильной сети; полный Telegram→PWA→ИИ→мастер на физических телефонах; container startup/recovery и restore-overlay runtime. По последнему указанию мобильные замеры делаются позже. Вход на iPhone не заменяет остальные критерии. Текстовый live ИИ-пример не доказывает производственную точность фотопроверки.

Рейтинг — согласованный Q/T scope; R/V и неподтверждённые корректировки «нет данных», веса нормированы C6. Старые фото с исходным upload-хешем автоматически не переписываются/не обходят integrity. T08/T10 до интеграции REVIEW; T04–T07/T10 не получают DONE без обязательной живой приёмки.
