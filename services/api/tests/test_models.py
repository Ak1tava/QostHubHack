from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError


def order_fields(db):
    return dict(
        number="W001",
        work_type="planned",
        description="Ремонт",
        area_id=db["area"].id,
        equipment_id=db["equipment"].id,
        master_id=db["master"].id,
        due_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="ISSUED",
    )


@pytest.mark.parametrize("assignment", [{}, {"both": True}])
def test_order_requires_exactly_one_assignment(database, assignment):
    from app.modules.work_orders.models import WorkOrder

    values = order_fields(database)
    if assignment:
        values.update(
            assignee_id=database["worker"].id,
            brigade_id=database["brigade"].id,
            responsible_id=database["worker"].id,
        )
    database["session"].add(WorkOrder(**values))
    with pytest.raises(IntegrityError):
        database["session"].commit()
    database["session"].rollback()


def test_brigade_requires_responsible_worker(database):
    from app.modules.work_orders.models import WorkOrder

    database["session"].add(
        WorkOrder(**order_fields(database), brigade_id=database["brigade"].id)
    )
    with pytest.raises(IntegrityError):
        database["session"].commit()
    database["session"].rollback()


def test_material_quantity_must_be_positive(database):
    from sqlalchemy import select

    from app.modules.catalog.models import Material, MaterialNorm, WorkCode

    s = database["session"]
    s.add(
        MaterialNorm(
            equipment_id=database["equipment"].id,
            work_code_id=s.scalar(select(WorkCode.id)),
            material_id=s.scalar(select(Material.id)),
            quantity=0,
        )
    )
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_submission_revision_unique_per_order(database):
    from sqlalchemy import select

    from app.modules.catalog.models import WorkCode
    from app.modules.work_orders.models import Submission, WorkOrder

    s = database["session"]
    order = WorkOrder(**order_fields(database), assignee_id=database["worker"].id)
    s.add(order)
    s.flush()
    values = dict(
        work_order_id=order.id,
        revision=1,
        worker_id=database["worker"].id,
        work_description="Ремонт выполнен",
        work_code_id=s.scalar(select(WorkCode.id)),
    )
    s.add_all([Submission(**values), Submission(**values)])
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_order_rejects_unknown_status(database):
    from app.modules.work_orders.models import WorkOrder

    values = order_fields(database)
    values["status"] = "made-up"
    database["session"].add(WorkOrder(**values, assignee_id=database["worker"].id))
    with pytest.raises(IntegrityError):
        database["session"].commit()
    database["session"].rollback()
