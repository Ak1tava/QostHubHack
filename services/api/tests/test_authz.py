"""Behaviour at the auth/catalog boundary, using real PostgreSQL."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import sign_in
from sqlalchemy import select, update

ORIGIN = {"Origin": "http://localhost:5173"}


def headers(token):
    return {**ORIGIN, "X-CSRF-Token": token}


def test_without_session_me_returns_401(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("path", ["/catalog/areas", "/catalog/equipment", "/shift"])
def test_catalog_and_shift_require_session(client, path):
    assert client.get("/api/v1" + path).status_code == 401


def test_csrf_creates_hashed_anonymous_session(client, database):
    from app.modules.auth.models import AuthSession

    r = client.get("/api/v1/auth/csrf")
    assert r.status_code == 200
    cookie = client.cookies.get("qosthub_session")
    assert len(cookie) >= 43
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "samesite=lax" in r.headers["set-cookie"].lower()
    assert r.headers["cache-control"] == "no-store"
    row = database["session"].scalar(select(AuthSession))
    assert row.token_hash != cookie and len(row.token_hash) == 64
    assert row.user_id is None
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/csrf").json() == r.json()


def test_login_rotates_cookie_and_csrf_and_preserves_pin(client, database):
    before = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    old = client.cookies.get("qosthub_session")
    r = client.post(
        "/api/v1/auth/login",
        json={"login": " worker ", "password": "0042"},
        headers=headers(before),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["role"] == "worker"
    assert set(data["user"]) == {
        "id",
        "display_name",
        "role",
        "specialty",
        "grade",
        "brigade_id",
        "shift_id",
    }
    assert data["csrf_token"] != before
    assert client.cookies.get("qosthub_session") != old
    assert client.get("/api/v1/auth/me").json() == data
    assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == data["csrf_token"]
    client.cookies.set("qosthub_session", old, domain="localhost.local", path="/")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_cookie_on_server(client):
    token = sign_in(client)
    old = client.cookies.get("qosthub_session")
    r = client.post("/api/v1/auth/logout", headers=headers(token))
    assert r.status_code == 204 and not r.content
    assert "Max-Age=0" in r.headers["set-cookie"]
    client.cookies.set("qosthub_session", old, domain="localhost.local", path="/")
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "login,password", [("missing", "0042"), ("worker", "wrong"), ("worker", "0042 ")]
)
def test_invalid_credentials_generic(client, login, password):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = client.post(
        "/api/v1/auth/login",
        json={"login": login, "password": password},
        headers=headers(token),
    )
    assert r.status_code == 401
    assert r.json() == {
        "error": {
            "code": "invalid_credentials",
            "message": "Неверный логин или пароль",
            "details": [],
        }
    }
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"login": "worker", "password": "0042", "role": "admin"},
        {"login": " ", "password": "0042"},
        {"login": "worker", "password": ""},
    ],
)
def test_validation_rejects_bad_body_without_echoing_password(client, body):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = client.post("/api/v1/auth/login", json=body, headers=headers(token))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["details"]
    assert "0042" not in r.text


@pytest.mark.parametrize(
    "extra",
    [
        {"Origin": "http://evil.example"},
        {"Origin": "http://localhost:51730"},
        {"Origin": "null"},
        {},
    ],
)
def test_login_rejects_untrusted_or_missing_origin(client, extra):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = client.post(
        "/api/v1/auth/login",
        json={"login": "worker", "password": "0042"},
        headers={"X-CSRF-Token": token, **extra},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


def test_same_origin_referer_allowed(client):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    r = client.post(
        "/api/v1/auth/login",
        json={"login": "worker", "password": "0042"},
        headers={"X-CSRF-Token": token, "Referer": "http://localhost:5173/login"},
    )
    assert r.status_code == 200


@pytest.mark.parametrize("token", ["wrong", ""])
def test_login_rejects_bad_csrf(client, token):
    client.get("/api/v1/auth/csrf")
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"login": "worker", "password": "0042"},
            headers=headers(token),
        ).status_code
        == 403
    )


def test_logout_checks_auth_before_csrf(client):
    assert client.post("/api/v1/auth/logout", headers=ORIGIN).status_code == 401
    sign_in(client)
    assert (
        client.post("/api/v1/auth/logout", headers=headers("wrong")).status_code == 403
    )
    assert client.get("/api/v1/auth/me").status_code == 200


def test_expired_anonymous_session_cannot_login(client, database):
    from app.modules.auth.models import AuthSession

    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    database["session"].execute(
        update(AuthSession).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    )
    database["session"].commit()
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"login": "worker", "password": "0042"},
            headers=headers(token),
        ).status_code
        == 403
    )


def test_expired_user_session_rejected(client, database):
    from app.modules.auth.models import AuthSession

    sign_in(client)
    database["session"].execute(
        update(AuthSession).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    )
    database["session"].commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_tampered_cookie_rejected(client):
    sign_in(client)
    client.cookies.set(
        "qosthub_session", "tampered", domain="localhost.local", path="/"
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_https_cookie_always_secure(app, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://demo.example")
    with TestClient(app, base_url="https://demo.example") as client:
        r = client.get("/api/v1/auth/csrf")
    assert "secure" in r.headers["set-cookie"].lower()


def test_login_attempts_limited_persistently(client, database):
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"login": "worker", "password": "wrong"},
                headers=headers(token),
            ).status_code
            == 401
        )
    r = client.post(
        "/api/v1/auth/login",
        json={"login": "worker", "password": "0042"},
        headers=headers(token),
    )
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    assert r.json()["error"]["code"] == "rate_limited"


def test_csrf_requests_limited(client):
    for _ in range(60):
        assert client.get("/api/v1/auth/csrf").status_code == 200
    assert client.get("/api/v1/auth/csrf").status_code == 429


def test_worker_cannot_issue_order_master_limited_to_areas(database):
    from app.core.security import can_access_order, require_order_creation
    from app.modules.auth.service import AuthError
    from app.modules.work_orders.models import WorkOrder

    s = database["session"]
    with pytest.raises(AuthError) as exc:
        require_order_creation(s, database["worker"], database["area"].id)
    assert exc.value.status_code == 403
    require_order_creation(s, database["master"], database["area"].id)
    with pytest.raises(AuthError):
        require_order_creation(s, database["master"], database["other_area"].id)
    order = WorkOrder(
        area_id=database["area"].id,
        assignee_id=database["worker"].id,
        brigade_id=None,
        master_id=database["master"].id,
    )
    assert can_access_order(s, database["worker"], order)
    assert not can_access_order(s, database["outsider"], order)
    assert can_access_order(s, database["master"], order)
    order.area_id = database["other_area"].id
    assert not can_access_order(s, database["master"], order)


def test_worker_and_master_catalog_scoped(client, database):
    sign_in(client)
    areas = client.get("/api/v1/catalog/areas").json()["items"]
    assert [a["id"] for a in areas] == [str(database["area"].id)]
    equipment = client.get("/api/v1/catalog/equipment").json()["items"]
    assert [e["name"] for e in equipment] == ["Насос"]
    users = client.get("/api/v1/catalog/users").json()["items"]
    assert [u["id"] for u in users] == [str(database["worker"].id)]
    assert "password" not in str(users) and "login" not in str(users)
    sign_in(client, "master")
    users = client.get("/api/v1/catalog/users").json()["items"]
    assert {u["id"] for u in users} == {
        str(database["worker"].id),
        str(database["master"].id),
    }
    assert client.get("/api/v1/catalog/not-a-kind").status_code == 404


def test_shift_scoped_and_occupancy_computed(client, database):
    from app.modules.work_orders.models import WorkOrder

    s = database["session"]
    s.add(
        WorkOrder(
            number="N001",
            work_type="planned",
            description="Ремонт",
            area_id=database["area"].id,
            equipment_id=database["equipment"].id,
            assignee_id=database["worker"].id,
            master_id=database["master"].id,
            due_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status="IN_PROGRESS",
        )
    )
    s.commit()
    sign_in(client)
    items = client.get("/api/v1/shift").json()["items"]
    assert len(items) == 1 and items[0]["user"]["id"] == str(database["worker"].id)
    assert items[0]["availability"] == "busy"
    sign_in(client, "master")
    ids = {r["user"]["id"] for r in client.get("/api/v1/shift").json()["items"]}
    assert str(database["outsider"].id) not in ids


def test_password_hash_not_plain_and_verify(database):
    from app.core.security import verify_password

    hashed = database["worker"].password_hash
    assert "0042" not in hashed
    assert verify_password("0042", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("0042", "malformed")


def test_brigade_members_view_but_only_responsible_writes(database):
    from app.core.security import can_access_order
    from app.modules.work_orders.models import WorkOrder

    actor = database["worker"]
    order = WorkOrder(
        area_id=database["area"].id,
        assignee_id=None,
        brigade_id=actor.brigade_id,
        responsible_id=database["master"].id,
        master_id=database["master"].id,
    )
    assert can_access_order(database["session"], actor, order)
    assert not can_access_order(database["session"], actor, order, write=True)
    order.responsible_id = actor.id
    assert can_access_order(database["session"], actor, order, write=True)


def test_disabled_user_cannot_login_or_use_session(client, database):
    sign_in(client)
    user = database["worker"]
    user.is_active = False
    database["session"].commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"login": "worker", "password": "0042"},
            headers=headers(token),
        ).status_code
        == 401
    )


def test_rate_window_expires(client, database):
    from app.modules.auth.models import AuthThrottle

    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    for _ in range(6):
        client.post(
            "/api/v1/auth/login",
            json={"login": "worker", "password": "wrong"},
            headers=headers(token),
        )
    database["session"].execute(
        update(AuthThrottle).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    )
    database["session"].commit()
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"login": "worker", "password": "0042"},
            headers=headers(token),
        ).status_code
        == 200
    )


def test_demo_command_creates_hashes_and_does_not_overwrite(database):
    from app.core.security import verify_password
    from app.modules.auth.demo import create_demo_accounts
    from app.modules.auth.models import User

    s = database["session"]
    create_demo_accounts(
        s, "demo-master", "master-secret-42", "demo-worker", "worker-secret-42"
    )
    worker = s.scalar(select(User).where(User.login == "demo-worker"))
    assert worker.role == "worker"
    assert verify_password("worker-secret-42", worker.password_hash)
    with pytest.raises(ValueError):
        create_demo_accounts(s, "demo-master", "changed", "demo-worker", "changed")
    assert verify_password("worker-secret-42", worker.password_hash)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost/production",
        "postgresql+psycopg://u:p@remote/qosthub_demo",
        "sqlite:///qosthub_demo",
    ],
)
def test_demo_refuses_production_targets(url):
    from app.modules.auth.demo import validate_demo_target

    with pytest.raises(ValueError):
        validate_demo_target(url)


def test_session_not_sliding(client, database):
    from app.modules.auth.models import AuthSession

    sign_in(client)
    expiry = database["session"].scalar(
        select(AuthSession.expires_at).where(AuthSession.user_id.is_not(None))
    )
    client.get("/api/v1/auth/me")
    client.get("/api/v1/auth/csrf")
    assert (
        database["session"].scalar(
            select(AuthSession.expires_at).where(AuthSession.user_id.is_not(None))
        )
        == expiry
    )


def test_real_dependency_rolls_back_uncommitted_writes(database, monkeypatch):
    from sqlalchemy.orm import Session, sessionmaker

    from app.core import db as module
    from app.modules.catalog.models import Area

    monkeypatch.setattr(module, "_engine", database["engine"])
    monkeypatch.setattr(
        module,
        "_factory",
        sessionmaker(database["engine"], autoflush=False, expire_on_commit=False),
    )
    generator = module.get_db()
    session = next(generator)
    session.add(Area(name="Не коммитить"))
    session.flush()
    generator.close()
    with Session(database["engine"]) as reader:
        assert reader.scalar(select(Area).where(Area.name == "Не коммитить")) is None


def test_concurrent_throttle_cannot_lose_attempts(database):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.orm import Session

    from app.modules.auth.service import AuthError, enforce_limits

    def attempt(_):
        with Session(database["engine"]) as s:
            try:
                enforce_limits(s, [("concurrent-test", 5, 900)])
                s.commit()
                return 200
            except AuthError as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(12)))
    assert results.count(200) == 5
    assert results.count(429) == 7


def test_concurrent_login_consumes_anonymous_session_once(app, database, client):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.core.db import get_db

    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    cookie = client.cookies.get("qosthub_session")

    def separate_session():
        with Session(database["engine"], expire_on_commit=False) as s:
            try:
                yield s
            finally:
                s.rollback()

    app.dependency_overrides[get_db] = separate_session

    def attempt(_):
        with TestClient(app, base_url="http://localhost:5173") as other:
            other.cookies.set(
                "qosthub_session", cookie, domain="localhost.local", path="/"
            )
            return other.post(
                "/api/v1/auth/login",
                json={"login": "worker", "password": "0042"},
                headers=headers(token),
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [200, 403]


def test_remote_http_cannot_issue_insecure_cookie(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_base_url", "http://demo.example")
    r = client.get("/api/v1/auth/csrf")
    assert r.status_code == 503
    assert "set-cookie" not in r.headers


def test_me_expiry_between_authorization_and_response_returns_401(
    client, database, monkeypatch
):
    from app.modules.auth import service
    from app.modules.auth.models import AuthSession

    sign_in(client)
    first = datetime.now(timezone.utc)
    database["session"].execute(
        update(AuthSession).values(expires_at=first + timedelta(seconds=1))
    )
    database["session"].commit()
    ticks = iter([first, first + timedelta(seconds=2)])
    monkeypatch.setattr(service, "now_utc", lambda: next(ticks))
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_shift_counts_work_in_other_area_without_leaking_order_id(client, database):
    from app.modules.auth.models import UserArea
    from app.modules.catalog.models import Equipment
    from app.modules.work_orders.models import WorkOrder

    s = database["session"]
    s.add(UserArea(user_id=database["worker"].id, area_id=database["other_area"].id))
    equipment = s.scalar(
        select(Equipment).where(Equipment.area_id == database["other_area"].id)
    )
    s.add(
        WorkOrder(
            number="B001",
            work_type="planned",
            description="Работа на другом участке",
            area_id=database["other_area"].id,
            equipment_id=equipment.id,
            assignee_id=database["worker"].id,
            master_id=database["master"].id,
            due_at=datetime.now(timezone.utc) + timedelta(hours=1),
            status="IN_PROGRESS",
        )
    )
    s.add(
        WorkOrder(
            number="B002",
            work_type="planned",
            description="Очередь на другом участке",
            area_id=database["other_area"].id,
            equipment_id=equipment.id,
            assignee_id=database["worker"].id,
            master_id=database["master"].id,
            due_at=datetime.now(timezone.utc) + timedelta(hours=2),
            status="QUEUED",
        )
    )
    s.commit()
    sign_in(client, "master")
    worker = next(
        row
        for row in client.get("/api/v1/shift").json()["items"]
        if row["user"]["id"] == str(database["worker"].id)
    )
    assert worker["availability"] == "busy"
    assert worker["queue_count"] == 1
    assert worker["active_work_order_id"] is None


def test_blocked_ip_does_not_allocate_new_account_keys(client, database):
    from sqlalchemy import func

    from app.modules.auth.models import AuthThrottle

    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    for n in range(30):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"login": f"unknown-{n}", "password": "wrong"},
                headers=headers(token),
            ).status_code
            == 401
        )
    count = database["session"].scalar(select(func.count()).select_from(AuthThrottle))
    for n in range(10):
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"login": f"blocked-{n}", "password": "wrong"},
                headers=headers(token),
            ).status_code
            == 429
        )
    assert (
        database["session"].scalar(select(func.count()).select_from(AuthThrottle))
        == count
    )


def test_expired_throttle_keys_cleaned_without_removing_live_limits(client, database):
    from app.modules.auth.models import AuthThrottle

    now = datetime.now(timezone.utc)
    s = database["session"]
    for n in range(5):
        s.add(
            AuthThrottle(
                key=f"{n:064x}", attempts=10, expires_at=now - timedelta(seconds=1)
            )
        )
    live = "f" * 64
    s.add(AuthThrottle(key=live, attempts=10, expires_at=now + timedelta(hours=1)))
    s.commit()
    assert client.get("/api/v1/auth/csrf").status_code == 200
    keys = set(s.scalars(select(AuthThrottle.key)))
    assert live in keys
    assert len(keys) == 2
