"""HTTP reports preserve revisions, authorization and command atomicity."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from conftest import sign_in
from work_order_helpers import BASE, headers, seed_order, count_rows, add_user
from app.modules.catalog.models import Material, WorkCode
from app.modules.work_orders.models import (
    IdempotencyRecord, MaterialUsage, OutboxEvent, Photo, Submission, WorkOrder, WorkOrderEvent,
)


def payload(database, **changes):
    result = dict(expected_version=1, assignment_version=1, work_description="Заменён подшипник",
                  fault_code_id=str(database["session"].scalar(select(WorkCode.id))),
                  materials=[], no_materials_used=True, after_photo_ids=[], comment="Проверено")
    result.update(changes)
    return result


def send(client, token, order, body, key=None):
    return client.post(f"{BASE}/{order['id']}/submissions", json=body, headers=headers(token, key))


def add_photo(database, order, **changes):
    photo = Photo(work_order_id=UUID(order["id"]), uploaded_by=database["worker"].id,
                  type="after", storage_key=uuid4().hex, mime_type="image/jpeg", content_hash="f"*64,
                  **changes)
    database["session"].add(photo)
    database["session"].commit()
    return photo


def test_submission_route_is_registered(client, database):
    order = seed_order(database, "IN_PROGRESS")
    token = sign_in(client, "worker")
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert "submit" in detail["allowed_actions"]
    response = send(client, token, order, payload(database))
    assert response.status_code == 201, response.text


def test_materials_and_photos_are_saved_once_on_retry(client, database):
    order = seed_order(database, "IN_PROGRESS", work_type="emergency")
    photo = add_photo(database, order)
    mid = str(database["session"].scalar(select(Material.id)))
    body = payload(database, materials=[dict(material_id=mid, quantity="1.2500")],
                   no_materials_used=False, after_photo_ids=[str(photo.id)])
    token = sign_in(client, "worker")
    first = send(client, token, order, body, "report-retry")
    assert first.status_code == 201, first.text
    second = send(client, token, order, body, "report-retry")
    assert second.status_code == 201 and second.json() == first.json()
    report = first.json()
    assert report["revision"] == 1 and not report["missing_evidence"]
    assert report["work_description"] == body["work_description"]
    assert report["fault_code_id"] == body["fault_code_id"]
    assert report["comment"] == body["comment"]
    assert report["after_photo_ids"] == [str(photo.id)]
    assert report["materials"][0]["quantity"] == "1.2500"
    db = database["session"]
    assert count_rows(db, Submission) == count_rows(db, MaterialUsage) == 1
    assert count_rows(db, WorkOrderEvent) == count_rows(db, OutboxEvent) == 1
    saved_order = db.get(WorkOrder, UUID(order["id"]), populate_existing=True)
    assert (saved_order.status, saved_order.version) == ("SUBMITTED", 2)
    detail = client.get(f"{BASE}/{order['id']}").json()
    assert detail["submission"] == report


@pytest.mark.parametrize("change", [
    {"materials": [], "no_materials_used": False},
    {"work_description": "  "}, {"fault_code_id": str(uuid4())},
    {"after_photo_ids": [str(uuid4())]}, {"expected_version": 2},
    {"assignment_version": 2}, {"extra": "forbidden"},
])
def test_invalid_report_rolls_back_all_artifacts(client, database, change):
    order = seed_order(database, "IN_PROGRESS")
    response = send(client, sign_in(client, "worker"), order, payload(database, **change), "bad-report")
    assert response.status_code in (409, 422), response.text
    db = database["session"]
    for model in [Submission, MaterialUsage, WorkOrderEvent, OutboxEvent, IdempotencyRecord]:
        assert count_rows(db, model) == 0
    assert db.get(WorkOrder, UUID(order["id"]), populate_existing=True).status == "IN_PROGRESS"


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity", "0.00001", "10000000000"])
def test_invalid_quantity_is_rejected(client, database, quantity):
    order = seed_order(database, "IN_PROGRESS")
    mid = str(database["session"].scalar(select(Material.id)))
    body = payload(database, materials=[dict(material_id=mid, quantity=quantity)], no_materials_used=False)
    assert send(client, sign_in(client, "worker"), order, body).status_code == 422


@pytest.mark.parametrize("conflict", ["duplicate", "no_materials", "unknown"])
def test_invalid_material_combination_is_rejected(client, database, conflict):
    order = seed_order(database, "IN_PROGRESS")
    mid = str(database["session"].scalar(select(Material.id))) if conflict != "unknown" else str(uuid4())
    materials = [dict(material_id=mid, quantity="1")]
    if conflict == "duplicate":
        materials *= 2
    body = payload(database, materials=materials, no_materials_used=conflict == "no_materials")
    assert send(client, sign_in(client, "worker"), order, body).status_code == 422


@pytest.mark.parametrize("bad_photo", ["foreign_order", "before", "foreign_author", "duplicate"])
def test_photo_references_are_checked(client, database, bad_photo):
    order = seed_order(database, "IN_PROGRESS")
    other = seed_order(database, "ISSUED") if bad_photo == "foreign_order" else order
    photo = add_photo(database, other)
    if bad_photo == "before": photo.type = "before"
    if bad_photo == "foreign_author": photo.uploaded_by = database["master"].id
    database["session"].commit()
    ids = [str(photo.id)] * (2 if bad_photo == "duplicate" else 1)
    assert send(client, sign_in(client, "worker"), order, payload(database, after_photo_ids=ids)).status_code == 422


def test_emergency_missing_photo_is_recorded_as_evidence_gap(client, database):
    order = seed_order(database, "IN_PROGRESS", work_type="emergency")
    result = send(client, sign_in(client, "worker"), order, payload(database))
    assert result.status_code == 201, result.text
    assert result.json()["missing_evidence"] == ["after_photo"]


@pytest.mark.parametrize("login,status", [("master",403), ("outsider",404)])
def test_report_requires_responsible_worker(client, database, login, status):
    order = seed_order(database, "IN_PROGRESS")
    assert send(client, sign_in(client, login), order, payload(database)).status_code == status


def test_brigade_member_cannot_submit_for_responsible_worker(client, database):
    add_user(database, "member", brigade_id=database["brigade"].id)
    order = seed_order(database, "IN_PROGRESS", assignee_id=None, brigade_id=database["brigade"].id,
                       responsible_id=database["worker"].id)
    assert send(client, sign_in(client, "member"), order, payload(database)).status_code == 403


def test_replay_rechecks_current_assignment(client, database):
    order = seed_order(database, "IN_PROGRESS")
    body = payload(database)
    token = sign_in(client, "worker")
    assert send(client, token, order, body, "original").status_code == 201
    db = database["session"]
    changed = db.get(WorkOrder, UUID(order["id"]))
    changed.assignee_id = database["outsider"].id
    changed.assignment_version += 1
    db.commit()
    assert send(client, token, order, body, "original").status_code == 404


def test_key_conflict_and_new_revision_preserve_old_evidence(client, database):
    order = seed_order(database, "IN_PROGRESS")
    photo = add_photo(database, order)
    body = payload(database, after_photo_ids=[str(photo.id)])
    token = sign_in(client, "worker")
    first = send(client, token, order, body, "revision-one")
    assert first.status_code == 201, first.text
    assert send(client, token, order, {**body,"comment":"изменено"}, "revision-one").status_code == 409
    db = database["session"]
    saved = db.get(WorkOrder, UUID(order["id"]))
    saved.status = "REWORK"
    db.commit()
    from work_order_helpers import succeed
    restarted = succeed(client, token, {"id":order["id"],"version":2}, "restart")
    attempt = payload(database, expected_version=restarted["version"], after_photo_ids=[str(photo.id)])
    assert send(client, token, order, attempt, "revision-two").status_code == 422
    photo2 = add_photo(database, order)
    second = send(client, token, order, {**attempt,"after_photo_ids":[str(photo2.id)]}, "revision-two")
    assert second.status_code == 201 and second.json()["revision"] == 2
    assert db.get(Photo, photo.id, populate_existing=True).submission_id == UUID(first.json()["id"])
    assert count_rows(db, Submission) == 2


def test_csrf_and_authentication_protect_submission(client, database):
    order = seed_order(database, "IN_PROGRESS")
    body = payload(database)
    assert send(client, "invalid", order, body).status_code == 401
    sign_in(client, "worker")
    assert send(client, "invalid", order, body).status_code == 403


def test_report_is_not_accepted_through_generic_actions(client, database):
    order = seed_order(database, "IN_PROGRESS")
    response = client.post(f"{BASE}/{order['id']}/actions", json={"action":"submit","expected_version":1},
                           headers=headers(sign_in(client, "worker")))
    assert response.status_code == 422


@pytest.mark.parametrize("status", ["ISSUED", "PAUSED", "SUBMITTED", "CLOSED", "CANCELLED"])
def test_invalid_transition_rolls_back_new_revision(client, database, status):
    order = seed_order(database, status)
    result = send(client, sign_in(client, "worker"), order, payload(database))
    assert result.status_code == 409, result.text
    for model in [Submission, MaterialUsage, WorkOrderEvent, OutboxEvent, IdempotencyRecord]:
        assert count_rows(database["session"], model) == 0


def test_event_failure_rolls_back_report_materials_and_photo(client, database, monkeypatch):
    from app.modules.work_orders import events
    order = seed_order(database, "IN_PROGRESS")
    photo = add_photo(database, order)
    mid = str(database["session"].scalar(select(Material.id)))
    token = sign_in(client, "worker")
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic event failure")
    monkeypatch.setattr(events, "record_transition", fail)
    with pytest.raises(RuntimeError, match="synthetic event failure"):
        send(client, token, order, payload(database, after_photo_ids=[str(photo.id)],
             materials=[dict(material_id=mid, quantity="1")], no_materials_used=False), "atomic-fail")
    db = database["session"]
    assert db.get(Photo, photo.id, populate_existing=True).submission_id is None
    assert db.get(WorkOrder, UUID(order["id"]), populate_existing=True).status == "IN_PROGRESS"
    for model in [Submission, MaterialUsage, WorkOrderEvent, OutboxEvent, IdempotencyRecord]:
        assert count_rows(db, model) == 0


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_submits_create_one_revision(database, same_key):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from app.core.security import AuthError
    from app.modules.auth.models import User
    from app.modules.work_orders.schemas import SubmissionCreate
    from app.modules.work_orders.submissions import SubmissionService
    order = seed_order(database, "IN_PROGRESS")
    body = SubmissionCreate.model_validate(payload(database))
    worker_id = database["worker"].id
    barrier = Barrier(2)
    def submit(index):
        with Session(database["engine"], expire_on_commit=False) as db:
            actor = db.get(User, worker_id)
            barrier.wait(timeout=10)
            try:
                return SubmissionService(db).submit_order(UUID(order["id"]), actor, body,
                       "concurrent" if same_key else f"concurrent-{index}").id
            except AuthError as exc:
                assert exc.status_code == 409
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [1,2]))
    assert len(set(results) - {None}) == 1
    assert sum(item is not None for item in results) == (2 if same_key else 1)
    for model in [Submission, WorkOrderEvent, OutboxEvent]:
        assert count_rows(database["session"], model) == 1
