# Передача серверной T02 участнику A

Работа ведётся в feat/T02-data-auth от 8a26387 (chore/parallel-foundation). Ветка main и GitHub не изменены. Это серверная реализация на проверке; общий app.main и frontend подключает A.

## Что реализовано

- Ленивый sync PostgreSQL engine, Base/get_db, Session на запрос; commit в сервисе, rollback/close в зависимости, dispose_engine для lifespan.
- 19 таблиц C1: пользователи/участки/смены/бригады, сессии/ограничители входа, справочники/нормы, наряды, события, отчёты, фотографии, расход, ИИ-проверки, решения и простой. В БД UUID, timezone-aware время, decimal, FK и проверки значений. Наряд назначается одному сотруднику или бригаде с ответственным.
- Вход с непрозрачной серверной cookie; в БД только SHA-256 идентификатора сессии. Пароль — PBKDF2-HMAC-SHA256 с солью и 600000 итерациями. Пароль/ПИН остаётся строкой.
- C1.2 csrf/login/logout/me, ротация сессии при входе, отзыв на выходе, срок 12 часов / анонимная 15 минут; CSRF плюс Origin/Referer; Cache-Control: no-store.
- PostgreSQL-ограничители: 5 попыток за 15 минут на пару IP/логин, 10 на логин, 30 на IP; csrf — 60 запросов в минуту на IP. Общий IP-лимит проверяется до создания ключей новых логинов; истёкшие ключи очищаются пакетами до 500 с SKIP LOCKED при получении CSRF. Счётчики сохраняются при отказе, обновляются атомарно; 429 возвращает Retry-After. Используется ASGI peer, заголовки клиента X-Forwarded-For не читаются.
- Cookie Secure принудительно на HTTPS; HTTP допустим только на localhost/127.0.0.1/::1. Публичный HTTP отклоняется.
- Общие проверки объектов: require_order_creation, can_access_order, require_order_access. Мастер работает только в разрешённых участках; исполнитель — собственный наряд или свою бригаду, изменение бригадного наряда — только ответственный. Manager/admin здесь имеют чтение своих участков, выдача — только master. Карточки/фото/переходы подключаются в T03/T05.

## Подключение — делает A

Существующие main.py/config.py/pyproject.toml/uv.lock/web не менялись.

В main.py подключить до app.include_router(api_router):

~~~python
from app.modules.auth.router import router as auth_router, register_auth_handlers
from app.modules.catalog.router import router as catalog_router, shift_router

register_auth_handlers(app)
api_router.include_router(auth_router)
api_router.include_router(catalog_router)
api_router.include_router(shift_router)
~~~

api_router имеет единственный prefix='/api/v1'. Router модулей уже содержит /auth, /catalog или /shift. В lifespan A вызывает dispose_engine() при остановке. Глобальный AuthError handler нужен также будущим модулям. Обработчик validation унифицирует только ошибки auth, не меняет остальные маршруты.

БД: DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/qosthub_demo. Настройка уже существует как SecretStr; пароль задаётся вне Git. PUBLIC_BASE_URL должен совпадать с browser origin. На HTTPS cookie всегда Secure, локально SESSION_COOKIE_SECURE=false. Для непрозрачных серверных сессий SESSION_SECRET не используется: подпись токена не нужна, он случайный и проверяется по хешу в БД.

Новых runtime-пакетов не требуется: пароль хешируется стандартной библиотекой. A добавляет тестовые pytest и httpx в dev-зависимости; для зафиксированной в основе Starlette 1.7.0 нужен также httpx2, иначе TestClient выдаёт предупреждение. Во время этой работы пакеты предоставлены через uv --with без правки общих lock-файлов.

## Миграции и локальные аккаунты

Из services/api, после задания DATABASE_URL и создания пустой PostgreSQL БД:

~~~sh
uv sync --locked
uv run alembic upgrade head
uv run alembic check
uv run python -m app.modules.auth.demo --confirm-demo
~~~

Demo-команда требует локальную БД qosthub_demo* или qosthub_test*, спрашивает два пароля через getpass, не содержит default-паролей и не перезаписывает существующие аккаунты. Создаёт два аккаунта, участок, бригаду и восьмичасовую смену. Полный seed остаётся T09; оборудование/материалы команда не наполняет.

До подключения общего main можно проверить серверные маршруты в тестовом приложении:

~~~sh
uv run uvicorn --app-dir tests t02_app:app --host 127.0.0.1 --port 8000
~~~

Это тестовый harness, не новая production-точка входа. Swagger — /docs. Для изменяющих запросов нужны cookie, X-CSRF-Token и Origin из PUBLIC_BASE_URL; один Swagger без этих заголовков не заменяет браузерную проверку.

## Передача frontend

Auth следует C1.2: GET csrf → POST login → GET me → POST logout. JSON login содержит только login/password; остальные поля запрещены. Cookie браузер отправляет автоматически, session id в JSON отсутствует. csrf_token хранится в памяти, после перезагрузки восстанавливается из me. Сессия не продлевается при чтении. Ошибки не возвращают введённые секреты.

Каталог: GET /api/v1/catalog/{kind}?offset=0&limit=100; kind: areas, equipment, users, brigades, work-codes, materials, norms. Ответ: {items,total,offset,limit}. items содержит тип соответствующего справочника; users соответствует UserView. Максимальный limit=200. Пользователь видит разрешённые участки/оборудование/нормы; worker в users видит себя, другие роли — активных пользователей своих участков. Общие материалы и шифры доступны после входа.

Смена: GET /api/v1/shift → {items,as_of}. Элемент: user, start_at/end_at (nullable), availability (free|busy|queued|off_shift), queue_count, active_work_order_id (nullable). Нагрузка учитывает все назначения видимых работников, включая другие участки; UUID активного наряда выдаётся только при праве доступа к нему. availability рассчитывается сервером: вне смены → off_shift; IN_PROGRESS → busy; QUEUED → queued; иначе free. Начало смены включительно, конец исключительно. Worker видит себя, остальные роли — людей своих участков. Паузы и полный жизненный цикл уточняются в T03.

Формы каталога/смены в C1 не были подробно заданы; они предложены этими серверными Pydantic-схемами и требуют принятия A перед frontend-интеграцией. Auth C1.2 сохранён. A подключает реальные routers, экспортирует OpenAPI и генерирует TS; генерируемые файлы вручную не менять. WorkOrderView предоставлен для T03; is_overdue/allowed_actions рассчитывает сервис жизненного цикла.

## Проверки

Тесты выполняют настоящий HTTP-контракт через ASGI/TestClient и настоящие операции PostgreSQL. TEST_DATABASE_URL должен указывать только на одноразовую qosthub_test* БД: fixtures удаляют/создают таблицы. Для теста миграций отдельно MIGRATION_TEST_DATABASE_URL=qosthub_migration_test*; upgrade/downgrade также меняют её содержимое. Не направлять их в рабочую БД.

~~~sh
uv run --locked --with pytest --with httpx --with httpx2 pytest tests/test_authz.py -q
uv run --locked --with pytest --with httpx --with httpx2 pytest -q
~~~

В Windows переменные можно задать в PowerShell через $env:TEST_DATABASE_URL и $env:MIGRATION_TEST_DATABASE_URL. Пароли и URL не помещать в планы/логи/коммиты.

Проверены обычный/ошибочный вход, expiry, CSRF/origin, logout, потеря прав, область каталога, бригада, конкурентный вход и ограничения попыток, rollback незакоммиченного запроса, constraints и миграция пустой БД. Фактический итог находится в docs/T02-verification.md.

## Что остаётся

A: подключить routers/обработчики/lifespan, зафиксировать dev-зависимости, обновить OpenAPI/TS и проверить LoginPage через браузер. T03/T05: подключить общую объектную авторизацию к настоящим карточкам/фото и проверить чужие UUID по HTTP. T04: проверить авторизацию WebSocket. T06: jobs/outbox. До этих интеграционных проверок Т02 не получает DONE.
