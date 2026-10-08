# T16: локальный Whisper для русского и казахского

Реализация на ветке `codex/t13-t16-delivery`, база `main 3af3261`. Backend: `services/api/app/modules/speech/`; клиент: `apps/web/src/features/speech/`. Интеграция/публичные статусы определяются `plans.md`.

Голос создаёт редактируемый черновик для описания нового наряда мастером и выполненных работ исполнителем. Пользователь отдельно вставляет текст в форму. Распознавание не отправляет форму, не сохраняет наряд и не меняет его статус.

## Контракт и ограничения

`POST /api/v1/speech/transcriptions`: multipart `file`, `language=ru|kk`; действующая cookie-session и `Origin`/`X-CSRF-Token`. Разрешены только активные `master` и `worker`. Ответ `SpeechTranscription`: `text`, `language`, `model="large-v3-turbo"`, `duration_seconds`, `is_mock`. Fake допускается только через тестовую подмену зависимости; production inference возвращает `is_mock=false`.

Сервер принимает максимум **10 MiB и 60 секунд**. Поддержаны `audio/webm`, `audio/mp4`, `audio/x-m4a`, `audio/mpeg`, `audio/wav`, `audio/x-wav`, `audio/ogg`, включая MIME с codec-параметрами. PyAV проверяет настоящий контейнер, наличие аудио и декодированную длительность; неподдержанный контейнер/видео отклоняется. Проверка останавливается при первом превышении 60 секунд. Пустой файл/речь и повреждённое аудио дают ошибку. Передаваемые пути и URL не используются; FFmpeg запрещены внешние файловые/сетевые протоколы.

Ошибки в существующем `ErrorResponse`: `401` вход, `403` роль/CSRF, `413` размер, `415` формат/несоответствие контейнера, `422` язык/пустое/повреждённое/длинное аудио/отсутствие речи, `429` занятый inference, `503` отсутствие модели/настройки/сервиса, timeout или ошибка ASR. Ответы имеют `Cache-Control: no-store`; внутренние пути, Bearer-токен и исключения пользователю не раскрываются. HTTP timeout — 90 секунд, автоматических повторов и redirect нет.

Внутренний отдельный процесс: `POST /transcribe` с теми же multipart-полями и Bearer; `GET /health/ready`. Readiness проверяет непустой токен, локальные `model.bin/config.json/tokenizer.json` и наличие faster-whisper. Загрузка весов остаётся ленивой: readiness не обещает корректность содержимого файлов; ошибка загрузки на первом inference безопасно возвращает 503. Обязательный `tokenizer.json` предотвращает сетевой fallback tokenizer в faster-whisper 1.2.1.

Одновременно работает один inference; второй получает 429 без очереди. Блокировкой владеет рабочий поток: отмена HTTP-coroutine не освобождает её до завершения модели. Публичный API и внутренний сервис независимо ограниченно декодируют аудио. UploadFile закрывается при успехе, ошибке и отмене; аудио не пишется в БД/историю/постоянные файлы приложения и не логируется. Небольшой временный файл multipart принадлежит lifecycle загрузки и удаляется при закрытии. Reverse proxy ограничивает весь request body до multipart overhead сверх допустимого аудио, поскольку multipart разбирается до вызова handler.

## Подготовка модели

Модель: `mobiuslabsgmbh/faster-whisper-large-v3-turbo`, **revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`**. Revision передаётся CLI в `snapshot_download`, поэтому повторная подготовка не следует изменяемому `main` репозитория модели. Подтверждённый скачанный `model.bin`: **1 617 884 929 байт**, SHA256 **`e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`**.

Из `services/api`:

```text
uv sync --locked --no-dev --extra speech
uv run --no-sync python -m app.modules.speech.prepare_model --output <absolute-model-directory>
```

CLI — отдельная явно запускаемая подготовка, требующая сети для первого скачивания. Requests модели ничего не скачивают (`local_files_only=True` плюс проверка tokenizer). Модель/аудио находятся в ignored-каталогах и не входят в Git. На Windows `PYTHONUTF8=1` обеспечивает вывод русского CLI help.

Для проверки Windows-файла:

```powershell
(Get-Item '<absolute-model-directory>/model.bin').Length
(Get-FileHash '<absolute-model-directory>/model.bin' -Algorithm SHA256).Hash
```

## Native и Compose

Общие настройки перечислены в `.env.example`:

| Настройка | API / ASR |
| --- | --- |
| `SPEECH_SERVICE_URL` | API: `http://127.0.0.1:8016` native; `http://speech:8016` Compose |
| `SPEECH_SERVICE_TOKEN` | Одинаковый случайный внутренний токен у API и ASR; только ignored environment |
| `SPEECH_REQUEST_TIMEOUT_SECONDS` | API: `90` |
| `SPEECH_MODEL_PATH` | ASR: абсолютный локальный каталог; Compose `/models` |
| `SPEECH_DEVICE` / `SPEECH_COMPUTE_TYPE` | ASR: `cpu` / `int8` |
| `SPEECH_MODEL_DIR` | Compose: каталог модели на хосте, монтируется read-only |

Native ASR из `services/api`, с заранее заданными environment:

```text
uv run --no-sync uvicorn app.modules.speech.internal:app --host 127.0.0.1 --port 8016 --no-access-log
```

Один процесс/worker сохраняет гарантию одного inference. ASR запускается отдельно от обычного `app.main:app`; без настройки речи остальное приложение продолжает работать, а transcription недоступна с 503. Native ASR слушает loopback.

Compose после заполнения ignored environment и подготовки модели:

```text
docker compose -f compose.yaml -f compose.speech.yaml up -d --build
```

`infra/speech.Dockerfile` устанавливает locked optional extra `speech`. В Compose веса read-only, `/tmp` — ограниченный tmpfs, контейнер работает без root, порт 8016 не публикуется на хост. У API/ASR совпадает Bearer; стандартный профиль CPU/int8. CUDA не требуется для принятого native smoke и не проверена как способ production-запуска.

## Фактические проверки 2026-10-08

Последняя целевая backend-проверка: **48 PASS, 6,83 с**. Runtime `services/api/.venv` (Python 3.12.14), отдельная PostgreSQL `qosthub_test_t16_20261008` на loopback-порту 55460. Команда из корня worktree:

```text
services/api/.venv/Scripts/python.exe -m pytest services/api/tests/test_speech.py services/api/tests/test_speech_internal.py -q --tb=short -p no:cacheprovider
```

Environment: `PYTHONUTF8=1`, `TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55460/qosthub_test_t16_20261008`. Это выделенная временная тестовая БД, не настройка production.

Проверены реальные session/login/CSRF/Origin и роли; ошибки и контракт; настоящее WAV/WEBM-Opus/OGG-Opus/MP3/MP4-AAC декодирование, MIME spoofing, размер и границы длительности; закрытие upload/отмена; HTTP timeout и отсутствие retry; internal auth/readiness; локальная модель/ленивые segments/cache; конкурентные потоки и отмена во время inference; HTTP provider→internal ASGI roundtrip. Открытый HLS-текст под видом аудио не обращается к локальному HTTP listener. Начальные RED и дополнительные RED→GREEN для отсутствующего tokenizer, ErrorResponse, readiness и фиксированной model revision сохранены в ignored `.tooling/t13-t16/backend-*.log`. Отдельный расширенный запуск speech + существующий `test_authz.py`: **90 PASS, 42,00 с**, до последних readiness/pinned-CLI проверок; после них и двух AAC-регрессий повторены все 48 speech-тестов. AAC boundary: реальный fragmented MP4/AAC mono48k с входными 59 секундами принят; 60 секунд плюс decoder padding отклоняются серверным лимитом 60 секунд. Каждый encoded fixture меньше 100 KB; evidence — `.tooling/t13-t16/backend-aac-suite.log`. Полный интеграционный прогон фиксируется отдельно в `docs/T13-T16-verification.md`.

### Настоящий CPU int8 inference

Отдельный процесс загрузил локальные веса; SHA256 двух fixtures сверены с manifest до распознавания. Холодная загрузка модели в новом процессе — **3,000 с** (это не измерение после очистки дискового кэша ОС). Реальный `LocalWhisperService`, без fake модели, сети для модели или платных API:

| Язык / fixture | Эталон из открытого источника | Реальный text | Decoded duration | Inference wall time |
| --- | --- | --- | --- | --- |
| RU / `ru.wav` | Добрый день | **Добрый день!** | 1,3946875 с | 5,968 с |
| KK / `kk.ogg` | Қазақстан Республикасы | **Қазақстан Республикасы** | 1,8779375 с | 6,018 с |

Оба ответа: `model="large-v3-turbo"`, `language` выбранного fixture, **`is_mock=false`**. Небольшое различие source duration/decoded duration связано с приведением к 16 kHz. Exit code процесса — 0. Воспроизведение из корня: `services/api/.venv/Scripts/python.exe .tooling/t13-t16/smoke_whisper.py` при `PYTHONUTF8=1`. Ignored evidence: `.tooling/t13-t16/whisper-real-smoke.json`, `.log`, `speech-fixtures/manifest.json` и source metadata. Audio fixtures не коммитились.

### Публичный маршрут и настоящий HTTP ASR

Дополнительно выполнен публичный `POST /api/v1/speech/transcriptions` через FastAPI TestClient с настоящим login/session/CSRF и собственной PostgreSQL. API использовал обычный `HttpSpeechProvider` и настоящий HTTP к отдельному uvicorn ASR на loopback 8018; модель CPU/int8, без fake-provider или fake-model.

| Актор / язык | HTTP | Реальный text | Duration | Public request wall time |
| --- | --- | --- | --- | --- |
| master / RU | 200 | Добрый день! | 1,3946875 с | 8,375 с |
| worker / KK | 200 | Қазақстан Республикасы | 1,8779375 с | 5,297 с |

Оба ответа `model="large-v3-turbo"`, `is_mock=false`, `Cache-Control: no-store`. Первый публичный запрос включает ленивую загрузку модели; второй переиспользует её. Pytest — **2 PASS, 15,78 с**, exit 0. Единственное предупреждение `PytestAssertRewriteWarning(anyio)` относится к bootstrap отдельного ignored pytest-script, импортирующего fixtures перед запуском pytest; на ASR-результат не влияет. ASR subprocess остановлен в `finally` (`isolated_asr_stopped=True`), остальные локальные сервисы не затрагивались. Evidence содержит только статусы, роли, язык, текст, длительность, время и fixture hashes — без токенов и аудио.

Воспроизведение: `services/api/.venv/Scripts/python.exe .tooling/t13-t16/run_public_whisper_smoke.py` при `PYTHONUTF8=1`. Ignored файлы: `run_public_whisper_smoke.py`, `test_public_whisper_smoke.py`, `whisper-public-http-smoke.json`, `.log`. Script запускает и останавливает отдельный ASR; тест использует только `qosthub_test_t16_20261008`.

### Источники тестовой речи

RU: [«добрый день», Wikimedia Commons / Lingua Libre](https://commons.wikimedia.org/wiki/File:LL-Q7737_(rus)-Tatiana_Kerbush-%D0%B4%D0%BE%D0%B1%D1%80%D1%8B%D0%B9_%D0%B4%D0%B5%D0%BD%D1%8C.wav), speaker/recorder **Tatiana Kerbush**, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0). KK: [«Қазақстан Республикасы», Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Kk-republic-of-kazakhstan.ogg), **Esetok**, носитель из Актюбинской области, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0). Для smoke использованы оригиналы без конвертации/обрезки; transient resampling выполняет decoder. Исходные страницы, лицензии, авторы, хеши и размеры сохранены в manifest.

## Оставшаяся приёмка

Два коротких произношения подтверждают загрузку реальной модели и работу RU/KK. Они не измеряют точность производственных терминов, шум цеха, смешанную речь, длинные записи или end-to-end latency 60-секундного аудио. Интерфейс сохраняет возможность редактирования и ручного ввода; 90-секундный timeout не является обещанием скорости на любом CPU.

Нужно отдельно проверить физические Safari/Chrome, разрешения микрофона, фактические recorder-codecs, HTTPS и мобильную сеть; автоматическое реальное container decode не заменяет телефонную приёмку. Публичный smoke подтверждает session/CSRF и HTTP к настоящему ASR через TestClient; внешний browser/reverse-proxy путь этим запуском не проверялся. Реальные container/profile настройки Compose требуют фактического запуска Docker и не подтверждаются этим native smoke. Итоговая интеграция/frontend/E2E и общий статус — `docs/T13-T16-verification.md` и `plans.md`.
