"""T04 realtime authorization and committed cross-process invalidation."""

from uuid import uuid4

import pytest
from conftest import sign_in
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from work_order_helpers import add_user


def enable_polling(database, monkeypatch):
    from sqlalchemy.orm import Session
    from app.modules.work_orders import realtime

    def sessions():
        with Session(database["session"].get_bind()) as db:
            yield db

    monkeypatch.setattr(realtime, "get_db", sessions)
    monkeypatch.setattr(realtime, "POLL_INTERVAL", 0.025)
    return realtime


def connection(client):
    from starlette.requests import HTTPConnection
    token = client.cookies.get("qosthub_session")
    return HTTPConnection({"type": "websocket", "headers": [(b"cookie", f"qosthub_session={token}".encode())]})


def event(database, order, version=1, db=None, **changes):
    from datetime import datetime, timezone
    from uuid import UUID
    from app.modules.work_orders.models import WorkOrder, WorkOrderEvent
    db = db or database["session"]
    row = db.get(WorkOrder, UUID(order["id"]))
    row.version = version
    row_event = WorkOrderEvent(work_order_id=row.id, action="reprioritize", version=version,
                               assignment_version=row.assignment_version, payload={},
                               occurred_at=datetime.now(timezone.utc), **changes)
    db.add(row_event)
    db.flush()
    return row_event


def test_websocket_denies_missing_session_without_database(monkeypatch):
    from app.core.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "public_base_url", "http://localhost:5173")
    with TestClient(app) as anonymous:
        with pytest.raises(WebSocketDisconnect) as denied:
            with anonymous.websocket_connect("ws://localhost:5173/api/v1/events", headers={"Origin": "http://localhost:5173"}):
                pass
        assert denied.value.code == 1008


def test_shift_area_filter_and_enterprise_timezone(client, database, monkeypatch):
    from app.core.config import settings
    from app.modules.auth.models import UserArea

    monkeypatch.setattr(settings, "app_timezone", "Asia/Qyzylorda")
    db = database["session"]
    db.add(UserArea(user_id=database["master"].id, area_id=database["other_area"].id))
    db.commit()
    second = add_user(database, "other-area-worker", area=database["other_area"])
    sign_in(client, "master")
    response = client.get("/api/v1/shift", params={"area_id": str(database["area"].id)})
    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Qyzylorda"
    assert second.id.hex not in {item["user"]["id"].replace("-", "") for item in response.json()["items"]}
    assert str(database["worker"].id) in {item["user"]["id"] for item in response.json()["items"]}
    assert client.get("/api/v1/shift", params={"area_id": str(uuid4())}).status_code == 404
    sign_in(client, "worker")
    assert client.get("/api/v1/shift", params={"area_id": str(database["other_area"].id)}).status_code == 404


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", "http://localhost:5173.evil.example", "http://localhost:5174", "http://localhost:5173/path"])
def test_websocket_rejects_foreign_or_missing_origin(client, origin):
    sign_in(client)
    headers = {"Origin": origin} if origin else {}
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("ws://localhost:5173/api/v1/events", headers=headers):
            pass
    assert denied.value.code == 1008


def test_websocket_receives_committed_change_from_another_connection(client, database, monkeypatch, app):
    from work_order_helpers import issue
    enable_polling(database, monkeypatch)
    sign_in(client)
    with client.websocket_connect("ws://localhost:5173/api/v1/events", headers={"Origin": "http://localhost:5173"}) as ws:
        with TestClient(app, base_url="http://localhost:5173") as publisher:
            order = issue(publisher, database)
        received = ws.receive_json()
        assert set(received) == {"event_id", "type", "work_order_id", "version", "occurred_at"}
        assert received["work_order_id"] == order["id"]
        assert received["type"] == "work_order.create"
        assert received["version"] == 1


def test_open_socket_is_closed_after_logout(client, database, monkeypatch):
    enable_polling(database, monkeypatch)
    token = sign_in(client)
    with client.websocket_connect("ws://localhost:5173/api/v1/events", headers={"Origin": "http://localhost:5173"}) as ws:
        assert client.post("/api/v1/auth/logout", headers={"Origin": "http://localhost:5173", "X-CSRF-Token": token}).status_code == 204
        with pytest.raises(WebSocketDisconnect) as denied:
            ws.receive_json()
        assert denied.value.code == 1008


def test_snapshot_uses_current_access_and_never_discloses_other_area(client, database, monkeypatch):
    from sqlalchemy import delete
    from app.modules.auth.models import UserArea
    from work_order_helpers import seed_order
    realtime = enable_polling(database, monkeypatch)
    own = seed_order(database)
    other = seed_order(database, area_id=database["other_area"].id, assignee_id=database["outsider"].id)
    event(database, own)
    event(database, other)
    database["session"].commit()
    sign_in(client, "master")
    assert [e["work_order_id"] for e in realtime.read_events(connection(client))] == [own["id"]]
    database["session"].execute(delete(UserArea).where(UserArea.user_id == database["master"].id))
    database["session"].commit()
    assert realtime.read_events(connection(client)) == []
    sign_in(client, "worker")
    assert [e["work_order_id"] for e in realtime.read_events(connection(client))] == [own["id"]]


def test_late_commit_with_older_timestamp_is_delivered(client, database, monkeypatch):
    from datetime import timedelta
    from sqlalchemy.orm import Session
    from work_order_helpers import seed_order
    enable_polling(database, monkeypatch)
    first, second = seed_order(database), seed_order(database)
    event(database, first)
    event(database, second)
    database["session"].commit()
    sign_in(client)
    with client.websocket_connect("ws://localhost:5173/api/v1/events", headers={"Origin": "http://localhost:5173"}) as ws:
        with Session(database["session"].get_bind()) as delayed:
            late = event(database, first, version=2, db=delayed)
            late.occurred_at -= timedelta(days=1)
            event(database, second, version=2)
            database["session"].commit()
            assert ws.receive_json()["work_order_id"] == second["id"]
            delayed.commit()
        received = ws.receive_json()
        assert received["work_order_id"] == first["id"] and received["version"] == 2


def test_rolled_back_event_is_not_published(client, database, monkeypatch):
    from sqlalchemy.orm import Session
    from work_order_helpers import seed_order
    realtime = enable_polling(database, monkeypatch)
    own = seed_order(database)
    event(database, own)
    database["session"].commit()
    sign_in(client)
    with Session(database["session"].get_bind()) as pending:
        event(database, own, version=2, db=pending)
        assert [e["version"] for e in realtime.read_events(connection(client))] == [1]
        pending.rollback()
    assert [e["version"] for e in realtime.read_events(connection(client))] == [1]


def test_open_socket_does_not_publish_an_order_after_reassignment(client, database, monkeypatch, app):
    from work_order_helpers import action, issue
    enable_polling(database, monkeypatch)
    second = add_user(database, "new-responsible")
    own = issue(client, database)
    sign_in(client)
    with client.websocket_connect("ws://localhost:5173/api/v1/events", headers={"Origin": "http://localhost:5173"}) as ws:
        with TestClient(app, base_url="http://localhost:5173") as publisher:
            token = sign_in(publisher, "master")
            assert action(publisher, token, own, "reassign", assignee_id=str(second.id), reason="Передача").status_code == 200
            current = issue(publisher, database)
        assert ws.receive_json()["work_order_id"] == current["id"]


@pytest.mark.parametrize("revoke", ["expired", "inactive"])
def test_open_socket_rechecks_expiry_and_active_user(client, database, monkeypatch, revoke):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.core.security import session_hash
    from app.modules.auth.models import AuthSession, User
    enable_polling(database, monkeypatch)
    sign_in(client)
    with client.websocket_connect("ws://localhost:5173/api/v1/events", headers={"Origin": "http://localhost:5173"}) as ws:
        db = database["session"]
        if revoke == "expired":
            db.execute(update(AuthSession).where(AuthSession.token_hash == session_hash(client.cookies.get("qosthub_session"))).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        else:
            db.execute(update(User).where(User.id == database["worker"].id).values(is_active=False))
        db.commit()
        with pytest.raises(WebSocketDisconnect) as denied:
            ws.receive_json()
        assert denied.value.code == 1008


def test_anonymous_csrf_session_is_not_a_websocket_login(client, database, monkeypatch):
    enable_polling(database, monkeypatch)
    assert client.get("/api/v1/auth/csrf").status_code == 200
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect("ws://localhost:5173/api/v1/events", headers={"Origin": "http://localhost:5173"}):
            pass
    assert denied.value.code == 1008
