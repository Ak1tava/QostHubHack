# T18 — язык Telegram RU/KZ

Ветка `codex/t18-telegram-language`, base `4db0ab6`; владелец A / Codex backend agent. Root подготовил контракт/миграцию commit `52021f9`: `TelegramBinding.language`, допустимые `ru`/`kk`, default/server_default `ru`. OpenAPI/TS и интеграцию выполняет root последовательно.

В личном чате связанного активного аккаунта `/language` показывает постоянную клавиатуру RU/KZ. `/ru`, `/kz`, `/kk` и текст RU/KZ/KK сохраняют выбор в PostgreSQL. Первая привязка использует Telegram `language_code` (`kk`/`kk-KZ` → `kk`, прочие → `ru`); повтор `/start <token>` сохраняет ранее выбранный язык. Приветствие/помощь до привязки двуязычны и ведут в PWA. После привязки ответы и подсказка `/language` локализованы.

Пять типов уведомлений, служебные поля и inline-кнопка «Открыть наряд» локализуются по **получателю**, а не по мастеру/отправителю. Названия оборудования/людей/участков и комментарии сохраняются исходными. Telegram остаётся каналом уведомлений; принятие/закрытие выполняются в PWA. Приватность, one-use token, update dedup, user-first lock order и доставка с попытками до I/O сохраняются.

Ответ команды подготовлен внутри транзакции и возвращается после успешного commit как webhook JSON `method=sendMessage` — дополнительного HTTP/consumer нет. Telegram поддерживает этот механизм, но результат доставки такого ответа неизвестен: [официальная документация Bot API](https://core.telegram.org/bots/api#making-requests-when-getting-updates). Поэтому ответ API не выдается за подтверждение доставки в реальном Telegram. `allowed_updates=['message']` сохраняется; callback updates не нужны.

TDD RED: исходная locale suite → **12 failed, 8 passed** (язык/commands/reply отсутствуют), затем **20 passed in 11.48s**. RED уведомлений/кнопки → **7 failed**; до race fix расширенная suite → **105 passed in 54.71s**. Независимое ревью обнаружило конкурентный перенос binding между аккаунтами: дополнительный regression → **1 failed**; исправление проверяет владельца повторно под lock и обновляет User из БД.

Финальная команда из `services/api`, отдельные `qosthub_test_t18_language` / `qosthub_migration_test_t18_language`, без реальных токенов:

```text
python -m pytest tests/test_telegram_language.py tests/test_telegram_linking.py tests/test_telegram_format.py tests/test_telegram_client.py tests/test_telegram_recovery.py tests/test_telegram_review_fixes.py tests/test_deadlines.py tests/test_telegram_delivery_visibility.py -q --tb=short
```

Фактический результат: **106 passed in 55.19s**, exit0. Durable locale проверен новым независимым `Session` после commit; протестированы повтор update, relink/default, group/неверный chat/inactive/неизвестный sender, передача binding другому owner, no-HTTP webhook ответы, маршрутизация RU/KK между двумя получателями и пять типов уведомлений. `git diff --check` → exit0. Root сообщил migration RED `UndefinedColumn`, затем **1 PASS**; этим агентом его результат повторно не заявляется как собственный прогон.

Код: [service](../services/api/app/modules/telegram/service.py), [webhook](../services/api/app/modules/telegram/router.py), [notification worker](../services/api/app/workers/notifications.py), [новые проверки](../services/api/tests/test_telegram_language.py). Требуются миграция/перегенерация контрактов и restart API/notification worker при интеграции. Живых Telegram отправок этим агентом не выполнялось; человеческая проверка казахских терминов остаётся отдельной проверкой.
