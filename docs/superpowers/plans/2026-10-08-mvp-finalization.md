# Завершение MVP НарядAI

Пользователь утвердил реализацию 2026-10-08. Владелец интеграции: A / Codex; ветка `codex/mvp-finalization`, база `ad034bf`.

## Обязательный результат

- Только русский ASR: существующий multipart endpoint принимает `ru`, отклоняет `kk` кодом `speech_invalid_language`; UI остаётся RU/KZ. Локальный Whisper large-v3-turbo, лимиты 60с/10MiB, явная вставка редактируемого текста.
- Сохранить обязательные фото до/после и живую фотопроверку. Три подготовленных синтетических сценария проходят server rules/lifecycle, имеют `is_mock=true` и явную подпись. Новые submissions не получают fixtures, закрывает мастер.
- Подключить ASR к текущему native HTTPS-стенду. Воспроизводимый запуск/остановка/проверка; обычный Compose worker без OpenAI key; paid consumer использует прежний ledger и общий потолок $10.
- Backup/restore в изолированную среду без внешних consumers; сохранить БД, приватные фото и бюджетную историю.
- RU/KZ review, актуальные инструкции судей, презентация до10слайдов и резервное видео до3минут.
- Полные API/Vitest/types/build/contracts/E2E, независимое ревью, интеграция в main/CI и deployment с сохранением данных.

## Владение и последовательность

1. Speech agent: modules/speech, speech tests, SpeechInput/locale tests/appMessages, speech E2E и fake ASR. Не редактирует generated contracts/plans.md.
2. Demo agent: judge demo/fixtures/tests и ReviewPanel; новые строки переводов сообщает интегратору. Не редактирует appMessages/plans.md.
3. Runtime agent: compose/infra launcher/tests; без live изменений и секретов. Не редактирует plans.md.
4. Integrator: contracts, документация, UI review, материалы, isolated validation, live deployment, backup/restore, main/CI. Ревью каждой ветки и итоговое независимое ревью.

## Ограничения

Мобильная приёмка/численные замеры отложены. Дообучение, сбор и разметка нового benchmark, VPS не входят. Реестр50 сохраняется как заготовка; использованный holdout не повторяется. Секреты/персональные данные не коммитятся. Никаких новых бюджетов или сброса ledger. Публичные статусы обновляются по интегрированной ветке; невыполненные проверки не объявляются пройденными.

## Проверки поведения

- RU ASR при UI RU/KZ, kk422 до provider, отмена/ошибки/сохранение черновика, настоящий RU inference и restart.
- Три ожидаемых demo-вердикта после guards, уникальные фото, is_mock в API/UI, повтор setup сохраняет пользовательские действия; реальные новые jobs остаются реальными.
- Default Compose не получает ключ; единственный budgeted consumer; restart/exhausted/unresolved budget fail-closed.
- Сохранность БД/фото/ledger после изолированного restore и обновления live; один новый paid AI сценарий в прежнем бюджете.
