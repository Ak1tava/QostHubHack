from datetime import timedelta

import pytest
from test_analytics import START, PARAMS, order, event, submission, report


def worker_row(result, worker, kind="planned"):
    return next(x for x in result["items"] if x["worker_id"] == str(worker.id) and x["work_type"] == kind)


def test_rating_final_revision_q_t_weights_and_no_invented_r_v(client, database):
    early = order(database)
    submission(database, early, accepted=False, score=1)
    submission(database, early, revision=2, score=4, at=START + timedelta(hours=3))
    ontime = order(database)
    submission(database, ontime, score=5)
    database["session"].commit()
    row = worker_row(report(client, route="/reports/rating"), database["worker"])
    assert row["closed_count"] == 2
    assert row["components"]["Q"] == dict(value=.9, sample_size=2, reason=None)
    assert row["components"]["T"] == dict(value=.5, sample_size=2, reason=None)
    assert row["score"] == pytest.approx(76.6666666667)
    assert row["components"]["R"]["value"] is None
    assert row["components"]["V"]["value"] is None
    assert row["components"]["R"]["sample_size"] == 0


def test_null_scores_normalize_available_weights_and_empty_workers(client, database):
    row = order(database)
    submission(database, row, score=None)
    database["session"].commit()
    result = report(client, route="/reports/rating")
    value = worker_row(result, database["worker"])
    assert value["components"]["Q"]["value"] is None
    assert value["score"] == 100
    empty = worker_row(result, database["worker"], "emergency")
    assert empty["score"] is None and empty["closed_count"] == 0


def test_attribution_uses_submission_worker_and_deadline_history(client, database):
    row = order(database)
    submission(database, row, score=3)
    event(database, row, START + timedelta(hours=4), "reassign", "CLOSED",
          assignee_id=str(database["outsider"].id), due_at=(START + timedelta(minutes=30)).isoformat())
    row.assignee_id = database["outsider"].id
    row.due_at = START + timedelta(minutes=30)
    database["session"].commit()
    result = report(client, "worker", route="/reports/rating")
    assert {x["worker_id"] for x in result["items"]} == {str(database["worker"].id)}
    value = worker_row(result, database["worker"])
    assert value["closed_count"] == 1
    assert value["components"]["T"]["value"] == 1
    assert value["score"] == pytest.approx(73.333333333)


def test_rating_keeps_work_types_separate_and_mature_r_still_unknown(client, database):
    planned = order(database, at=START - timedelta(days=10))
    submission(database, planned, at=START + timedelta(minutes=30), score=5)
    emergency = order(database, work_type="emergency")
    submission(database, emergency, score=1)
    database["session"].commit()
    result = report(client, route="/reports/rating")
    normal = worker_row(result, database["worker"])
    urgent = worker_row(result, database["worker"], "emergency")
    assert normal["closed_count"] == urgent["closed_count"] == 1
    assert normal["components"]["Q"]["value"] == 1
    assert urgent["components"]["Q"]["value"] == .2
    assert normal["components"]["R"]["value"] is None
    assert normal["components"]["R"]["reason"]


def test_incomplete_seven_day_window_never_becomes_quality_success(client, database, monkeypatch):
    from app.modules.analytics import router
    class FixedClock:
        @staticmethod
        def now(tz):
            return START + timedelta(days=1)
    monkeypatch.setattr(router, "datetime", FixedClock)
    row = order(database)
    submission(database, row)
    database["session"].commit()
    value = worker_row(report(client, route="/reports/rating"), database["worker"])
    assert value["components"]["R"]["value"] is None
    assert value["components"]["R"]["sample_size"] == 0
    assert "7 дней не завершено для 1" in value["components"]["R"]["reason"]


def test_rating_assignee_filter_follows_accepted_submission_after_reassignment(client, database):
    row = order(database)
    submission(database, row, score=4)
    event(database, row, START + timedelta(hours=2), "reassign", "CLOSED", assignee_id=str(database["outsider"].id))
    row.assignee_id = database["outsider"].id
    database["session"].commit()
    result = report(client, params={**PARAMS, "assignee_id": str(database["worker"].id)}, route="/reports/rating")
    assert len(result["items"]) == 2
    assert worker_row(result, database["worker"])["closed_count"] == 1


def test_worker_former_brigade_filter_preserves_own_accepted_history(client, database):
    from app.modules.auth.models import Brigade
    row = order(database)
    row.assignee_id = None
    row.brigade_id = database["brigade"].id
    row.responsible_id = database["worker"].id
    event(database, row, START, "reassign", "ISSUED")
    submission(database, row)
    new_brigade = Brigade(name="Новая бригада")
    db = database["session"]
    db.add(new_brigade)
    db.flush()
    database["worker"].brigade_id = new_brigade.id
    db.commit()
    result = report(client, "worker", params={**PARAMS, "brigade_id": str(database["brigade"].id)}, route="/reports/rating")
    assert {x["worker_id"] for x in result["items"]} == {str(database["worker"].id)}
    assert worker_row(result, database["worker"])["closed_count"] == 1
