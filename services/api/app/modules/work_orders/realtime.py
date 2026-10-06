"""Read-only invalidations from committed database state, across API/worker processes."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.requests import HTTPConnection

from app.core.db import get_db
from app.core.security import AuthError, origin_matches
from app.modules.auth.models import User
from app.modules.auth.service import read_session
from app.modules.work_orders.models import WorkOrder, WorkOrderEvent
from app.modules.work_orders.queries import visible_orders

router = APIRouter(tags=["events"])
POLL_INTERVAL = 1.0


def read_events(connection: HTTPConnection) -> list[dict]:
    """One short Session entirely in one worker thread; no timestamp cursor."""
    sessions = get_db()
    try:
        db = next(sessions)
        row = read_session(db, connection)
        actor = db.get(User, row.user_id) if row and row.user_id else None
        if actor is None or not actor.is_active:
            raise AuthError(401, "unauthenticated", "Требуется вход")
        allowed = visible_orders(db, actor).with_only_columns(WorkOrder.id).subquery()
        events = db.scalars(select(WorkOrderEvent).join(
            WorkOrder, (WorkOrder.id == WorkOrderEvent.work_order_id) &
            (WorkOrder.version == WorkOrderEvent.version),
        ).where(WorkOrder.id.in_(select(allowed.c.id))))
        return [{
            "event_id": str(event.id), "type": "work_order." + event.action,
            "work_order_id": str(event.work_order_id), "version": event.version,
            "occurred_at": event.occurred_at.isoformat(),
        } for event in events]
    finally:
        sessions.close()


@router.websocket("/events")
async def events(websocket: WebSocket):
    token = websocket.cookies.get("qosthub_session", "")
    if not token or len(token) > 128 or not websocket.headers.get("origin") or not origin_matches(websocket):
        await websocket.close(code=1008)
        return
    try:
        baseline = await run_in_threadpool(read_events, websocket)
        seen = {event["work_order_id"]: event["version"] for event in baseline}
        await websocket.accept()
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=POLL_INTERVAL)
                if message["type"] == "websocket.disconnect":
                    return
                # Clients only subscribe. Reject unsolicited commands.
                await websocket.close(code=1008)
                return
            except TimeoutError:
                snapshot = await run_in_threadpool(read_events, websocket)
                current = {}
                for event in snapshot:
                    order_id, version = event["work_order_id"], event["version"]
                    current[order_id] = version
                    if version > seen.get(order_id, 0):
                        await websocket.send_json(event)
                seen = current
    except AuthError:
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        return
