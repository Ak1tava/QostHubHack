"""Hand-calculated historical reports, access boundaries and real seed insights."""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import sign_in
from app.modules.catalog.models import Equipment, Material, MaterialNorm, WorkCode
from app.modules.work_orders.models import (
    DowntimeInterval, MasterDecision, MaterialUsage, Submission, WorkOrder,
    WorkOrderEvent, WorkOrderInterval,
)

START = datetime(2026, 9, 1, 20, tzinfo=timezone.utc)
END = START + timedelta(hours=8)
PARAMS = {"start_at": START.isoformat(), "end_at": END.isoformat()}


def test_all_reporting_routes_require_session_before_reading_history():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.db import get_db
    # No cookie means authentication needs no DB read; fail on any unexpected query.
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as unauthenticated:
            for route in ("/reports/shift", "/reports/rating", "/analytics/anomalies"):
                response = unauthenticated.get("/api/v1" + route, params=PARAMS)
                assert response.status_code == 401
                assert response.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


def test_interval_union_clips_overlaps_and_open_interval():
    import importlib.util
    assert importlib.util.find_spec("app.modules.analytics.queries") is not None, "Reporting queries are missing"
    from app.modules.analytics.queries import merged_seconds
    spans = [(START - timedelta(hours=1), START + timedelta(hours=2)),
             (START + timedelta(hours=1), START + timedelta(hours=4)),
             (START + timedelta(hours=6), None)]
    assert merged_seconds(spans, START, END) == 21600


def order(database, *, at=START, due=None, worker=None, equipment=None, **kwargs):
    row = WorkOrder(
        number="AN-" + uuid4().hex, description="Синтетическая работа",
        work_type=kwargs.pop("work_type", "planned"),
        status=kwargs.pop("status", "CLOSED"), area_id=kwargs.pop("area_id", database["area"].id),
        equipment_id=(equipment or database["equipment"]).id,
        assignee_id=(worker or database["worker"]).id, master_id=database["master"].id,
        due_at=due or at + timedelta(hours=2), created_at=at, **kwargs,
    )
    db = database["session"]
    db.add(row)
    db.flush()
    event(database, row, at, "created", "ISSUED")
    return row


def event(database, row, at, action, status, **state):
    values = dict(status=status, due_at=row.due_at.isoformat(),
                  assignee_id=str(row.assignee_id) if row.assignee_id else None,
                  responsible_id=str(row.responsible_id) if row.responsible_id else None,
                  brigade_id=str(row.brigade_id) if row.brigade_id else None)
    values.update(state)
    events = list(database["session"].scalars(select(WorkOrderEvent).where(
        WorkOrderEvent.work_order_id == row.id).order_by(WorkOrderEvent.version)))
    before = events[-1].payload["after"] if events else {}
    database["session"].add(WorkOrderEvent(
        work_order_id=row.id, action=action, version=len(events) + 1,
        assignment_version=1, actor_id=database["master"].id,
        payload={"before": before, "after": values}, occurred_at=at,
    ))
    database["session"].flush()


def submission(database, row, *, at=None, worker=None, revision=1, score=5, accepted=True):
    db = database["session"]
    code = db.scalar(select(WorkCode))
    report = Submission(work_order_id=row.id, revision=revision, assignment_version=1,
                        worker_id=(worker or database["worker"]).id,
                        work_description="Ремонт", work_code_id=code.id,
                        no_materials_used=True, submitted_at=at or row.created_at + timedelta(hours=1))
    db.add(report)
    db.flush()
    event(database, row, report.submitted_at, "submit", "SUBMITTED")
    decision_at = report.submitted_at + timedelta(minutes=10)
    db.add(MasterDecision(work_order_id=row.id, submission_id=report.id,
                          master_id=database["master"].id, decision="accept" if accepted else "rework",
                          score=score, decided_at=decision_at))
    event(database, row, decision_at, "close" if accepted else "request_rework",
          "CLOSED" if accepted else "REWORK")
    db.flush()
    return report


def report(client, login="master", params=None, route="/reports/shift"):
    sign_in(client, login)
    response = client.get("/api/v1" + route, params=params or PARAMS)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_midnight_distinct_revision_counts_and_clipped_intervals(client, database):
    db = database["session"]
    row = order(database)
    submission(database, row, accepted=False)
    submission(database, row, at=START + timedelta(hours=3), revision=2)
    event(database, row, START + timedelta(hours=4), "reject", "REJECTED")
    for kind, begin, finish in [("active", -1, 1), ("pause", 1, 2), ("review", 7, 9)]:
        db.add(WorkOrderInterval(work_order_id=row.id, kind=kind,
                                start_at=START + timedelta(hours=begin), end_at=START + timedelta(hours=finish)))
    for begin, finish in [(-2, 2), (1, 4), (6, 9)]:
        db.add(DowntimeInterval(equipment_id=row.equipment_id, work_order_id=row.id,
                                start_at=START + timedelta(hours=begin), end_at=START + timedelta(hours=finish), reason="Тест"))
    order(database, at=END)
    db.commit()
    result = report(client)
    assert result["counts"] == dict(issued=1, performed=1, closed=1, overdue=1, rejected=1)
    assert result["workload"] == dict(active_seconds=3600, pause_seconds=3600, review_seconds=3600)
    assert result["downtime"] == dict(seconds=21600, has_data=True)


def test_historical_overdue_survives_closed_status_and_due_extension(client, database):
    row = order(database, at=START - timedelta(hours=3), due=START - timedelta(hours=1))
    event(database, row, START + timedelta(hours=1), "change_due", "IN_PROGRESS", due_at=(END + timedelta(hours=1)).isoformat())
    submission(database, row, at=START + timedelta(hours=2))
    row.due_at = END + timedelta(hours=1)
    database["session"].commit()
    assert report(client)["counts"] == dict(issued=0, performed=1, closed=1, overdue=1, rejected=0)


def test_shift_uses_its_historical_boundaries_not_user_current_shift(client, database):
    shift = database["shift"]
    shift.start_at, shift.end_at = START, END
    order(database)
    database["session"].commit()
    result = report(client, params={"shift_id": str(shift.id)})
    assert result["counts"]["issued"] == 1
    assert datetime.fromisoformat(result["period"]["start_at"].replace("Z", "+00:00")) == START


@pytest.mark.parametrize("params", [{}, {"start_at": START.isoformat()},
    {"start_at": END.isoformat(), "end_at": START.isoformat()},
    {"start_at": "2026-09-01T00:00:00", "end_at": END.isoformat()},
    {**PARAMS, "shift_id": str(uuid4())}, {**PARAMS, "as_of": END.isoformat()}])
def test_invalid_period_and_client_clock_are_c1_errors(client, params):
    sign_in(client, "master")
    response = client.get("/api/v1/reports/shift", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.headers["cache-control"] == "no-store"


def test_scope_precedes_counts_and_worker_brigade_cannot_leak(client, database):
    own = order(database)
    submission(database, own)
    foreign = order(database, worker=database["outsider"], area_id=database["other_area"].id,
                    equipment=database["session"].scalar(select(Equipment).where(Equipment.area_id == database["other_area"].id)))
    submission(database, foreign, worker=database["outsider"])
    teammate = order(database, worker=database["outsider"])
    teammate.assignee_id = None
    teammate.brigade_id = database["brigade"].id
    teammate.responsible_id = database["outsider"].id
    # Persist matching assignment history rather than relying on current fields.
    event(database, teammate, START, "reassign", "ISSUED", assignee_id=None,
          responsible_id=str(database["outsider"].id), brigade_id=str(database["brigade"].id))
    submission(database, teammate, worker=database["outsider"])
    database["session"].commit()
    assert report(client)["counts"]["closed"] == 2
    own_result = report(client, "worker")
    assert own_result["counts"]["closed"] == 1
    assert own_result["counts"]["performed"] == 1
    sign_in(client, "worker")
    for route in ("/reports/shift", "/reports/rating"):
        response = client.get("/api/v1" + route, params={**PARAMS, "assignee_id": str(database["outsider"].id)})
        assert response.status_code == 404
    assert client.get("/api/v1/analytics/anomalies", params=PARAMS).status_code == 403
    sign_in(client, "master")
    assert client.get("/api/v1/reports/shift", params={**PARAMS, "area_id": str(database["other_area"].id)}).status_code == 404


@pytest.mark.parametrize("route", ["/reports/shift", "/reports/rating"])
def test_worker_foreign_assignee_404_does_not_reveal_same_brigade_peer(client, database, route):
    from app.modules.auth.models import User, UserArea
    peer = User(login="analytics-peer", display_name="Коллега по бригаде", role="worker",
                password_hash=database["worker"].password_hash, brigade_id=database["brigade"].id,
                shift_id=database["shift"].id, specialty="Слесарь")
    db = database["session"]
    db.add(peer)
    db.flush()
    db.add(UserArea(user_id=peer.id, area_id=database["area"].id))
    own = order(database)
    submission(database, own)
    other = order(database, worker=peer)
    submission(database, other, worker=peer)
    db.commit()
    sign_in(client, "worker")
    own_response = client.get("/api/v1" + route, params={**PARAMS, "assignee_id": str(database["worker"].id)})
    assert own_response.status_code == 200, own_response.text
    errors = []
    for foreign_id in (peer.id, uuid4()):
        response = client.get("/api/v1" + route, params={**PARAMS, "assignee_id": str(foreign_id)})
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["error"]["code"] == "not_found"
        assert "Коллега" not in response.text
        errors.append(response.json())
    assert errors[0] == errors[1]
    forbidden = client.get("/api/v1" + route, params={**PARAMS, "brigade_id": str(uuid4())})
    assert forbidden.status_code == 403


def test_empty_data_and_authentication(client):
    assert client.get("/api/v1/reports/shift", params=PARAMS).status_code == 401
    result = report(client)
    assert result["counts"] == dict(issued=0, performed=0, closed=0, overdue=0, rejected=0)
    assert result["downtime"] == dict(seconds=0, has_data=False)


def test_anomalies_use_history_before_period_and_exact_norm(client, database):
    db = database["session"]
    previous = order(database, at=START - timedelta(days=2))
    submission(database, previous)
    latest = order(database, at=START, work_type="emergency")
    sub = submission(database, latest)
    material = db.scalar(select(Material))
    db.add(MaterialUsage(submission_id=sub.id, material_id=material.id, quantity=Decimal("1.0001")))
    db.add(MaterialNorm(equipment_id=latest.equipment_id, work_code_id=sub.work_code_id,
                        material_id=material.id, quantity=Decimal("1.0000")))
    extra_equipment = Equipment(name="Без нормы", area_id=database["area"].id)
    db.add(extra_equipment)
    db.flush()
    missing_norm = order(database, at=START + timedelta(hours=2), equipment=extra_equipment)
    extra = submission(database, missing_norm)
    db.add(MaterialUsage(submission_id=extra.id, material_id=material.id, quantity=Decimal("100")))
    db.commit()
    result = report(client, route="/analytics/anomalies")
    types = {x["type"] for x in result["items"]}
    assert types == {"repeat_fault", "after_planned", "material_overuse"}
    excessive = [x for x in result["items"] if x["type"] == "material_overuse"]
    assert len(excessive) == 1
    assert excessive[0]["evidence_order_ids"] == [str(latest.id)]
    assert excessive[0]["metrics"]["actual"] == 1.0001


def test_after_planned_selects_only_nearest_emergency(client, database):
    planned = order(database, at=START - timedelta(days=1))
    submission(database, planned, at=START - timedelta(hours=23))
    nearest = order(database, at=START, work_type="emergency")
    submission(database, nearest)
    later = order(database, at=START + timedelta(hours=2), work_type="emergency")
    submission(database, later)
    database["session"].commit()
    anomalies = report(client, route="/analytics/anomalies")["items"]
    after = [a for a in anomalies if a["type"] == "after_planned"]
    assert [a["evidence_order_ids"] for a in after] == [[str(planned.id), str(nearest.id)]]


def test_after_planned_nearest_emergency_may_be_unclosed(client, database):
    planned = order(database, at=START - timedelta(days=1))
    submission(database, planned, at=START - timedelta(hours=23))
    nearest = order(database, at=START, work_type="emergency", status="ISSUED")
    later = order(database, at=START + timedelta(hours=2), work_type="emergency")
    submission(database, later)
    database["session"].commit()
    after = [a for a in report(client, route="/analytics/anomalies")["items"] if a["type"] == "after_planned"]
    assert [a["evidence_order_ids"] for a in after] == [[str(planned.id), str(nearest.id)]]


@pytest.mark.parametrize("hours, expected", [(48, 1), (48.0001, 0)])
def test_after_planned_48h_boundary(client, database, hours, expected):
    planned = order(database, at=START - timedelta(days=3))
    submission(database, planned, at=START - timedelta(hours=hours, minutes=10))
    emergency = order(database, work_type="emergency")
    submission(database, emergency)
    database["session"].commit()
    after = [a for a in report(client, route="/analytics/anomalies")["items"] if a["type"] == "after_planned"]
    assert len(after) == expected


def test_repeat_uses_occurrence_order_even_when_older_repair_accepted_later(client, database):
    prior = order(database, at=START - timedelta(days=7))
    submission(database, prior, at=START + timedelta(hours=4))
    latest = order(database, work_type="emergency")
    submission(database, latest)
    database["session"].commit()
    repeats = [a for a in report(client, route="/analytics/anomalies")["items"] if a["type"] == "repeat_fault"]
    assert [a["evidence_order_ids"] for a in repeats] == [[str(prior.id), str(latest.id)]]
    assert repeats[0]["metrics"]["hours_between"] == 168


def test_future_period_clips_open_workload_and_downtime_to_server_clock(client, database, monkeypatch):
    from app.modules.analytics import router
    fixed_now = START + timedelta(hours=2)
    class FixedClock:
        @staticmethod
        def now(tz):
            return fixed_now
    monkeypatch.setattr(router, "datetime", FixedClock)
    row = order(database, status="IN_PROGRESS")
    event(database, row, START, "start", "IN_PROGRESS")
    db = database["session"]
    db.add(WorkOrderInterval(work_order_id=row.id, kind="active", start_at=START, end_at=None))
    db.add(DowntimeInterval(equipment_id=row.equipment_id, work_order_id=row.id,
                            start_at=START, end_at=None, reason="Тест"))
    # A future submission/decision must not make today's work performed/closed.
    submission(database, row, at=END + timedelta(hours=1))
    db.commit()
    result = report(client)
    assert result["workload"]["active_seconds"] == 7200
    assert result["downtime"]["seconds"] == 7200
    assert result["counts"]["performed"] == result["counts"]["closed"] == 0
    assert datetime.fromisoformat(result["period"]["as_of"].replace("Z", "+00:00")) == fixed_now


def test_foreign_and_unlinked_downtime_do_not_leak_to_worker(client, database):
    db = database["session"]
    own = order(database)
    submission(database, own)
    eq2 = db.scalar(select(Equipment).where(Equipment.area_id == database["other_area"].id))
    for equipment in (database["equipment"], eq2):
        db.add(DowntimeInterval(equipment_id=equipment.id, work_order_id=None,
                                start_at=START, end_at=END, reason="Тест"))
    db.commit()
    assert report(client)["downtime"]["seconds"] == 28800
    assert report(client, "worker")["downtime"] == dict(seconds=0, has_data=False)


@pytest.mark.parametrize("role", ["master", "manager", "admin"])
@pytest.mark.parametrize("order_hour", [1, 3])
def test_leadership_downtime_before_issuance_has_linked_unlinked_parity(client, database, role, order_hour):
    database["master"].role = role
    row = order(database, at=START + timedelta(hours=order_hour))
    interval = DowntimeInterval(equipment_id=row.equipment_id, work_order_id=row.id,
                                start_at=START, end_at=START + timedelta(hours=2), reason="Остановка до оформления")
    db = database["session"]
    db.add(interval)
    db.commit()
    linked = report(client)["downtime"]
    assert linked == dict(seconds=7200, has_data=True)
    interval.work_order_id = None
    db.commit()
    assert report(client)["downtime"] == linked


def test_downtime_assignment_filters_preserve_worker_and_brigade_privacy(client, database):
    own = order(database, at=START + timedelta(hours=1))
    own.assignee_id = None
    own.brigade_id = database["brigade"].id
    own.responsible_id = database["worker"].id
    event(database, own, own.created_at, "reassign", "ISSUED")
    teammate = order(database, at=START + timedelta(hours=3), worker=database["outsider"])
    teammate.assignee_id = None
    teammate.brigade_id = database["brigade"].id
    teammate.responsible_id = database["outsider"].id
    event(database, teammate, teammate.created_at, "reassign", "ISSUED")
    db = database["session"]
    for row, begin, finish in [(own, 0, 2), (None, 2, 3), (teammate, 3, 6)]:
        db.add(DowntimeInterval(equipment_id=database["equipment"].id, work_order_id=row.id if row else None,
                                start_at=START + timedelta(hours=begin), end_at=START + timedelta(hours=finish),
                                reason="Синтетический простой"))
    db.commit()
    assert report(client)["downtime"] == dict(seconds=21600, has_data=True)
    assert report(client, params={**PARAMS, "assignee_id": str(database["worker"].id)})["downtime"] == dict(seconds=3600, has_data=True)
    assert report(client, params={**PARAMS, "brigade_id": str(database["brigade"].id)})["downtime"] == dict(seconds=14400, has_data=True)
    assert report(client, "worker")["downtime"] == dict(seconds=3600, has_data=True)
    assert report(client, "worker", params={**PARAMS, "brigade_id": str(database["brigade"].id)})["downtime"] == dict(seconds=3600, has_data=True)


def test_real_t09_patterns_are_detected_without_runtime_expected_file(client, database, tmp_path, monkeypatch):
    from app.seed_demo import build_dataset, load_dataset
    from app.modules.auth.models import UserArea
    db = database["session"]
    load_dataset(db, build_dataset(42, date(2026, 10, 4)), password="synthetic-test-only", photo_root=tmp_path)
    areas = set(db.scalars(select(UserArea.area_id)))
    for area in areas - {database["area"].id}:
        db.add(UserArea(user_id=database["master"].id, area_id=area))
    db.commit()
    original_open = Path.open
    def deny_expected_file(path, *args, **kwargs):
        if path.name == "expected_anomalies.json":
            raise AssertionError("Runtime must not read expected anomaly answers")
        return original_open(path, *args, **kwargs)
    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", deny_expected_file)
        result = report(client, params={"start_at": "2026-07-04T00:00:00+05:00", "end_at": "2026-10-04T00:00:00+05:00"}, route="/analytics/anomalies")
    expected = json.loads((Path(__file__).resolve().parents[3] / "data/demo/expected_anomalies.json").read_text(encoding="utf-8"))
    evidence = lambda kind: {x for item in result["items"] if item["type"] == kind for x in item["evidence_order_ids"]}
    assert set(expected["patterns"]["repeat_unit"]["order_ids"]) <= evidence("repeat_fault")
    assert set(expected["patterns"]["excess_material"]["order_ids"]) <= evidence("material_overuse")
    for pair in expected["patterns"]["after_ppr"]["pairs"]:
        assert any(set(item["evidence_order_ids"]) == {pair["planned_order_id"], pair["followup_order_id"]}
                   for item in result["items"] if item["type"] == "after_planned")
