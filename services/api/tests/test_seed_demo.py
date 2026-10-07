"""Seed safety, deterministic history and independently queried planted patterns."""

import importlib
import json
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select


def seed_module():
    spec = importlib.util.find_spec("app.seed_demo")
    assert spec is not None, "T09 seed command is not implemented"
    return importlib.import_module("app.seed_demo")


def test_three_calendar_months_and_reproducibility():
    seed = seed_module()
    history = seed.build_dataset(42, date(2026, 10, 4))
    assert history == seed.build_dataset(42, date(2026, 10, 4))
    assert history != seed.build_dataset(43, date(2026, 10, 4))
    assert seed.calendar_start(date(2026, 5, 31)) == date(2026, 2, 28)
    assert seed.calendar_start(date(2024, 5, 31)) == date(2024, 2, 29)
    assert seed.calendar_start(date(2026, 1, 31)) == date(2025, 10, 31)
    assert len(history["work_orders"]) == 500
    assert len(history["areas"]) >= 4
    assert len(history["equipment"]) >= 25
    assert len(history["brigades"]) == 3
    assert len(history["work_codes"]) >= 20
    assert len(history["materials"]) >= 40
    assert sum(u["role"] == "master" for u in history["users"]) == 2
    assert sum(u["role"] == "worker" for u in history["users"]) == 15
    start = datetime.fromisoformat("2026-07-04T00:00:00+05:00")
    end = datetime.fromisoformat("2026-10-04T00:00:00+05:00")
    for order in history["work_orders"]:
        assert start <= order["created_at"] < end
        assert order["created_at"] < order["due_at"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://x:y@prod.example/qosthub_demo",
        "postgresql+psycopg://x:y@localhost/qosthub",
        "postgresql+psycopg://x:y@localhost/qosthub_demo_production",
        "sqlite:///qosthub_demo.db",
    ],
)
def test_production_targets_are_refused(url):
    with pytest.raises(ValueError):
        seed_module().validate_target(url)


def test_cli_rejects_unsafe_database_before_any_password_or_write():
    import os

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.seed_demo",
            "--seed",
            "42",
            "--as-of",
            "2026-10-04",
        ],
        env={
            **os.environ,
            "DATABASE_URL": "postgresql+psycopg://hidden:secret@prod.example/prod",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "secret" not in result.stdout + result.stderr
    assert "демо" in result.stderr.lower()


def test_seed_persists_once_without_touching_existing_accounts(database, tmp_path):
    from app.modules.auth.models import User
    from app.modules.work_orders.models import OutboxEvent, WorkOrder

    seed = seed_module()
    db = database["session"]
    original_hash = database["master"].password_hash
    data = seed.build_dataset(42, date(2026, 10, 4))
    result = seed.load_dataset(
        db, data, password="synthetic-test-only", photo_root=tmp_path
    )
    db.commit()
    assert result == "created"
    assert db.scalar(select(func.count()).select_from(WorkOrder)) == 500
    assert db.scalar(select(func.count()).select_from(User)) == 20
    # Historical fixtures must not enqueue Telegram delivery.
    assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    assert (
        seed.load_dataset(db, data, password="different-test-only", photo_root=tmp_path)
        == "unchanged"
    )
    db.commit()
    assert db.scalar(select(func.count()).select_from(WorkOrder)) == 500
    assert database["master"].password_hash == original_hash


def test_partial_or_modified_seed_is_refused_without_overwriting(database, tmp_path):
    from app.modules.work_orders.models import WorkOrder

    seed = seed_module()
    db = database["session"]
    data = seed.build_dataset(42, date(2026, 10, 4))
    seed.load_dataset(db, data, password="synthetic-test-only", photo_root=tmp_path)
    db.commit()
    order = db.get(WorkOrder, data["work_orders"][0]["id"])
    order.description = "Changed by user"
    db.commit()
    with pytest.raises(ValueError, match="измен|частич"):
        seed.load_dataset(db, data, password="synthetic-test-only", photo_root=tmp_path)
    db.rollback()
    assert db.get(WorkOrder, order.id).description == "Changed by user"


def test_history_matches_real_transition_rules_and_intervals():
    from app.modules.work_orders.state_machine import transition

    data = seed_module().build_dataset(42, date(2026, 10, 4))
    users = {u["id"]: u for u in data["users"]}
    events = data["work_order_events"]
    for order in data["work_orders"]:
        own = sorted(
            (e for e in events if e["work_order_id"] == order["id"]),
            key=lambda e: e["version"],
        )
        assert [e["version"] for e in own] == list(range(1, order["version"] + 1))
        assert own[0]["action"] == "created"
        assert own[0]["occurred_at"] == order["created_at"]
        for before, after in zip(own, own[1:]):
            assert before["occurred_at"] <= after["occurred_at"]
            role = users[after["actor_id"]]["role"] if after["actor_id"] else "system"
            assert (
                transition(
                    before["payload"]["after"]["status"],
                    after["action"],
                    role,
                    after["reason"],
                )
                == after["payload"]["after"]["status"]
            )
        assert own[-1]["payload"]["after"]["status"] == order["status"]
        intervals = sorted(
            (
                x
                for x in data["work_order_intervals"]
                if x["work_order_id"] == order["id"]
            ),
            key=lambda x: x["start_at"],
        )
        for i, interval in enumerate(intervals):
            assert interval["start_at"] >= order["created_at"]
            assert (
                interval["end_at"] is None or interval["start_at"] <= interval["end_at"]
            )
            if i:
                assert intervals[i - 1]["end_at"] <= interval["start_at"]
        if order["status"] == "CLOSED":
            assert all(x["end_at"] is not None for x in intervals)
            assert any(
                d["work_order_id"] == order["id"] and d["decision"] == "accept"
                for d in data["master_decisions"]
            )


def test_planted_anomalies_come_from_database_not_expected_answers(database, tmp_path):
    from app.modules.catalog.models import MaterialNorm
    from app.modules.work_orders.models import MaterialUsage, Submission, WorkOrder

    seed = seed_module()
    db = database["session"]
    seed.load_dataset(
        db,
        seed.build_dataset(42, date(2026, 10, 4)),
        password="synthetic-test-only",
        photo_root=tmp_path,
    )
    db.commit()
    # Same unit, repeated incidents; regular equipment controls have fewer.
    repeats = db.execute(
        select(WorkOrder.equipment_id, func.count())
        .where(WorkOrder.description.contains("подшипниковый узел"))
        .group_by(WorkOrder.equipment_id)
    ).all()
    assert max(count for _, count in repeats) >= 12
    planned = db.scalars(
        select(WorkOrder).where(WorkOrder.description.contains("ППР"))
    ).all()
    emergencies = db.scalars(
        select(WorkOrder).where(WorkOrder.work_type == "emergency")
    ).all()
    recurrence = [
        (p, e)
        for p in planned
        for e in emergencies
        if p.equipment_id == e.equipment_id
        and p.created_at
        < e.created_at
        <= p.created_at + __import__("datetime").timedelta(days=2)
    ]
    assert len(recurrence) >= 6
    ratios = db.execute(
        select(MaterialUsage.quantity, MaterialNorm.quantity)
        .join(Submission, Submission.id == MaterialUsage.submission_id)
        .join(WorkOrder, WorkOrder.id == Submission.work_order_id)
        .join(
            MaterialNorm,
            (MaterialNorm.equipment_id == WorkOrder.equipment_id)
            & (MaterialNorm.work_code_id == Submission.work_code_id)
            & (MaterialNorm.material_id == MaterialUsage.material_id),
        )
    ).all()
    assert sum(actual > norm * Decimal("1.5") for actual, norm in ratios) >= 10
    assert sum(actual <= norm for actual, norm in ratios) >= 10


def test_photo_files_are_valid_and_removed_on_rollback(database, tmp_path):
    seed = seed_module()
    db = database["session"]
    data = seed.build_dataset(42, date(2026, 10, 4))
    seed.load_dataset(db, data, password="synthetic-test-only", photo_root=tmp_path)
    photo = data["photos"][0]
    content = (tmp_path / photo["storage_key"]).read_bytes()
    import hashlib

    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    assert hashlib.sha256(content).hexdigest() == photo["content_hash"]
    db.rollback()
    assert not list(tmp_path.rglob("*.png"))


def test_partial_seed_refuses_missing_rows(database, tmp_path):
    from app.modules.work_orders.models import MaterialUsage

    seed = seed_module()
    db = database["session"]
    data = seed.build_dataset(42, date(2026, 10, 4))
    seed.load_dataset(db, data, password="synthetic-test-only", photo_root=tmp_path)
    db.commit()
    db.delete(db.get(MaterialUsage, data["material_usage"][0]["id"]))
    db.commit()
    with pytest.raises(ValueError, match="[Чч]астич"):
        seed.load_dataset(db, data, password="synthetic-test-only", photo_root=tmp_path)
    db.rollback()


def test_expected_anomaly_ids_are_verified_by_independent_sql(database, tmp_path):
    from app.modules.catalog.models import MaterialNorm
    from app.modules.work_orders.models import MaterialUsage, Submission, WorkOrder

    seed = seed_module()
    db = database["session"]
    seed.load_dataset(
        db,
        seed.build_dataset(42, date(2026, 10, 4)),
        password="synthetic-test-only",
        photo_root=tmp_path,
    )
    db.commit()
    expected = json.loads(
        (
            Path(__file__).resolve().parents[3] / "data/demo/expected_anomalies.json"
        ).read_text(encoding="utf-8")
    )
    repeat = db.scalars(
        select(WorkOrder.id).where(WorkOrder.description.contains("подшипниковый узел"))
    ).all()
    assert {str(x) for x in repeat} == set(
        expected["patterns"]["repeat_unit"]["order_ids"]
    )
    assert len(repeat) == 24
    excessive = db.scalars(
        select(WorkOrder.id)
        .join(Submission, Submission.work_order_id == WorkOrder.id)
        .join(MaterialUsage, MaterialUsage.submission_id == Submission.id)
        .join(
            MaterialNorm,
            (MaterialNorm.equipment_id == WorkOrder.equipment_id)
            & (MaterialNorm.work_code_id == Submission.work_code_id)
            & (MaterialNorm.material_id == MaterialUsage.material_id),
        )
        .where(MaterialUsage.quantity > MaterialNorm.quantity * Decimal("1.5"))
    ).all()
    assert {str(x) for x in excessive} == set(
        expected["patterns"]["excess_material"]["order_ids"]
    )
    assert len(excessive) == 12
    for pair in expected["patterns"]["after_ppr"]["pairs"]:
        from uuid import UUID

        planned = db.get(WorkOrder, UUID(pair["planned_order_id"]))
        followup = db.get(WorkOrder, UUID(pair["followup_order_id"]))
        assert planned.work_type == "planned" and followup.work_type == "emergency"
        assert planned.equipment_id == followup.equipment_id
        assert (
            0 < (followup.created_at - planned.created_at).total_seconds() <= 48 * 3600
        )
    assert len(expected["patterns"]["after_ppr"]["pairs"]) == 12
    assert len(expected["control_order_ids"]) == 24


def test_every_historical_event_is_in_its_recorded_shift():
    from uuid import UUID

    data = seed_module().build_dataset(42, date(2026, 10, 4))
    shifts = {s["id"]: s for s in data["shifts"]}
    for event in data["work_order_events"]:
        shift = shifts[UUID(event["payload"]["shift_id"])]
        assert shift["start_at"] <= event["occurred_at"] < shift["end_at"]


def test_concurrent_seed_serializes_without_duplicates(database, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from app.modules.work_orders.models import WorkOrder

    seed = seed_module()
    data = seed.build_dataset(42, date(2026, 10, 4))
    barrier = Barrier(2)

    def run():
        with Session(database["engine"]) as db:
            barrier.wait(timeout=15)
            result = seed.load_dataset(
                db, data, password="synthetic-test-only", photo_root=tmp_path
            )
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(results) == ["created", "unchanged"]
    assert (
        database["session"].scalar(select(func.count()).select_from(WorkOrder)) == 500
    )


@pytest.mark.parametrize(
    "override",
    [
        "host=prod.example&dbname=qosthub_production",
        "hostaddr=203.0.113.2",
        "service=production",
        "port=9999",
    ],
)
def test_driver_connection_overrides_are_rejected(override):
    with pytest.raises(ValueError):
        seed_module().validate_target(
            "postgresql+psycopg://x:y@localhost/qosthub_demo?" + override
        )


def test_regular_controls_do_not_repeat_same_equipment_and_work_code_within_seven_days():
    from datetime import timedelta

    data = seed_module().build_dataset(42, date(2026, 10, 4))
    codes = {s["work_order_id"]: s["work_code_id"] for s in data["submissions"]}
    orders = [o for o in data["work_orders"] if o["id"] in codes]
    controls = [o for o in orders if "Контрольный обычный ремонт" in o["description"]]
    assert len(controls) == 24
    for control in controls:
        peers = [
            o
            for o in orders
            if o["id"] != control["id"]
            and o["equipment_id"] == control["equipment_id"]
            and codes[o["id"]] == codes[control["id"]]
            and abs(o["created_at"] - control["created_at"]) <= timedelta(days=7)
        ]
        assert peers == [], "Normal control became a repeated repair"


def test_failed_photo_write_is_cleaned_on_rollback(database, tmp_path, monkeypatch):
    seed = seed_module()
    db = database["session"]
    data = seed.build_dataset(42, date(2026, 10, 4))
    original_open = Path.open

    class FailingWrite:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, content):
            self.handle.write(content[:20])
            self.handle.flush()
            raise OSError("simulated full disk")

    def open_file(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return FailingWrite(handle) if args and args[0] == "xb" else handle

    monkeypatch.setattr(Path, "open", open_file)
    with pytest.raises(OSError, match="full disk"):
        seed.load_dataset(db, data, password="synthetic-test-only", photo_root=tmp_path)
    db.rollback()
    assert not list(tmp_path.rglob("*.png"))


@pytest.mark.parametrize(
    "variable", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"]
)
def test_environment_connection_overrides_are_rejected(variable, monkeypatch):
    monkeypatch.setenv(variable, "external-override")
    with pytest.raises(ValueError):
        seed_module().validate_target("postgresql+psycopg://x:y@localhost/qosthub_demo")


def test_master_scores_fit_c6_five_point_quality_formula():
    data = seed_module().build_dataset(42, date(2026, 10, 4))
    scores = [d["score"] for d in data["master_decisions"] if d["score"] is not None]
    assert scores and all(1 <= score <= 5 for score in scores)
