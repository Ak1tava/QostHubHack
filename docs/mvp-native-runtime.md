# Native runtime MVP (Windows)

Владелец: Runtime / Codex, `codex/mvp-final-runtime`; интеграцию и живую приёмку выполняет A / Codex. Runtime не скачивает бинарники/модель, не создаёт БД, не запускает миграции/seed и не меняет webhook. Используется существующий локальный PostgreSQL, подготовленная PWA и faster-whisper large-v3-turbo.

## Конфигурация и запуск

Скопировать `infra/native-runtime.example.json` в ignored `.tooling/native-runtime-config.json`, заполнить абсолютные пути. `env_file` указывает на существующий ignored `.env` либо JSON с переменными окружения. Значения секретов в config не помещать; неизвестные поля отклоняются. Нужны `DATABASE_URL` с host `127.0.0.1` и `postgres_port`, `SESSION_SECRET`, `SESSION_COOKIE_SECURE=true`, `PUBLIC_BASE_URL=https://...`, `SPEECH_SERVICE_TOKEN`. Для consumers — прежние OpenAI/Telegram credentials и прежние параметры моделей/токенов.

`manage_postgres=false` оставляет существующий общий PostgreSQL внешним: проверяет readiness, не запускает и не останавливает его. Для отдельного уже инициализированного кластера можно указать `true`; наличие чужого `postmaster.pid` блокирует старт. `state_dir` должен быть отдельным ignored каталогом, доступным только владельцу стенда: там конфигурация без секретов, PID/creation/executable, Nginx config и приватные логи.

Команды из корня проекта (путь `$nativePython` — настроенный Python с API и speech dependencies):

```powershell
$nativePython = 'C:/path/to/existing/venv/Scripts/python.exe'
$nativeConfig = 'C:/path/to/qoshackhub/.tooling/native-runtime-config.json'
& $nativePython infra/native_runtime.py start --config $nativeConfig
& $nativePython infra/native_runtime.py status --config $nativeConfig
& $nativePython infra/native_runtime.py stop --config $nativeConfig
```

Обычный `start` запускает только DB (если managed), ASR, API, Nginx. `--notifications`, `--live-ai`, `--tunnel` включают соответствующие процессы явно. Например, разрешённый живой запуск: `start --config $nativeConfig --notifications --live-ai --tunnel`. Quick Tunnel получает новый hostname из своего свежего лога и передаёт URL API/consumer/Nginx через snapshot config; URL остаётся в `.tooling/native-runtime/runtime.json`. Webhook при смене hostname обновляет интегратор отдельно. Если остаётся внешний существующий tunnel, флаг `--tunnel` не нужен; hostname берётся из env.

Все серверы слушают loopback. Nginx сохраняет точный Host gate и проверенные proxy headers. ASR использует только локальные веса (`model.bin`, `config.json`, `tokenizer.json`), outbound скачивание отключено. Child entrypoint загружает явный env, затем `Settings(_env_file=None)`: `.env` другой ветки не подмешивается. OpenAI key доступен только budgeted reviews, Telegram token — только notification worker, webhook secret — API.

Повторный запуск с той же конфигурацией проверяет уже свои процессы, не создаёт дубликаты. При ошибке readiness убираются только новые процессы. Смена путей/портов требует `stop` → `start`; `stop` использует сохранённые исходные пути. PID проверяется по creation stamp и executable; переиспользованный PID не останавливается. PostgreSQL останавливается `pg_ctl -m fast`, Nginx — `quit`, остальные — по проверенному открытому process handle. Чужие processes никогда не усыновляются; существующие live scripts перед переходом останавливает их владелец. Не применять `taskkill /IM`, удаление pidfile или сброс ledger.

Consumers имеют startup handshake с PID и новым случайным token каждого запуска. Budgeted worker сообщает готовность только после file lock, проверки ledger/frozen, DB lock и проверки владения; notification worker — после успешного первого outbox commit, до Telegram send. `status` до подтверждения возвращает `starting`, а `start` ждёт подтверждения и живого исходного процесса. Старый marker либо вышедший процесс не подтверждает новый запуск; timeout приводит к rollback. Docker entry добавляет API package path явно, не зависит от `PYTHONPATH`/текущего каталога.

Windows venv Python может создавать wrapper и настоящий worker с разными PID. Launcher проверяет direct parent, creation stamps и точный base interpreter из `pyvenv.cfg`, затем сохраняет worker identity и отдельную wrapper identity. Marker должен совпасть с PID настоящего worker. Stop/rollback проверяют и завершают обе identities; переиспользованный wrapper PID не затрагивается. Уже завершающийся wrapper проверяется bounded ожиданием того же открытого handle.

Если managed Quick Tunnel умер, а свои API/Nginx/consumers ещё живы, новый `start --tunnel` отказывает до создания нового tunnel: hostname может измениться, а прежний origin продолжит использовать старый адрес. Такое же правило действует при добавлении managed tunnel к уже работающему origin. Явное восстановление: `stop --config $nativeConfig --keep-db` → `start --config $nativeConfig --tunnel` с нужными consumer flags. Внешний tunnel без `--tunnel` остаётся вне этого правила и не останавливается launcher.

## Mapping существующего стенда

Пути относительно основного checkout `C:/Users/white/Documents/ChatGPT/qoshackhub`:

| Поле | Существующий источник |
| --- | --- |
| `repo` | Интегрированная ветка/checkout с актуальным `apps/web/dist` |
| `env_file` | `.worktrees/t17-t19-integration/.tooling/t17-t19/judge-live/.env` либо `environment.json` |
| `python` | `.worktrees/t13-t16-delivery/services/api/.venv/Scripts/python.exe` |
| `nginx`, `nginx_mime_types` | `.worktrees/t08-t10-integration/.tooling/bin/nginx-1.30.5/{nginx.exe,conf/mime.types}` |
| `cloudflared` | `.worktrees/t08-t10-integration/.tooling/bin/cloudflared.exe` |
| `model_path` | `.worktrees/t13-t16-delivery/.tooling/models/whisper-large-v3-turbo` |
| `photo_path` | `.worktrees/t17-t19-integration/.tooling/t17-t19/judge-live/photos` |
| `ledger` | `.worktrees/t08-t10-integration/.tooling/mobile/budget.json` — именно прежний файл |
| Порты | PostgreSQL `55486`, API `8036`, Nginx `5214`; ASR `8016` только если свободен |

`postgres_bin`/`postgres_data` берутся из действующего portable PostgreSQL, `manage_postgres=false`. Не копировать чужой PID registry и не использовать старый `api.py`: он явно запрещает ASR. В ignored env интегратор добавляет общий `SPEECH_SERVICE_TOKEN`; model/service paths launcher задаёт сам. В текущей реализации ASR readiness проверяет файлы/зависимости; настоящий inference и restart — отдельная живая приёмка.

## Compose и бюджет

Базовый `ai-worker` сохранён для offline/CI, `OPENAI_API_KEY: ""` перекрывает root `.env`. В tunnel overlay он принадлежит отдельному `unbudgeted-ai` profile и исключён из обычного запуска и `live-ai`. Paid `ai-demo-worker` существует только в `live-ai`; named volume для нового бюджета удалён. `LIVE_AI_LEDGER_DIR` должен указывать на прежний каталог с `budget.json`, `frozen.json`, amendment/audit files. Bind `create_host_path:false` не создаёт пустой каталог. Entry отказывается при отсутствии истории, лимите кроме `$10`, exhausted/unresolved/halted budget. Существующие file lock и DB advisory lock бюджетного worker исключают второго платного consumer; автоматически изменять лимит/модели нельзя.

Compose не используется для переноса текущего native live. Для отдельно согласованной Docker-среды сначала остановить native budgeted worker и ранее запущенный ordinary Docker ai-worker; не включать `unbudgeted-ai` одновременно с `live-ai`:

```powershell
docker compose -f compose.yaml -f compose.tunnel.yaml stop ai-worker
docker compose -f compose.yaml -f compose.tunnel.yaml --profile live-ai up --no-deps ai-demo-worker
```

`--no-deps` предполагает уже готовые DB/API/migrations. Сам profile `live-ai` также исключает ordinary worker, но не останавливает его уже запущенный контейнер; поэтому явный `stop` нужен при переключении режима. Не создавать копию ledger для второй действующей среды; restore-копия ниже остаётся offline.

## Offline backup/restore

Это явная процедура для отдельной БД/каталога, без external consumers и webhook. Сначала остановить все writers и consumers контроллером, который ими владеет; для нового launcher — `stop --keep-db`. Проверить отсутствие API/notification/review процессов, при внешнем PG оставить его работающим. После остановки workers все calls в ledger должны быть `settled`; unresolved call требует audit, backup не превращает его в разрешение продолжать платные запросы.

Секрет PostgreSQL задаётся через существующий ignored `PGPASSFILE`; команды не включают пароль/полный URL. Значения ниже — параметры, а не действующие credentials:

```powershell
$pgNativeBin = 'C:/path/to/portable/postgres/bin'
$nativeBackup = 'C:/path/to/ignored/backup-2026-10-08'
$nativePhotos = 'C:/path/to/existing/private/photos'
$nativeBudgetDir = 'C:/path/to/original/mobile'
$nativeDbUser = 'existing_db_user'
$nativeSourceDb = 'qosthub_demo_t18_judges'
$nativeRestoreDb = 'qosthub_restore_20261008'
$nativeRestoreRoot = 'C:/path/to/ignored/offline-restore-2026-10-08'
if (Test-Path -LiteralPath $nativeBackup) { throw 'Backup destination already exists' }
if (Test-Path -LiteralPath $nativeRestoreRoot) { throw 'Restore destination already exists' }
New-Item -ItemType Directory -Path $nativeBackup | Out-Null
& "$pgNativeBin/pg_dump.exe" -h 127.0.0.1 -p 55486 -U $nativeDbUser -d $nativeSourceDb -Fc -f "$nativeBackup/database.dump"
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
Copy-Item -LiteralPath $nativePhotos -Destination "$nativeBackup/photos" -Recurse
New-Item -ItemType Directory -Path "$nativeBackup/budget" | Out-Null
foreach ($budgetFile in @('budget.json','frozen.json','budget.budget-amendment.json','budget.halt.json')) {
  $budgetSource = Join-Path $nativeBudgetDir $budgetFile
  if (Test-Path -LiteralPath $budgetSource) { Copy-Item -LiteralPath $budgetSource -Destination "$nativeBackup/budget/$budgetFile" }
}
& "$pgNativeBin/createdb.exe" -h 127.0.0.1 -p 55486 -U $nativeDbUser $nativeRestoreDb
if ($LASTEXITCODE -ne 0) { throw 'Restore DB must be new' }
& "$pgNativeBin/pg_restore.exe" -h 127.0.0.1 -p 55486 -U $nativeDbUser -d $nativeRestoreDb --no-owner --no-privileges --exit-on-error "$nativeBackup/database.dump"
if ($LASTEXITCODE -ne 0) { throw 'pg_restore failed' }
New-Item -ItemType Directory -Path $nativeRestoreRoot | Out-Null
Copy-Item -LiteralPath "$nativeBackup/photos" -Destination "$nativeRestoreRoot/photos" -Recurse
Copy-Item -LiteralPath "$nativeBackup/budget" -Destination "$nativeRestoreRoot/budget" -Recurse
```

Создать отдельный ignored env для восстановленной БД: новое DB name, restore photo path, `OPENAI_API_KEY=` и `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_WEBHOOK_SECRET=`, отдельный session secret. Не запускать notification/review/tunnel и не назначать production webhook. Для launcher задать отдельные state/ports и restore photo path; `ledger` можно указать на restore copy только для offline хранения, `--live-ai` запрещён процедурой. Модель и portable binaries можно использовать прежние; PostgreSQL внешний. Проверить SQL counts нарядов/пользователей/фото, список и SHA256 приватных фото, SHA256 всех budget/audit JSON до/после копирования. Restore не перезаписывает исходную БД/фото/ledger, не делает rollback расходов и не создаёт второго разрешённого бюджета.

## Проверка без live

`python -m pytest services/api/tests/test_native_runtime.py services/api/tests/test_tunnel_config.py -q` использует fake processes и synthetic env; Windows regression дополнительно запускает скрытый synthetic subprocess через configured Python для проверки venv redirector. БД/сеть/платный ИИ/live при этом не используются. Покрывает idempotence, PID reuse, foreign ports, rollback новых процессов, stop с исходными путями, внешний PG, secret isolation, budget fail-closed, Host gate и Compose mounts/profile exclusion. Полные API/Compose runtime, настоящий ASR inference, isolated restore и HTTPS выполняются интегратором отдельно; создание launcher не означает их прохождение.

Фактическая scoped-проверка 2026-10-08: reusable Python `.worktrees/t13-t16-delivery/services/api/.venv/Scripts/python.exe`, команда выше с `--tb=short -p no:cacheprovider --basetemp=.tooling/runtime-tests-profile-green`: **23 passed**. Parsing/merge двух Compose YAML подтвердил: `live-ai` включает budgeted consumer и исключает ordinary, base сохраняет keyless CI worker. `git diff --check` — exit 0. Docker runtime не запускался; live-процессы/платные вызовы/Telegram не затрагивались.

После reviewer fixes: scoped runtime/tunnel suite — **38 passed**, включая isolated Docker package bootstrap, устаревший marker/PID, frozen mismatch/file lock/DB lock и rollback consumers. Из `services/api` команда `python -m pytest tests/test_native_runtime.py tests/test_tunnel_config.py tests/test_budgeted_worker.py -k 'not amendment and not database_lock_loss and not live_original_session and not closed_original and not lock_loss_after_reservation' -q --tb=short -p no:cacheprovider --basetemp=../../.tooling/runtime-review-regression2` — **50 passed, 12 deselected**. PostgreSQL-only проверки остаются интегратору: в scoped среде `TEST_DATABASE_URL` не настроен.

После managed tunnel recovery fix та же combined-команда с `--basetemp=../../.tooling/runtime-tunnel-green1` — **54 passed, 12 deselected**; дополнительные проверки покрывают отказ до нового hostname, отсутствие побочных эффектов, явное stop/start и безопасную CLI-инструкцию восстановления.

Windows redirector probe подтвердил разные PID: wrapper `17028`, worker `12960`, parent worker — `17028`; synthetic subprocess завершился exit 0. После identity fix combined-команда с `--basetemp=../../.tooling/runtime-redirector-final` — **62 passed, 12 deselected**, включая настоящий скрытый venv subprocess: readiness marker соответствует worker PID, stop завершает worker и wrapper; fake проверки отвергают чужого/старого child и переиспользованный wrapper PID. Probe/test не использовали БД, сеть, credentials и live-процессы.
