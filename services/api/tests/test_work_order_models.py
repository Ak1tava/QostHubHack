from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.work_orders import schemas
from app.modules.work_orders.models import WorkOrder, WorkOrderEvent


def create_payload(**changes):
    return {
        "work_type": "planned",
        "description": "Ремонт насоса",
        "area_id": uuid4(),
        "equipment_id": uuid4(),
        "assignee_id": uuid4(),
        "due_at": datetime.now(timezone.utc) + timedelta(hours=1),
        **changes,
    }


def test_create_requires_one_complete_assignment_and_aware_time():
    command = schemas.WorkOrderCreate(**create_payload())
    assert command.priority == "normal"
    assert command.assignee_id is not None
    invalid = [
        {"assignee_id": None},
        {"brigade_id": uuid4(), "responsible_id": uuid4()},
        {"assignee_id": None, "brigade_id": uuid4()},
        {"responsible_id": uuid4()},
        {"due_at": datetime(2026, 10, 3)},
        {"description": "   "},
        {"master_id": uuid4()},
        {"status": "CLOSED"},
    ]
    for values in invalid:
        with pytest.raises(ValidationError):
            schemas.WorkOrderCreate(**create_payload(**values))
    brigade = schemas.WorkOrderCreate(
        **create_payload(assignee_id=None, brigade_id=uuid4(), responsible_id=uuid4())
    )
    assert brigade.brigade_id is not None


@pytest.mark.parametrize("action", ["reject", "pause", "reassign", "cancel"])
def test_actions_require_nonblank_reason(action):
    extra = {"assignee_id": uuid4()} if action == "reassign" else {}
    for reason in [None, "", "  "]:
        with pytest.raises(ValidationError):
            schemas.ActionCommand(action=action, expected_version=1, reason=reason, **extra)
    command = schemas.ActionCommand(
        action=action, expected_version=1, reason=" Причина ", **extra
    )
    assert command.reason == "Причина"


@pytest.mark.parametrize(
    "values",
    [
        {"action": "start", "expected_version": 0},
        {"action": "start", "reason": "Не используется"},
        {"action": "accept", "priority": None},
        {"action": "accept", "assignee_id": uuid4()},
        {"action": "reprioritize"},
        {"action": "reassign", "reason": "Замена"},
        {"action": "reassign", "reason": "Замена", "brigade_id": uuid4()},
        {"action": "submit"},
        {"action": "close"},
        {"action": "begin_review"},
        {"action": "start", "actor_id": uuid4()},
        {"action": "start", "source": "internal"},
    ],
)
def test_public_action_rejects_invalid_or_unconsumed_fields(values):
    with pytest.raises(ValidationError):
        schemas.ActionCommand(**{"expected_version": 1, **values})


def test_valid_public_action_variants():
    for action in ["accept", "queue", "start", "resume", "restart"]:
        assert schemas.ActionCommand(action=action, expected_version=1).action == action
    command = schemas.ActionCommand(
        action="reassign", expected_version=2, reason="Смена бригады",
        brigade_id=uuid4(), responsible_id=uuid4(),
    )
    assert command.responsible_id is not None
    assert schemas.ActionCommand(
        action="reprioritize", expected_version=2, priority="emergency"
    ).priority == "emergency"


def test_internal_action_requires_revision_and_rejects_actor_source():
    values = dict(
        action="begin_review", expected_version=3,
        assignment_version=1, submission_id=uuid4(),
    )
    assert schemas.InternalActionCommand(**values).submission_id == values["submission_id"]
    for bad in [{"assignment_version": 0}, {"actor_id": uuid4()}, {"source": "worker"}]:
        with pytest.raises(ValidationError):
            schemas.InternalActionCommand(**{**values, **bad})
    for action in ["request_rework", "override_close"]:
        with pytest.raises(ValidationError):
            schemas.InternalActionCommand(**{**values, "action": action})


def order_record(database, **changes):
    order = WorkOrder(
        number=f"T-{uuid4()}", work_type="planned", description="Ремонт",
        area_id=database["area"].id, equipment_id=database["equipment"].id,
        master_id=database["master"].id, due_at=datetime.now(timezone.utc),
        **{"assignee_id": database["worker"].id, **changes},
    )
    database["session"].add(order)
    database["session"].flush()
    return order


def test_db_prevents_second_active_order_across_assignment_types(database):
    order_record(database, status="IN_PROGRESS")
    with pytest.raises(IntegrityError):
        order_record(
            database, status="IN_PROGRESS", assignee_id=None,
            brigade_id=database["brigade"].id, responsible_id=database["worker"].id,
        )
    database["session"].rollback()


def test_db_allows_paused_and_active_order_for_same_worker(database):
    order_record(database, status="PAUSED")
    order_record(database, status="IN_PROGRESS")
    database["session"].commit()


def test_db_event_version_is_unique_per_order(database):
    order = order_record(database)
    values = dict(work_order_id=order.id, action="create", version=1, assignment_version=1)
    database["session"].add_all([WorkOrderEvent(**values), WorkOrderEvent(**values)])
    with pytest.raises(IntegrityError):
        database["session"].flush()
    database["session"].rollback()


def test_db_one_open_interval_per_order_and_nonnegative_duration(database):
    from app.modules.work_orders.models import WorkOrderInterval

    session = database["session"]
    order = order_record(database)
    now = datetime.now(timezone.utc)
    session.add(WorkOrderInterval(work_order_id=order.id, kind="active", start_at=now))
    session.flush()
    session.add(WorkOrderInterval(work_order_id=order.id, kind="pause", start_at=now))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    order = order_record(database)
    session.add(WorkOrderInterval(
        work_order_id=order.id, kind="review", start_at=now, end_at=now-timedelta(seconds=1),
    ))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_db_number_sequence_and_submission_default(database):
    from app.modules.catalog.models import WorkCode
    from app.modules.work_orders.models import ORDER_NUMBER_SEQUENCE, Submission

    session = database["session"]
    first = session.scalar(select(ORDER_NUMBER_SEQUENCE.next_value()))
    second = session.scalar(select(ORDER_NUMBER_SEQUENCE.next_value()))
    assert second > first
    order = order_record(database)
    submission = Submission(
        work_order_id=order.id, revision=1, worker_id=database["worker"].id,
        work_description="Готово", work_code_id=session.scalar(select(WorkCode.id)),
    )
    session.add(submission)
    session.flush()
    assert submission.no_materials_used is False


def test_db_idempotency_keys_are_scoped_to_actor(database):
    from app.modules.work_orders.models import IdempotencyRecord

    session = database["session"]
    session.add_all([
        IdempotencyRecord(actor_id=database[role].id, key="same-key", fingerprint="a" * 64)
        for role in ["master", "worker"]
    ])
    session.flush()
    session.add(IdempotencyRecord(
        actor_id=database["worker"].id, key="same-key", fingerprint="b" * 64,
    ))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_db_outbox_event_is_unique(database):
    from app.modules.work_orders.models import OutboxEvent

    session = database["session"]
    order = order_record(database)
    event = WorkOrderEvent(
        work_order_id=order.id, action="create", version=1, assignment_version=1,
    )
    session.add(event)
    session.flush()
    values = dict(
        event_id=event.id, work_order_id=order.id, version=1, assignment_version=1,
        type="work_order.created", payload={},
    )
    session.add_all([OutboxEvent(**values), OutboxEvent(**values)])
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_db_completed_intervals_can_share_a_boundary(database):
    from app.modules.work_orders.models import WorkOrderInterval

    session = database["session"]
    order = order_record(database)
    now = datetime.now(timezone.utc)
    session.add_all([
        WorkOrderInterval(work_order_id=order.id, kind="active", start_at=now, end_at=now),
        WorkOrderInterval(work_order_id=order.id, kind="pause", start_at=now),
    ])
    session.commit()
