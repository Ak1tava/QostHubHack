"""C2 role/status matrix, independently specified from the implementation."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.core.security import AuthError


STATUSES = (
    "ISSUED", "ACCEPTED", "QUEUED", "REJECTED", "IN_PROGRESS", "PAUSED",
    "SUBMITTED", "AI_REVIEW", "REWORK", "CLOSED", "CANCELLED",
)
ROLES = ("master", "worker", "manager", "admin", "system")
OPEN_STATUSES = frozenset(STATUSES[:-2])

# Literal contract expectations: never import the production transition table.
CASES = (
    ("accept", {"ISSUED", "QUEUED"}, {"worker"}, "ACCEPTED"),
    ("queue", {"ISSUED", "ACCEPTED"}, {"worker"}, "QUEUED"),
    ("reject", {"ISSUED", "ACCEPTED", "QUEUED"}, {"worker"}, "REJECTED"),
    ("reassign", {"ISSUED", "ACCEPTED", "QUEUED", "REJECTED", "PAUSED"}, {"master"}, "ISSUED"),
    ("start", {"ACCEPTED"}, {"worker"}, "IN_PROGRESS"),
    ("pause", {"IN_PROGRESS"}, {"worker"}, "PAUSED"),
    ("resume", {"PAUSED"}, {"worker"}, "IN_PROGRESS"),
    ("submit", {"IN_PROGRESS"}, {"worker"}, "SUBMITTED"),
    ("begin_review", {"SUBMITTED"}, {"system"}, "AI_REVIEW"),
    ("request_rework", {"AI_REVIEW"}, {"master", "system"}, "REWORK"),
    ("restart", {"REWORK"}, {"worker"}, "IN_PROGRESS"),
    ("close", {"AI_REVIEW"}, {"master"}, "CLOSED"),
    ("override_close", {"REWORK"}, {"master"}, "CLOSED"),
    ("cancel", OPEN_STATUSES, {"master"}, "CANCELLED"),
    ("reprioritize", OPEN_STATUSES, {"master"}, None),
)


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("action,sources,roles,target", CASES)
def test_c2_transition_matrix(status, role, action, sources, roles, target):
    from app.modules.work_orders.state_machine import transition

    if role not in roles:
        expected_error = (403, "forbidden")
    elif status not in sources:
        expected_error = (409, "invalid_transition")
    else:
        assert transition(status, action, role, "Указанная причина") == (target or status)
        return

    with pytest.raises(AuthError) as error:
        transition(status, action, role, "Указанная причина")
    assert (error.value.status_code, error.value.code) == expected_error


@pytest.mark.parametrize("reason", [None, "", " \t\n "])
@pytest.mark.parametrize(
    "status,action,role",
    [
        ("ISSUED", "reject", "worker"),
        ("PAUSED", "reassign", "master"),
        ("IN_PROGRESS", "pause", "worker"),
        ("AI_REVIEW", "request_rework", "system"),
        ("AI_REVIEW", "request_rework", "master"),
        ("REWORK", "override_close", "master"),
        ("REJECTED", "cancel", "master"),
    ],
)
def test_reason_is_required(status, action, role, reason):
    from app.modules.work_orders.state_machine import transition

    with pytest.raises(AuthError) as error:
        transition(status, action, role, reason)
    assert (error.value.status_code, error.value.code) == (422, "validation_error")


@pytest.mark.parametrize(
    "status,action,role,target",
    [
        ("ISSUED", "accept", "worker", "ACCEPTED"),
        ("ACCEPTED", "start", "worker", "IN_PROGRESS"),
        ("SUBMITTED", "begin_review", "system", "AI_REVIEW"),
        ("AI_REVIEW", "close", "master", "CLOSED"),
        ("IN_PROGRESS", "reprioritize", "master", "IN_PROGRESS"),
    ],
)
def test_actions_without_reason_requirement(status, action, role, target):
    from app.modules.work_orders.state_machine import transition

    assert transition(status, action, role) == target


@pytest.mark.parametrize("role", ROLES)
def test_unknown_action_is_rejected(role):
    from app.modules.work_orders.state_machine import transition

    with pytest.raises(AuthError) as error:
        transition("ISSUED", "invented", role)
    assert (error.value.status_code, error.value.code) == (422, "validation_error")


@pytest.mark.parametrize("action", ["cancel", "reprioritize"])
def test_unknown_status_cannot_be_cancelled_or_reprioritized(action):
    from app.modules.work_orders.state_machine import transition

    with pytest.raises(AuthError) as error:
        transition("invented", action, "master", "Причина")
    assert (error.value.status_code, error.value.code) == (409, "invalid_transition")


@pytest.mark.parametrize(
    "status,worker_actions,master_actions",
    [
        ("ISSUED", ["accept", "queue", "reject"], ["reassign", "cancel", "reprioritize"]),
        ("ACCEPTED", ["queue", "reject", "start"], ["reassign", "cancel", "reprioritize"]),
        ("QUEUED", ["accept", "reject"], ["reassign", "cancel", "reprioritize"]),
        ("REJECTED", [], ["reassign", "cancel", "reprioritize"]),
        ("IN_PROGRESS", ["pause"], ["cancel", "reprioritize"]),
        ("PAUSED", ["resume"], ["reassign", "cancel", "reprioritize"]),
        ("SUBMITTED", [], ["cancel", "reprioritize"]),
        ("AI_REVIEW", [], ["cancel", "reprioritize"]),
        ("REWORK", ["restart"], ["cancel", "reprioritize"]),
        ("CLOSED", [], []),
        ("CANCELLED", [], []),
        ("invented", [], []),
    ],
)
def test_allowed_actions_are_public_and_match_role_and_status(status, worker_actions, master_actions):
    from app.modules.work_orders.state_machine import allowed_actions

    for role, expected in (("worker", worker_actions), ("master", master_actions)):
        assert allowed_actions(status, role, is_responsible=True, has_active_order=False) == expected
    for role in ("manager", "admin", "system", "invented"):
        assert allowed_actions(status, role, is_responsible=True, has_active_order=False) == []


@pytest.mark.parametrize("status", STATUSES)
def test_nonresponsible_worker_has_no_actions(status):
    from app.modules.work_orders.state_machine import allowed_actions

    assert allowed_actions(status, "worker", is_responsible=False, has_active_order=False) == []


@pytest.mark.parametrize(
    "status,expected",
    [
        ("ISSUED", ["accept", "queue", "reject"]),
        ("ACCEPTED", ["queue", "reject"]),
        ("IN_PROGRESS", ["pause"]),
        ("PAUSED", []),
        ("REWORK", []),
    ],
)
def test_busy_worker_cannot_start_resume_or_restart(status, expected):
    from app.modules.work_orders.state_machine import allowed_actions

    assert allowed_actions(status, "worker", is_responsible=True, has_active_order=True) == expected


def test_master_actions_do_not_depend_on_worker_responsibility_or_occupancy():
    from app.modules.work_orders.state_machine import allowed_actions

    assert allowed_actions("PAUSED", "master", is_responsible=False, has_active_order=True) == [
        "reassign", "cancel", "reprioritize",
    ]


@pytest.mark.parametrize("action,sources,roles,target", CASES)
@pytest.mark.parametrize("role", ROLES)
def test_role_gate_does_not_require_current_status_or_reason(action, sources, roles, target, role):
    from app.modules.work_orders.state_machine import require_action_role

    if role in roles:
        assert require_action_role(action, role) is None
    else:
        with pytest.raises(AuthError) as error:
            require_action_role(action, role)
        assert (error.value.status_code, error.value.code) == (403, "forbidden")


NOW = datetime(2026, 10, 3, 7, 0, tzinfo=timezone.utc)
ORDER_ID = UUID("00000000-0000-0000-0000-000000000010")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000020")


def make_order(status="ISSUED", version=2):
    from app.modules.work_orders.models import WorkOrder

    return WorkOrder(
        id=ORDER_ID,
        status=status,
        priority="normal",
        assignee_id=ACTOR_ID,
        brigade_id=None,
        responsible_id=None,
        version=version,
        assignment_version=3,
        queue_position=None,
        due_at=NOW + timedelta(hours=4),
    )


class RecordingTransaction:
    """Capture writer effects while PostgreSQL integration tests cover persistence."""

    def __init__(self, open_interval=None):
        self.added = []
        self.open_interval = open_interval

    def add(self, item):
        self.added.append(item)

    def add_all(self, items):
        self.added.extend(items)

    def scalar(self, query):
        return self.open_interval

    def flush(self):
        # SQLAlchemy's insert UUID defaults become available after flush.
        for item in self.added:
            if item.id is None:
                item.id = uuid4()

    def commit(self):
        raise AssertionError("The writer must not commit the caller's transaction")


def test_snapshot_is_json_safe_and_records_mutable_assignment_fields():
    from app.modules.work_orders.events import snapshot

    order = make_order("QUEUED", version=8)
    order.queue_position = 2
    order.assignee_id = None
    order.brigade_id = UUID("00000000-0000-0000-0000-000000000030")
    order.responsible_id = ACTOR_ID

    assert json.loads(json.dumps(snapshot(order))) == {
        "status": "QUEUED",
        "priority": "normal",
        "assignee_id": None,
        "brigade_id": "00000000-0000-0000-0000-000000000030",
        "responsible_id": "00000000-0000-0000-0000-000000000020",
        "version": 8,
        "assignment_version": 3,
        "queue_position": 2,
        "due_at": "2026-10-03T11:00:00+00:00",
    }


def test_transition_writes_audit_and_outbox_with_matching_version_and_identity():
    from app.modules.work_orders.events import record_transition, snapshot
    from app.modules.work_orders.models import OutboxEvent, WorkOrderEvent

    db = RecordingTransaction()
    order = make_order("ISSUED", version=7)
    before = snapshot(order)
    order.status = "ACCEPTED"
    order.version = 8
    event = record_transition(db, order, action="accept", actor_id=ACTOR_ID, reason=None, before=before, now=NOW)

    assert isinstance(event, WorkOrderEvent)
    assert event.work_order_id == ORDER_ID
    assert event.version == 8
    assert event.assignment_version == 3
    assert event.actor_id == ACTOR_ID
    assert event.action == "accept"
    assert event.occurred_at == NOW
    assert event.payload == {"before": before, "after": {**before, "status": "ACCEPTED", "version": 8}}
    assert event.reason is None
    assert len(db.added) == 2
    outbox = next(item for item in db.added if isinstance(item, OutboxEvent))
    assert outbox.event_id == event.id
    assert outbox.work_order_id == ORDER_ID
    assert outbox.version == 8
    assert outbox.assignment_version == 3
    assert outbox.type == "work_order.accept"
    assert outbox.occurred_at == NOW
    assert outbox.published_at is None
    assert json.loads(json.dumps(outbox.payload)) == {
        "event_id": str(event.id),
        "type": "work_order.accept",
        "work_order_id": str(ORDER_ID),
        "version": 8,
        "assignment_version": 3,
        "occurred_at": "2026-10-03T07:00:00+00:00",
    }


def test_creation_records_empty_before_and_no_time_interval():
    from app.modules.work_orders.events import record_transition
    from app.modules.work_orders.models import WorkOrderInterval

    db = RecordingTransaction()
    event = record_transition(db, make_order(version=1), action="create", actor_id=ACTOR_ID, reason=None, before={}, now=NOW)

    assert event.version == 1
    assert event.payload["before"] == {}
    assert event.payload["after"]["status"] == "ISSUED"
    assert not any(isinstance(item, WorkOrderInterval) for item in db.added)


@pytest.mark.parametrize(
    "old_status,new_status,action,old_kind,new_kind",
    [
        ("ACCEPTED", "IN_PROGRESS", "start", None, "active"),
        ("IN_PROGRESS", "PAUSED", "pause", "active", "pause"),
        ("PAUSED", "IN_PROGRESS", "resume", "pause", "active"),
        ("PAUSED", "ISSUED", "reassign", "pause", None),
        ("IN_PROGRESS", "SUBMITTED", "submit", "active", "review"),
        ("SUBMITTED", "AI_REVIEW", "begin_review", "review", "review"),
        ("AI_REVIEW", "REWORK", "request_rework", "review", None),
        ("AI_REVIEW", "CLOSED", "close", "review", None),
        ("REWORK", "IN_PROGRESS", "restart", None, "active"),
        ("IN_PROGRESS", "CANCELLED", "cancel", "active", None),
        ("PAUSED", "CANCELLED", "cancel", "pause", None),
        ("SUBMITTED", "CANCELLED", "cancel", "review", None),
        ("IN_PROGRESS", "IN_PROGRESS", "reprioritize", "active", "active"),
        ("PAUSED", "PAUSED", "reprioritize", "pause", "pause"),
        ("AI_REVIEW", "AI_REVIEW", "reprioritize", "review", "review"),
    ],
)
def test_time_categories_close_and_open_only_when_category_changes(old_status, new_status, action, old_kind, new_kind):
    from app.modules.work_orders.events import record_transition, snapshot
    from app.modules.work_orders.models import WorkOrderInterval

    interval = None if old_kind is None else WorkOrderInterval(
        id=uuid4(), work_order_id=ORDER_ID, kind=old_kind, start_at=NOW - timedelta(minutes=10), end_at=None,
    )
    db = RecordingTransaction(interval)
    order = make_order(old_status)
    before = snapshot(order)
    order.status = new_status
    order.version += 1
    record_transition(db, order, action=action, actor_id=ACTOR_ID, reason="Основание", before=before, now=NOW)

    created = [item for item in db.added if isinstance(item, WorkOrderInterval)]
    if interval is not None:
        assert interval.end_at == (NOW if old_kind != new_kind else None)
    if new_kind is not None and old_kind != new_kind:
        assert len(created) == 1
        assert created[0].kind == new_kind
        assert created[0].work_order_id == ORDER_ID
        assert created[0].start_at == NOW
        assert created[0].end_at is None
    else:
        assert created == []


def test_review_audit_preserves_revision_identity_reason_and_system_actor():
    from app.modules.work_orders.events import record_transition

    submission_id = UUID("00000000-0000-0000-0000-000000000040")
    event = record_transition(
        RecordingTransaction(), make_order("REWORK"), action="request_rework", actor_id=None,
        reason="Недостаточно доказательств", before={"status": "AI_REVIEW"}, now=NOW, submission_id=submission_id,
    )
    assert event.actor_id is None
    assert event.reason == "Недостаточно доказательств"
    assert event.payload["submission_id"] == "00000000-0000-0000-0000-000000000040"
