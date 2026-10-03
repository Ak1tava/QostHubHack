"""Internal transitions require persisted evidence, never browser authority."""
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
from uuid import uuid4

import pytest
from sqlalchemy import select


def test_internal_kernel_exists():
    assert find_spec("app.modules.work_orders.internal") is not None


def make_order(database, status="IN_PROGRESS", work_type="planned"):
    from app.modules.work_orders.models import WorkOrder
    order = WorkOrder(
        number=str(uuid4()), work_type=work_type, description="Ремонт",
        area_id=database["area"].id, equipment_id=database["equipment"].id,
        assignee_id=database["worker"].id, master_id=database["master"].id,
        due_at=datetime.now(timezone.utc) + timedelta(hours=1), status=status,
    )
    database["session"].add(order)
    database["session"].commit()
    return order


def make_submission(database, order, revision=1):
    from app.modules.catalog.models import WorkCode
    from app.modules.work_orders.models import Submission
    db = database["session"]
    report = Submission(
        work_order_id=order.id, revision=revision, assignment_version=order.assignment_version,
        worker_id=database["worker"].id, work_description="Заменён узел",
        work_code_id=db.scalar(select(WorkCode.id)), no_materials_used=True,
    )
    db.add(report)
    db.flush()
    return report


def command(order, report, action, **kw):
    from app.modules.work_orders.schemas import InternalActionCommand
    return InternalActionCommand(
        action=action, expected_version=order.version,
        assignment_version=order.assignment_version, submission_id=report.id, **kw,
    )


def kernel(database):
    from app.modules.work_orders.internal import apply_internal
    return lambda oid, cmd, actor=None: apply_internal(database["session"], oid, cmd, actor=actor)


def test_submit_review_close_requires_master_decision(database):
    from app.core.security import AuthError
    from app.modules.work_orders.models import MasterDecision, WorkOrderEvent, OutboxEvent
    order = make_order(database)
    report = make_submission(database, order)
    run = kernel(database)
    run(order.id, command(order, report, "submit"), database["worker"])
    assert order.status == "SUBMITTED"
    run(order.id, command(order, report, "begin_review"))
    assert order.status == "AI_REVIEW"
    with pytest.raises(AuthError) as exc:
        run(order.id, command(order, report, "close"), database["master"])
    assert exc.value.status_code == 422
    decision = MasterDecision(work_order_id=order.id, submission_id=report.id,
                              master_id=database["master"].id, decision="accept")
    database["session"].add(decision)
    database["session"].flush()
    run(order.id, command(order, report, "close", decision_id=decision.id), database["master"])
    assert order.status == "CLOSED"
    events = list(database["session"].scalars(select(WorkOrderEvent)))
    assert [e.action for e in events] == ["submit", "begin_review", "close"]
    assert len(list(database["session"].scalars(select(OutboxEvent)))) == 3


def test_emergency_report_without_photo_cannot_close(database):
    from app.core.security import AuthError
    from app.modules.work_orders.models import MasterDecision
    order = make_order(database, "AI_REVIEW", "emergency")
    report = make_submission(database, order)
    decision = MasterDecision(work_order_id=order.id, submission_id=report.id,
                              master_id=database["master"].id, decision="accept")
    database["session"].add(decision)
    database["session"].flush()
    with pytest.raises(AuthError) as exc:
        kernel(database)(order.id, command(order, report, "close", decision_id=decision.id), database["master"])
    assert exc.value.status_code == 409
    assert order.status == "AI_REVIEW"


def test_internal_stale_assignment_and_fake_worker_authority(database):
    from app.core.security import AuthError
    order = make_order(database, "SUBMITTED")
    report = make_submission(database, order)
    with pytest.raises(AuthError) as exc:
        kernel(database)(order.id, command(order, report, "begin_review"), database["worker"])
    assert exc.value.status_code == 403
    stale = command(order, report, "begin_review")
    order.assignment_version += 1
    database["session"].flush()
    with pytest.raises(AuthError) as exc:
        kernel(database)(order.id, stale)
    assert exc.value.status_code == 409


def test_internal_caller_rollback_removes_submission_event_and_outbox(database):
    from app.modules.work_orders.models import Submission, WorkOrder, WorkOrderEvent, OutboxEvent
    db = database["session"]
    order = make_order(database)
    oid = order.id
    report = make_submission(database, order)
    kernel(database)(oid, command(order, report, "submit"), database["worker"])
    db.rollback()
    assert db.get(WorkOrder, oid).status == "IN_PROGRESS"
    for model in (Submission, WorkOrderEvent, OutboxEvent):
        assert list(db.scalars(select(model))) == []


def make_review(database, order, report, **overrides):
    from app.modules.work_orders.models import AIReview
    fields = dict(submission_id=report.id, order_version=order.version,
                  assignment_version=order.assignment_version, verdict="requires_rework",
                  result={"findings": [{"code": "incomplete", "message": "Нужна доработка"}]},
                  model="test", prompt_version="1")
    fields.update(overrides)
    review = AIReview(**fields)
    database["session"].add(review)
    database["session"].flush()
    return review


@pytest.mark.parametrize("overrides", [
    {"order_version": 9}, {"assignment_version": 9},
    {"verdict": "accepted"}, {"result": {"findings": []}},
])
def test_rework_rejects_stale_or_unsubstantiated_ai_review(database, overrides):
    from app.core.security import AuthError
    order = make_order(database, "AI_REVIEW")
    report = make_submission(database, order)
    review = make_review(database, order, report, **overrides)
    with pytest.raises(AuthError) as exc:
        kernel(database)(order.id, command(order, report, "request_rework",
                                          review_id=review.id, reason="Нужна доработка"))
    assert exc.value.status_code == 409
    assert order.status == "AI_REVIEW"


def test_rework_with_current_review_preserves_report_and_cannot_close_as_system(database):
    from app.core.security import AuthError
    from app.modules.work_orders.models import Submission
    order = make_order(database, "AI_REVIEW")
    report = make_submission(database, order)
    review = make_review(database, order, report)
    kernel(database)(order.id, command(order, report, "request_rework", review_id=review.id,
                                      reason="Нужна доработка"))
    assert order.status == "REWORK"
    assert database["session"].get(Submission, report.id).work_description == "Заменён узел"
    with pytest.raises(AuthError) as exc:
        kernel(database)(order.id, command(order, report, "override_close", reason="Проверено"))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("mismatch", ["master", "submission", "kind", "reason"])
def test_master_decision_must_match_actor_report_action_and_reason(database, mismatch):
    from app.core.security import AuthError
    from app.modules.work_orders.models import MasterDecision
    order = make_order(database, "REWORK")
    older = make_submission(database, order)
    report = make_submission(database, order, revision=2)
    decision = MasterDecision(
        work_order_id=order.id, submission_id=older.id if mismatch == "submission" else report.id,
        master_id=database["outsider"].id if mismatch == "master" else database["master"].id,
        decision="rework" if mismatch == "kind" else "accept",
        reason="Другая причина" if mismatch == "reason" else "Проверено",
    )
    database["session"].add(decision)
    database["session"].flush()
    with pytest.raises(AuthError) as exc:
        kernel(database)(order.id, command(order, report, "override_close", decision_id=decision.id,
                                          reason="Проверено"), database["master"])
    assert exc.value.status_code == 422
    assert order.status == "REWORK"


def test_new_submission_revision_required_after_rework(database):
    from app.core.security import AuthError
    from app.modules.work_orders.schemas import ActionCommand
    from app.modules.work_orders.service import WorkOrderService
    order = make_order(database)
    report = make_submission(database, order)
    run = kernel(database)
    run(order.id, command(order, report, "submit"), database["worker"])
    run(order.id, command(order, report, "begin_review"))
    review = make_review(database, order, report)
    run(order.id, command(order, report, "request_rework", review_id=review.id, reason="Доработка"))
    database["session"].commit()
    WorkOrderService(database["session"]).apply_action(order.id, database["worker"],
        ActionCommand(action="restart", expected_version=order.version), "restart")
    with pytest.raises(AuthError) as exc:
        run(order.id, command(order, report, "submit"), database["worker"])
    assert exc.value.status_code == 409
    newer = make_submission(database, order, revision=2)
    run(order.id, command(order, newer, "submit"), database["worker"])
    assert order.status == "SUBMITTED"
