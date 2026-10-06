# T06 — независимое финальное ревью

Дата: 2026-10-05. Проверены staged изменения относительно `7bc2b3ac4eace725ddf8bf6288d820041249474b`, ветка `feat/T06-telegram`; HEAD на момент проверки — база, итоговый коммит ещё не создан. Прочитаны review-focus, review-package, C4/T06, AGENTS, brief, implementation report и progress; реализация сверена с текущими файлами. Применён `requesting-code-review/code-reviewer.md`: соответствие спецификации и качество проверены вместе.

Проверка read-only: тесты не запускались, чтобы не конфликтовать с полной проверкой контроллера и её destructive PostgreSQL fixtures. Изменён только этот отчёт. Приведённые ниже сценарии — выводы из кода, а не заявленные результаты выполненных регрессионных тестов. Отчёт реализации содержит результаты focused tests, migration roundtrip и smoke; итог полного pytest на момент ревью ещё не получен.

## Strengths

- Одноразовые случайные токены хранятся хешированными; владелец блокируется перед токеном, receipt update_id и привязка коммитятся атомарно. Проверяются private chat, положительные числовые идентификаторы, соответствие sender/chat, активность пользователя; есть CSRF, rate limit и unlink.
- События T03 не теряют `published_at`: добавлены отдельные receipts. Ключи доставки включают назначение и получателя; попытки сохраняются до HTTP, claim использует SKIP LOCKED, подтверждение — fencing token. PENDING/RETRY/BLOCKED при смене приоритета учитываются отдельно, retry_after сохраняется.
- В отправке правильно сняты DB locks до сетевого запроса. NO KEY UPDATE на получателе совместим с настоящим T03 actor-FK KEY SHARE; порядок order → job → recipient согласован с командами наряда. `_prepare` обновляет сущности после блокировок и сверяет время; старое завершение после reclaim не подтверждается.
- Перед отправкой проверяются назначение, статус, текущий ответственный, активность и доступ; в Telegram не отправляются описания/фото. HTTP redirects отключены, ответы и webhook ограничены размером, внешние ошибки переведены в безопасные коды. Status endpoint ограничен доступом к конкретному наряду и не выдаёт Telegram IDs, токены или lease token.
- Миграция 0003 соответствует моделям; optional configuration не добавляет сетевых действий при импорте. Worker использует существующий production API image и ждёт миграции. Документация явно оставляет live Telegram/T04 проверку BLOCKED.

## Issues

### Critical (Must Fix)

Не обнаружено.

### Important (Should Fix)

1. **[P1] Планировщик может необратимо отменить задания текущего назначения из-за старого ORM-объекта.**

   Файл: `services/api/app/workers/notifications.py:104` (также 113–116, 158).

   `process_outbox` сначала загружает WorkOrder через `db.get`, затем `schedule_notifications` выполняет SELECT FOR UPDATE без `populate_existing=True`. SQLAlchemy не заменяет уже загруженные значения сущности свежими значениями такого запроса. Если между чтением и блокировкой другой процесс переназначил наряд, планировщик продолжает работать со старым assignment_version/status/recipient. Особенно опасен сценарий двух планировщиков: A прочитал assignment 1; B провёл/увидел переназначение и создал jobs assignment 2; A получил lock, но оставил assignment 1 в identity map, после чего `_fresh` отменяет все jobs assignment 2. Повторный outbox проход не восстанавливает CANCELLED dedup keys, и действующий исполнитель/мастер теряют уведомления нового назначения.

   Исправление: получать актуальное состояние под блокировкой с refresh/populate_existing, учитывая контракт flush-only и допустимые локальные изменения caller. Добавить регрессию с двумя независимыми Session: preloaded old order → committed reassignment/current jobs → scheduling через старую Session; все свежие jobs должны остаться действующими. Отдельно проверить pending local changes с используемым в приложении `autoflush=False`.

2. **[P1] Синхронная транзакция webhook блокирует event loop всего API-процесса.**

   Файл: `services/api/app/modules/telegram/router.py:122` (async route начинается на 103).

   После асинхронного чтения тела прямо в event loop вызываются synchronous SQLAlchemy `handle_update` и `commit`. Они могут ждать row locks пользователя/токена, уникального update_id, advisory lock Telegram identity или ответа PostgreSQL. Пока такой запрос ждёт, однопроцессный production Uvicorn не может обслуживать остальные запросы, включая PWA и health endpoints. Это относится и к обычной конкурентной привязке, а не только к отказу Telegram. Освобождение worker locks перед HTTP этот путь не исправляет.

   Исправление: оставить bounded body read асинхронным, а весь sync DB unit of work передать в threadpool с корректным владением Session, либо использовать полноценную async DB сессию. Регрессия: удерживать отдельной транзакцией нужный lock, начать webhook и убедиться, что параллельный `/health/live` и обычный API-запрос отвечают до освобождения lock.

3. **[P2] Ошибки БД из webhook могут раскрывать Telegram ID в серверных traceback.**

   Файл: `services/api/app/modules/telegram/router.py:122`; чувствительные параметры формируются в `services/api/app/modules/telegram/service.py:137` и 147–153.

   `handle_update`/`commit` не перехватывают SQLAlchemy/DBAPI errors. У приложения зарегистрированы только AuthError и validation handlers; Uvicorn запишет необработанное исключение. SQLAlchemy обычно включает SQL и bound parameters: при обрыве соединения/таймауте advisory lock или INSERT binding это числовой Telegram user/chat ID. Worker намеренно подавляет raw exceptions, однако новый webhook таким же барьером не защищён. Это противоречит явному требованию brief о безопасных DB error codes и отсутствии Telegram IDs в логах.

   Исправление: rollback и безопасный retryable ответ (например, 503 со стабильным кодом) на DB failure в Telegram HTTP unit of work; не логировать исходное исключение/цепочку/параметры. Не фиксировать receipt при неудачной привязке, чтобы повтор Telegram мог завершить её. Регрессия должна подставить DBAPI/SQLAlchemy failure с synthetic ID в параметрах и проверить response/logs, rollback и последующее успешное повторение.

4. **[P2] Сообщение не различает новый наряд, непринятие, аварийную очередь и просрочку.**

   Файл: `services/api/app/workers/notifications.py:231`.

   Для каждого kind собирается ровно один и тот же текст: номер, priority, due_at. Мастер не может понять, является сообщение эскалацией непринятия либо уведомлением «аварийный наряд в очереди»; исполнитель получает неотличимые новый наряд и напоминание. Для просрочки это можно пытаться вывести из часов, для emergency_queued — нельзя. Хранение kind в status endpoint не делает причину видимой в самом Telegram. Требование отдельной видимости аварийной очереди и практический смысл эскалации остаются неполными.

   Исправление: добавить короткую статическую безопасную подпись причины по kind («Не принят», «Аварийный наряд в очереди», «Срок истёк», «До срока 30 минут», «Новый наряд»), сохранив запрет на описание, личные данные и action tokens. Это уточнение буквального ограничения C4 «только номер, приоритет, срок» следует зафиксировать как разрешённую служебную подпись, а не добавление деталей наряда. Проверить отличимые тексты всех видов и отсутствие чувствительных полей.

### Minor (Nice to Have)

1. **[P3] Нет видимого признака остановившегося/застрявшего worker.**

   Файл: `services/api/app/workers/main.py:30`; `compose.yaml:56`.

   Для общих исключений сохраняется единственная строка `notification_worker_iteration_failed`; успешные итерации, возраст необработанного outbox, последний прогресс и количество просроченных jobs не наблюдаются. API delivery status полезен для уже созданных jobs, но пустой список при неработающем consumer выглядит так же, как отсутствие уведомлений. Compose restart помогает лишь при завершении процесса, тогда как exception loop продолжает жить. Для MVP это не отдельный blocker, но оператору полезны безопасные счётчики/heartbeat и короткий runbook проверки возраста pending jobs/outbox. Не добавлять в диагностику raw payloads, chat IDs или секреты.

## Проверенные классы отказов и границы вывода

- Concurrent duplicate update/token, разные app users на одну Telegram identity: порядок owner/token и advisory lock плюс unique constraints выглядят корректными; уже существующие тесты проверяют дубликат update и разные update IDs одного токена. Отдельная регрессия двух app users на один Telegram account усилит доказательство; нового подтверждённого дефекта здесь не найдено.
- Expired/reused/private mismatch/inactive identity: проверки присутствуют. Token expiry использует переданный now; текущее HTTP время захватывается до DB wait. Это согласовано с бизнес-интерфейсом управляемого времени; длительные ожидания следует ограничивать на уровне DB/HTTP.
- Конкурентные scheduler/outbox claims: rows берутся SKIP LOCKED, receipts коммитятся с jobs. Несколько заказов в двух batch могут приводить к обычным PostgreSQL deadlocks при разном порядке; rollback/retry worker сохраняет работу. Подтверждённый риск потери — Important 1.
- Lease expiry, stale finish, crash/network attempts: fencing и persisted attempt budget присутствуют; подтверждение использует явное now. Проверки lease после ожидания preparation locks есть. Абсолютная атомарность времени DB commit и внешнего send не обеспечивается и не заявлена.
- Accepted/QUEUED/rejected/cancelled/reassigned, текущий assignment timestamp, priority PENDING/RETRY/BLOCKED, sent dedup: соответствующая логика есть; `_prepare` дополнительно корректирует current priority для уже взятого задания. Просрочка строго после due_at, создание уже прошедшего reminder пропускается, retry reminder после срока отменяется.
- Permission/unlink/brigade changes: свежая проверка есть; после освобождения locks возможно изменение до завершения внешнего send — описанная в report граница. Нет требования удерживать API locks через сеть.
- HTTP 200 ok:false 403/429, timeout/5xx, redirects, malformed/oversized payloads: код содержит безопасные ветви и ограниченный retry budget. Invalid response считается terminal; это явное поведение, а не бесконечный retry.
- Status privacy/authz, additive OpenAPI, optional config/import, migrations и worker image wiring: видимых несовместимых изменений не найдено. Generated contracts просмотрены по новым путям/схемам; generator/build evidence взято из отчёта контроллера, не воспроизведено этим ревью.

## Recommendations

Исправить четыре Important и добавить направленные регрессии к ним. Контроллеру последовательно повторить необходимые PostgreSQL/HTTP проверки, затем финальный suite на окончательном состоянии. После подтверждения обновить только T06 registry/evidence и создать запрошенный коммит. Не объявлять DONE до требуемой интеграции и отдельно отмеченной живой проверки.

## Declined to judge

- Настоящая доставка Telegram, BotFather/webhook на публичном HTTPS и проверка двух телефонов — у пользователя нет бота/токена, внешняя проверка явно BLOCKED.
- Авторизованная PWA-карточка по deep link и визуальный мастерский status UI — экран T04 отсутствует и frontend не входит в T06; оценена только серверная ссылка/контракт и честность документации.
- Реальный запуск свежего Docker image/Compose — Docker локально недоступен; проверены wiring и переданные YAML/native smoke evidence, container execution не заявлено.
- Интеграция отдельной T09 ветки и работа T05/T07 — вне T06; новые уведомления не требуют их включения в этот PR.
- Абсолютная exactly-once доставка, отзыв уже начавшегося внешнего send, гарантия звука/прочтения на телефоне — исключены C4 и явно описанным решением об освобождении locks перед HTTP.
- Абсолютный end-to-end HTTP deadline при непрерывно trickling response — report честно указывает socket timeout/lease ambiguity; не переопределяю согласованное ограничение как скрытую гарантию. Более строгий deadline полезен отдельным улучшением.
- Итог полного pytest, свежий commit SHA и интеграция ветки — контроллер ещё выполняет финальную проверку; отчёт не заменяет фактический результат.

## Assessment

**Spec compliance:** основная серверная функциональность C4/T06 реализована; отдельная видимость причин сообщений неполна, а гонка scheduler нарушает надёжность доставки. Внешние блокировки описаны честно.

**Quality verdict / Ready to merge:** **With fixes**. До устранения Important 1–4 качество не проходит финальный gate: возможны потеря актуальных jobs, остановка API event loop и утечка идентификаторов в DB exception logs. Critical: 0; Important: 4; Minor: 1. Живая проверка остаётся BLOCKED независимо от исправлений и результатов локальных тестов.

## Решения контроллера

Все четыре Important приняты к исправлению одной волной с направленными регрессиями. Статические подписи причин разрешены как служебная часть уведомления без новых персональных данных или описания наряда. Minor о heartbeat/метриках worker отложен как операционное улучшение: штатные статусы доступны, отдельная система наблюдаемости не входит в текущую T06. Цена отсрочки — оператору сложнее различать остановку consumer и отсутствие новых событий.

Итог исправлений и повторного ревью будет записан после проверки окончательного дерева.

# T06 — scoped re-review четырёх Important

Дата: 2026-10-05. Это единственное ограниченное повторное ревью исправлений к `final-review.md`, не повтор полного ревью ветки. Проверены unstaged diff `services/api/app/modules/telegram/router.py`, `services/api/app/workers/notifications.py` и новый `services/api/tests/test_telegram_review_fixes.py` (точное имя найдено через rg --files). Финальное чтение включало форматирование, актуальное время для HTTP link-token fixture и bounded waits.

Тесты не запускались: PostgreSQL предоставлен fix-agent для исключительного использования. Product, index, HEAD и branch не изменялись; создан только этот отчёт. Контроллер добавляет фактические focused/full test results. Сообщённый результат исходной полной проверки — 1207 PASS и 1 Windows ConnectionAborted/10053 в локальном redirect fixture; это не результат повторного запуска данным reviewer и не доказательство GREEN окончательного состояния.

## Проверка исправлений

### Important 1 / P1 — stale ORM-состояние планировщика: устранено

`services/api/app/workers/notifications.py:113` выполняет `db.flush()` до блокирующего чтения, а строка 118 добавляет `populate_existing=True` к SELECT FOR UPDATE.

Чистая предварительно загруженная сущность теперь получает актуальные assignment_version/status/recipient из защищённой строки. Таким образом, старое assignment 1 не отменяет jobs уже записанного assignment 2. При `autoflush=False` явный flush сохраняет допустимые изменения caller до принудительного refresh; иначе refresh мог бы молча затереть их. Flush не коммитит транзакцию, контракт caller-commits сохранён.

Регрессии покрывают оба различающихся сценария: две независимые Session с предварительно загруженной старой версией и уже запланированным новым назначением; локальное изменение priority/status при отключённом autoflush. Проверяются действующие jobs нового назначения и emergency_queued после локальных изменений.

### Important 2 / P1 — блокировка event loop webhook: устранено

`services/api/app/modules/telegram/router.py:140` ожидает `run_in_threadpool(_webhook_transaction, db, payload)`. Bounded stream parsing остаётся асинхронным, вся synchronous DB работа — handle_update, commit, обработка ошибки/rollback — выполняется внутри одного синхронного unit of work.

Request Session создаётся существующей sync dependency; её может обслуживать другой поток пула, однако одновременного использования нет: route передаёт Session и ожидает завершение, event loop не делает с ней DB операций. Dependency finalizer выполняется после возврата unit of work. Последовательное владение Session сохранено; новая shared/global Session не вводится. Такой способ совместим с используемым synchronous psycopg, не требует новой async DB архитектуры.

Регрессия удерживает настоящий User row lock отдельной Session/нитью и выполняет webhook через ASGI AsyncClient. До освобождения lock проверяются `/health/live` и обычный `/telegram/status` (ожидаемый 401 без сессии). Ожидание входа в service и завершения webhook ограничено timeout; holder также имеет ограниченное ожидание и освобождается в finally. Тест отличает старую блокировку event loop от исправленного поведения.

### Important 3 / P2 — DB exception privacy: устранено в проверяемом webhook пути

`services/api/app/modules/telegram/router.py:104` вводит `_webhook_transaction`; SQLAlchemyError из handle/commit перехватывается, выполняется rollback, затем возвращается AuthError 503 с безопасным кодом `telegram_unavailable`. `raise ... from None` подавляет вывод исходной цепочки. Даже SQLAlchemyError самого rollback не превращается в raw exception данного helper. Код не логирует SQL, параметры, исходный exception или Telegram identity.

Регрессии подставляют OperationalError с синтетическим приватным параметром отдельно на handle и commit, проверяют безопасный response/log output, отсутствие binding/update receipt после rollback и успешное повторение того же webhook после восстановления. Дополнительный unit test проверяет 503 и suppressed exception context при ошибке rollback. HTTP token fixture теперь использует актуальное время, поэтому retry проверяет реальную привязку, а не заранее истёкший токен.

### Important 4 / P2 — неразличимые причины сообщений: устранено

`services/api/app/workers/notifications.py:26` содержит пять статических KIND_LABELS; строка 244 добавляет подпись к прежним номеру, priority и due_at. Emergency queue, nonacceptance, overdue, reminder и new теперь различимы в самом Telegram.

Подписи не берутся из свободного пользовательского текста и не добавляют описания наряда, имена, chat IDs, токены или действия изменения состояния. Контроллер явно принял их как служебные подписи C4. Параметризованная регрессия проверяет точный разрешённый состав сообщения для всех пяти kinds и одну реальную отправку через внешнюю test transport boundary.

## Findings

- Critical: **0** новых/оставшихся в проверяемых исправлениях.
- Important: **0** новых/оставшихся в проверяемых исправлениях; исходные **4 закрыты по анализу кода**.
- Minor: **0** новых. Исходный P3 heartbeat/worker operability контроллер осознанно отложил в ops; это не повторный blocker.

## Declined to judge

- Повторная оценка всей T06 ветки — вне явно ограниченного re-review; исходный полный отчёт сохраняется как история проверки.
- Фактический GREEN focused/full suite на финальных файлах — запускают fix-agent/контроллер, этот reviewer тесты не запускал.
- Windows redirect fixture и ConnectionAborted/10053 — исследуются fix-agent отдельно; redirect transport не относится к четырём проверяемым production исправлениям.
- Live Telegram, bot/webhook/два телефона — бота нет, проверка остаётся BLOCKED.
- T04 PWA-card и реальный Docker execution — прежние внешние ограничения не изменились; новым кодом их готовность не подтверждается.
- Отложенный worker heartbeat — принятое контроллером ops улучшение, не основание расширять этот diff.

## Assessment

**Scoped code/spec verdict: PASS.** Четыре Important адресованы непосредственно, целевые регрессии соответствуют причинам дефектов; новых оснований для product изменений в проверяемом scope не найдено.

**Ready for the next gate:** да, для окончательной верификации контроллером. Это заключение не заменяет фактическое успешное выполнение окончательных тестов и не снимает BLOCKED живой интеграции. Дополнительное design approval или новое полное ревью для этих исправлений не требуется.

## Проверка волны исправлений

# T06 — исправления четырёх Important

Исполнитель: t06_fixes. Ветка feat/T06-telegram, без commit/push. Изменены только router.py, notifications.py, test_telegram_client.py и новый test_telegram_review_fixes.py. Frontend/contracts/plans/docs/Compose не изменены. Применены systematic-debugging, TDD, executing-plans и verification-before-completion.

## Причины и исправления

1. SQLAlchemy identity map сохраняла предварительно загруженный assignment, несмотря на последующий SELECT FOR UPDATE. Добавлен populate_existing после lock. Предварительный db.flush сохраняет локальные изменения caller при production autoflush=False; refresh не затирает их.
2. Async webhook вызывал sync handle_update/commit непосредственно в event loop. Полный DB unit of work передан run_in_threadpool; body всё ещё читается асинхронно, предел 64KiB сохранён. Session используется последовательно, не одновременно из нескольких threads. В regression удерживается реальная User row lock, health и обычный unauthenticated API GET должны ответить до снятия lock.
3. SQLAlchemyError в handle_update/commit перехватывается в том же UOW: rollback, безопасный AuthError503 telegram_unavailable from None. Даже SQLAlchemyError при rollback подавляется, raw exception не логируется. Тесты проверяют handle и commit failures, отсутствие binding/receipt после rollback, отсутствие synthetic marker в response/caplog и успешный повтор того же update/token; отдельный unit test проверяет suppress_context при ошибке rollback.
4. Все5 kinds получили статические русские подписи: Новый наряд / До срока30минут / Наряд не принят / Срок истёк / Аварийный наряд в очереди. Остальная строка содержит только number/priority/due; новый private field не добавлен. Полное равенство сообщения проверено actual persisted delivery path для каждого kind.

## RED/GREEN evidence

Runner from new-chat:
work\QostHubHack-T09\services\api\.venv\Scripts\python.exe work/runtime/t06-run.py pytest TARGETS -q

- RED: tests/test_telegram_review_fixes.py + tests/test_telegram_client.py::test_real_transport_does_not_follow_redirects_with_credentials: **9 failed,2 passed22.65s**. Stale assignment2jobs стали CANCELLED; health задержался4.032s под row lock; handle/commit OperationalError выходили наружу; все5 kind labels отсутствовали. Pending-local-changes fixture и исходный redirect PASS.
- Первый run после productionfix: **2 failed,8 passed15.64s**. Только новые HTTP regression fixtures выдавали invalid_token при retry: fixed business NOW уже истёк относительно реального HTTP clock. Production не менялся по этому результату.
- Следующий полный focused run: **2 failed,64 passed106.14s**, та же fixture-проблема: первая замена исправила только первое token issuance. Исправлены оба HTTP fixtures на datetime.now(timezone.utc), health regression дополнительно проверяет actual linked.
- Финальный focused run: tests/test_telegram_review_fixes.py tests/test_telegram_linking.py tests/test_deadlines.py tests/test_telegram_recovery.py tests/test_telegram_client.py -q: **66 passed142.28s,exit0**. Это55existingT06 +11newregressions. БД освобождена послеэтогопрогона.
- Ruff check --select F,I --fix:2imports исправлены; format:2files formatted2unchanged. Финальный RuffF,I:All checks passed.

Async regression bounded: holder освобождает lock послеhealthdone или4s; wait_entered и pending ограничены6s; finally всегда сигналитrelease и boundedjoin.

## Исследование Windows10053 redirect

Полный suite контроллера до этой волны:1207PASS1FAIL596.70s. Ошибка возникла при чтении response status через HTTPConnection.getresponse/_read_status/socket.recv_into, до получения302; server traceback не был сохранён. В isolated RED запуске исходный тест PASS; повторяемой production-проблемы не получено.

Найден дефект локального HTTP fixture: POST body оставался непрочитанным при немедленном закрытии302response, Content-Lengthresponse отсутствовал. На Windows закрытие TCP socket с непрочитанными bytes может оборвать ответ. Исправлен именно fixture: exactreadContent-Lengthrequest (assert body{}), responseContent-Length0. Production transport не изменён, timeout1s и assert302/no destinationhit сохранены. Это обоснованная стабилизация корректного HTTP fixture; абсолютная причинность единственного10053 не заявляется.

Повторные isolated проверки: **1passed1.11s,1passed1.12s,1passed1.42s**; все3exit0. git diff --check:exit0.

## Rulings / limits

- Ruling: flush caller pending changes перед populate_existing под row lock — сохраняет flush-only public contract и production autoflush=False; цена ошибки: потребуется более узкая политика flush caller UOW, не изменение Telegram semantics.
- Ruling: fixed kind label считается служебной причиной уведомления, разрешённой контроллером по C4, не новым личным полем; цена ошибки: согласовать wording без изменения данных.
- Ruling: timeout localredirect остаётся1s, стабилизируется протокольно корректный fixture — stack не доказывает deadline problem; цена ошибки: intermittent Windows failure требует дальнейшей инфраструктурной диагностики.
- minor (deferred): worker heartbeat/операционные метрики остаются отдельным улучшением по решению контроллера; цена — остановившийся consumer нужно обнаруживать внешней диагностикой.
- Live Telegram BLOCKED: пользователь ещё не создал бота; HTTPS/T04 отсутствуют. Новый live evidence не заявляется.

Полный suite, свежий scoped re-review, plans/docs/commit принадлежат root.

## Итог контроллера

Окончательный полный pytest:1219 PASS616.07s, exit0. Scoped review PASS и целевые66 PASS подтверждены; native production API/worker/restart/cancel smoke повторён после исправлений — PASS. Статус Т06 REVIEW: до интеграции и живой приёмки не DONE. Push/merge не выполнялись.
