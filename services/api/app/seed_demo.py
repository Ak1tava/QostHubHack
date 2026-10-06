"""Explicit, reproducible synthetic T09 history. Never run at application startup."""

import argparse
import calendar
import hashlib
import json
import os
import random
import re
import struct
import zlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from getpass import getpass
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import event, select, text, tuple_
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_engine
from app.core.security import hash_password
from app.modules.auth.models import Brigade, Shift, User, UserArea
from app.modules.catalog.models import Area, Equipment, Material, MaterialNorm, WorkCode
from app.modules.work_orders.models import (
    DowntimeInterval,
    MasterDecision,
    MaterialUsage,
    Photo,
    Submission,
    WorkOrder,
    WorkOrderEvent,
    WorkOrderInterval,
)
from app.modules.work_orders.state_machine import transition

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "demo"
LOCAL = timezone(timedelta(hours=5))
NAMESPACE = UUID("44a34901-9f22-5bc4-a6d1-587fdc0e954e")
TABLES = {
    "areas": Area,
    "brigades": Brigade,
    "shifts": Shift,
    "users": User,
    "user_areas": UserArea,
    "equipment": Equipment,
    "work_codes": WorkCode,
    "materials": Material,
    "material_norms": MaterialNorm,
    "work_orders": WorkOrder,
    "submissions": Submission,
    "photos": Photo,
    "material_usage": MaterialUsage,
    "master_decisions": MasterDecision,
    "work_order_events": WorkOrderEvent,
    "work_order_intervals": WorkOrderInterval,
    "downtime_intervals": DowntimeInterval,
}


def calendar_start(as_of: date) -> date:
    month = as_of.year * 12 + as_of.month - 1 - 3
    year, zero_month = divmod(month, 12)
    return date(
        year,
        zero_month + 1,
        min(as_of.day, calendar.monthrange(year, zero_month + 1)[1]),
    )


def validate_target(url: str) -> None:
    target = make_url(url)
    name = target.database or ""
    if (
        target.get_backend_name() != "postgresql"
        or bool(target.query)
        or any(
            os.environ.get(name)
            for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")
        )
        or target.host not in {"localhost", "127.0.0.1", "::1", "db"}
        or not re.fullmatch(r"qosthub_(?:demo|test)(?:_[a-z0-9]+)*", name)
        or any(x in name.split("_") for x in {"prod", "production", "live"})
    ):
        raise ValueError(
            "Seed разрешён только в локальной демо/test БД qosthub_demo* / qosthub_test*; рабочая БД запрещена"
        )


def _png() -> bytes:
    """A procedural diagram, explicitly synthetic; no production photo is used."""

    def chunk(kind, value):
        return (
            struct.pack("!I", len(value))
            + kind
            + value
            + struct.pack("!I", zlib.crc32(kind + value) & 0xFFFFFFFF)
        )

    pixels = bytearray()
    for y in range(128):
        pixels.append(0)
        for x in range(128):
            color = (40, 160, 100) if 30 < x < 98 and 30 < y < 98 else (230, 230, 230)
            if x == y or x + y == 127:
                color = (200, 40, 40)
            pixels.extend(color)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 128, 128, 8, 2, 0, 0, 0))
        + chunk(
            b"tEXt", b"Description\x00SYNTHETIC DEMO DIAGRAM - NOT A REAL REPAIR PHOTO"
        )
        + chunk(b"IDAT", zlib.compress(bytes(pixels)))
        + chunk(b"IEND", b"")
    )


def build_dataset(seed: int, as_of: date) -> dict:
    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    scenarios = json.loads((DATA / "scenarios.json").read_text(encoding="utf-8"))
    start = datetime.combine(calendar_start(as_of), datetime.min.time(), LOCAL)
    end = datetime.combine(as_of, datetime.min.time(), LOCAL)
    days = (end - start).days
    rng = random.Random(seed)
    namespace = uuid5(NAMESPACE, f"v1:{seed}:{as_of.isoformat()}")
    uid = lambda key: uuid5(namespace, key)
    dataset = {name: [] for name in TABLES}
    dataset["_meta"] = {
        "seed": seed,
        "as_of": as_of.isoformat(),
        "version": 1,
        "synthetic": True,
    }
    add = lambda table, key, **values: dataset[table].append({"id": uid(key), **values})
    for i, name in enumerate(catalog["areas"]):
        add("areas", f"area:{i}", name=f"{name} / {seed}-{as_of}")
    for i, name in enumerate(catalog["brigades"]):
        add("brigades", f"brigade:{i}", name=f"{name} / {seed}-{as_of}")
    for day in range(days + 1):
        for shift in range(2):
            at = start + timedelta(days=day, hours=8 if shift == 0 else 20)
            add(
                "shifts",
                f"shift:{day}:{shift}",
                start_at=at,
                end_at=at + timedelta(hours=8),
            )
    for i in range(17):
        role = "master" if i < 2 else "worker"
        add(
            "users",
            f"user:{i}",
            login=f"t09-{seed}-{as_of}-{role}-{i + 1:02d}",
            password_hash="",
            display_name=f"[ДЕМО] {'Мастер' if i < 2 else 'Исполнитель'} {i + 1:02d}",
            role=role,
            specialty="Слесарь" if i >= 2 else None,
            grade=3 if i >= 2 else None,
            brigade_id=uid(f"brigade:{(i - 2) // 5}") if i >= 2 else None,
            shift_id=uid(f"shift:{days - 1}:1"),
            is_active=True,
        )
        for area in range(4):
            dataset["user_areas"].append(
                {"user_id": uid(f"user:{i}"), "area_id": uid(f"area:{area}")}
            )
    for i, item in enumerate(catalog["equipment"]):
        add(
            "equipment",
            f"equipment:{i}",
            name=item["name"],
            area_id=uid(f"area:{item['area']}"),
        )
    for i, item in enumerate(catalog["work_codes"]):
        add(
            "work_codes",
            f"code:{i}",
            code=f"T09-{seed}-{as_of}-{item['code']}",
            name=item["name"],
        )
    for i, item in enumerate(catalog["materials"]):
        add("materials", f"material:{i}", **item)
    for eq in range(25):
        for code in range(5):
            add(
                "material_norms",
                f"norm:{eq}:{code}",
                equipment_id=uid(f"equipment:{eq}"),
                work_code_id=uid(f"code:{code}"),
                material_id=uid("material:0"),
                quantity=Decimal("1.0000"),
            )
    patterns = scenarios["patterns"]
    repeats = set(patterns["repeat_unit"]["indices"])
    ppr = {i: j for i, j in patterns["after_ppr"]["pairs"]}
    after_ppr = {j: i for i, j in patterns["after_ppr"]["pairs"]}
    excess = set(patterns["excess_material"]["indices"])
    controls = set(scenarios["controls"]["indices"])
    picture_hash = hashlib.sha256(_png()).hexdigest()
    for i in range(scenarios["order_count"]):
        day = i * days // scenarios["order_count"]
        at = start + timedelta(days=day, hours=8, minutes=(i % 6) * 10)
        eq, code = rng.randrange(3, 25), rng.randrange(3)
        description = "[ДЕМО] Обычная проверка креплений и очистка оборудования"
        work_type, quantity = "planned", Decimal("1.0000")
        if i in repeats:
            eq, code, work_type = 0, 0, "emergency"
            description = "[ДЕМО] Повторная неисправность: подшипниковый узел насоса"
        elif i in ppr or i in after_ppr:
            eq, code = 1, 1
            if i in ppr:
                description = "[ДЕМО] ППР компрессора: плановое обслуживание"
            else:
                pair_day = after_ppr[i] * days // scenarios["order_count"]
                at = start + timedelta(days=pair_day + 1, hours=8)
                description, work_type = (
                    "[ДЕМО] Утечка после планового обслуживания",
                    "emergency",
                )
        elif i in excess:
            eq, code, quantity = 2, 2, Decimal(patterns["excess_material"]["quantity"])
            description = "[ДЕМО] Замена уплотнения оборудования"
        if i in controls:
            eq = 3 + (i - 400) % 22
            code = 3 + (i - 400) // 22
            description = "[ДЕМО] Контрольный обычный ремонт"
        worker_index = 2 + (i % 15)
        worker, master = uid(f"user:{worker_index}"), uid(f"user:{i % 2}")
        status = "CLOSED"
        if i >= 450:
            status = [
                "ISSUED",
                "ACCEPTED",
                "QUEUED",
                "REJECTED",
                "CANCELLED",
                "PAUSED",
                "SUBMITTED",
                "AI_REVIEW",
                "REWORK",
            ][i % 9]
        if i >= 497:
            at, status = end - timedelta(hours=2, minutes=(i - 497) * 10), "IN_PROGRESS"
        day = (at.date() - start.date()).days
        shift_index = 1 if at.hour >= 20 else 0
        brigade = i % 5 == 0
        order_id = uid(f"order:{i}")
        order = dict(
            id=order_id,
            number=f"T09-{seed}-{as_of}-{i + 1:04d}",
            work_type=work_type,
            description=description,
            area_id=uid(f"area:{catalog['equipment'][eq]['area']}"),
            equipment_id=uid(f"equipment:{eq}"),
            master_id=master,
            assignee_id=None if brigade else worker,
            brigade_id=uid(f"brigade:{(worker_index - 2) // 5}") if brigade else None,
            responsible_id=worker if brigade else None,
            priority="high" if work_type == "emergency" else "planned",
            due_at=at + timedelta(hours=6),
            status="ISSUED",
            version=1,
            assignment_version=1,
            queue_position=None,
            created_at=at,
        )
        actions = []
        if status == "CANCELLED":
            actions = [("cancel", "master", "Задание снято: синтетический пример")]
        elif status == "REJECTED":
            actions = [("reject", "worker", "Нет допуска: синтетический пример")]
        elif status == "QUEUED":
            actions = [("queue", "worker", None)]
        elif status != "ISSUED":
            actions = [("accept", "worker", None)]
            if status != "ACCEPTED":
                actions.append(("start", "worker", None))
            if status == "PAUSED":
                actions.append(("pause", "worker", "Ожидание материала"))
            elif status in {"SUBMITTED", "AI_REVIEW", "REWORK", "CLOSED"}:
                if i % 7 == 0:
                    actions += [
                        ("pause", "worker", "Ожидание отключения оборудования"),
                        ("resume", "worker", None),
                    ]
                actions.append(("submit", "worker", None))
                if status != "SUBMITTED":
                    actions.append(("begin_review", "system", None))
                if status == "REWORK":
                    actions.append(
                        ("request_rework", "master", "Уточните выполненные работы")
                    )
                elif status == "CLOSED":
                    actions.append(("close", "master", None))
        dataset["work_orders"].append(order)
        current_interval = None
        submitted_id = None
        for n, (action, role, reason) in enumerate(
            [("created", "master", None)] + actions
        ):
            when = at + timedelta(minutes=n * 20)
            old_status = order["status"] if n else None
            before = _snapshot(order) if n else {}
            if n:
                order["status"] = transition(order["status"], action, role, reason)
                order["version"] += 1
            order["queue_position"] = 1 if order["status"] == "QUEUED" else None
            if action == "submit":
                submitted_id = uid(f"submission:{i}:1")
                dataset["submissions"].append(
                    dict(
                        id=submitted_id,
                        work_order_id=order_id,
                        revision=1,
                        assignment_version=1,
                        worker_id=worker,
                        work_description="[ДЕМО] Выполнено: "
                        + catalog["work_codes"][code]["name"],
                        work_code_id=uid(f"code:{code}"),
                        no_materials_used=False,
                        comment="Синтетическая история, не производственные сведения",
                        submitted_at=when,
                    )
                )
                add(
                    "material_usage",
                    f"usage:{i}",
                    submission_id=submitted_id,
                    material_id=uid("material:0"),
                    quantity=quantity,
                )
                add(
                    "photos",
                    f"photo:{i}",
                    work_order_id=order_id,
                    submission_id=submitted_id,
                    uploaded_by=worker,
                    type="after",
                    storage_key=f"t09/{seed}-{as_of}/{order_id}/after.png",
                    mime_type="image/png",
                    content_hash=picture_hash,
                    received_at=when - timedelta(minutes=1),
                )
            if action in {"close", "request_rework"}:
                add(
                    "master_decisions",
                    f"decision:{i}",
                    work_order_id=order_id,
                    submission_id=submitted_id,
                    master_id=master,
                    decision="accept" if action == "close" else "rework",
                    reason=reason,
                    score=5 if action == "close" else None,
                    decided_at=when,
                )
            payload = {
                "before": before,
                "after": _snapshot(order),
                "synthetic": True,
                "shift_id": str(uid(f"shift:{day}:{shift_index}")),
            }
            if submitted_id:
                payload["submission_id"] = str(submitted_id)
            add(
                "work_order_events",
                f"event:{i}:{n}",
                work_order_id=order_id,
                actor_id=None
                if role == "system"
                else master
                if role == "master"
                else worker,
                action=action,
                version=order["version"],
                assignment_version=1,
                reason=reason,
                payload=payload,
                occurred_at=when,
            )
            kinds = {
                "IN_PROGRESS": "active",
                "PAUSED": "pause",
                "SUBMITTED": "review",
                "AI_REVIEW": "review",
            }
            if kinds.get(old_status) != kinds.get(order["status"]):
                if current_interval is not None:
                    current_interval["end_at"] = when
                current_interval = None
                if order["status"] in kinds:
                    current_interval = dict(
                        id=uid(f"interval:{i}:{n}"),
                        work_order_id=order_id,
                        kind=kinds[order["status"]],
                        start_at=when,
                        end_at=None,
                    )
                    dataset["work_order_intervals"].append(current_interval)
        if work_type == "emergency" and any(a[0] == "start" for a in actions):
            add(
                "downtime_intervals",
                f"downtime:{i}",
                equipment_id=order["equipment_id"],
                work_order_id=order_id,
                start_at=at,
                end_at=at + timedelta(minutes=len(actions) * 20)
                if status == "CLOSED"
                else None,
                reason="[ДЕМО] Остановка оборудования на ремонт",
            )
    return dataset


def _snapshot(order: dict) -> dict:
    names = (
        "status",
        "priority",
        "assignee_id",
        "brigade_id",
        "responsible_id",
        "version",
        "assignment_version",
        "queue_position",
        "due_at",
    )
    return {
        name: str(order[name])
        if isinstance(order[name], (UUID, datetime))
        else order[name]
        for name in names
    }


def load_dataset(
    db: Session, dataset: dict, *, password: str, photo_root: Path | None = None
) -> str:
    """Caller owns commit/rollback. Existing synthetic rows are never overwritten."""
    validate_target(str(db.get_bind().url.render_as_string(hide_password=False)))
    if len(password) < 8:
        raise ValueError("Демопароль должен содержать минимум 8 символов")
    db.execute(text("SELECT pg_advisory_xact_lock(709042)"))
    meta = dataset["_meta"]
    cohort = f"T09-{meta['seed']}-{meta['as_of']}-"
    foreign_cohort = db.scalar(
        select(WorkOrder.id)
        .where(WorkOrder.number.like("T09-%"), ~WorkOrder.number.startswith(cohort))
        .limit(1)
    )
    if foreign_cohort:
        raise ValueError(
            "В БД уже есть другой набор T09: используйте отдельную демо-БД"
        )
    existing_count = 0
    total_count = sum(len(dataset[name]) for name in TABLES)
    for name, model in TABLES.items():
        columns = list(model.__table__.primary_key.columns)
        keys = [tuple(row[c.name] for c in columns) for row in dataset[name]]
        rows = (
            db.execute(select(model.__table__).where(tuple_(*columns).in_(keys)))
            .mappings()
            .all()
            if keys
            else []
        )
        existing_count += len(rows)
        by_key = {tuple(row[c.name] for c in columns): row for row in rows}
        for expected in dataset[name]:
            actual = by_key.get(tuple(expected[c.name] for c in columns))
            if actual and any(
                actual[key] != value
                for key, value in expected.items()
                if key != "password_hash"
            ):
                raise ValueError(
                    "Демоданные изменены: повтор seed не перезаписывает изменения"
                )
    if existing_count not in {0, total_count}:
        raise ValueError(
            "Частичный набор T09: восстановите отдельную демо-БД, seed ничего не перезаписывает"
        )
    root = (
        Path(photo_root)
        if photo_root is not None
        else Path(settings.photo_storage_path)
    )
    picture = _png()
    for photo in dataset["photos"]:
        path = root / photo["storage_key"]
        if (
            path.exists()
            and hashlib.sha256(path.read_bytes()).hexdigest() != photo["content_hash"]
        ):
            raise ValueError("Синтетическое фото изменено; seed не перезаписывает файл")
    if existing_count == total_count:
        if any(not (root / p["storage_key"]).is_file() for p in dataset["photos"]):
            raise ValueError(
                "Фото набора отсутствуют; восстановите файлы из резервной копии"
            )
        return "unchanged"
    created_files = []

    def clean_files(session):
        for path in created_files:
            path.unlink(missing_ok=True)
        created_files.clear()

    event.listen(db, "after_rollback", clean_files, once=True)
    event.listen(db, "after_commit", lambda session: created_files.clear(), once=True)
    try:
        for name, model in TABLES.items():
            values = [
                {
                    **row,
                    **(
                        {"password_hash": hash_password(password)}
                        if name == "users"
                        else {}
                    ),
                }
                for row in dataset[name]
            ]
            if values:
                db.execute(model.__table__.insert(), values)
        for photo in dataset["photos"]:
            path = root / photo["storage_key"]
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open("xb") as handle:
                    created_files.append(path)
                    handle.write(picture)
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise
    return "created"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Загрузить синтетическую историю Т09 в локальную демо-БД"
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if not settings.database_url:
        parser.error("DATABASE_URL не задан для демо-БД")
    try:
        validate_target(settings.database_url.get_secret_value())
    except ValueError as exc:
        parser.error(str(exc))
    password = os.environ.get("DEMO_PASSWORD") or getpass(
        "Демопароль (минимум 8 символов): "
    )
    if len(password) < 8:
        parser.error("Задайте демопароль минимум 8 символов вне Git")
    data = build_dataset(args.seed, args.as_of)
    with Session(get_engine()) as db:
        try:
            result = load_dataset(db, data, password=password)
            db.commit()
        except ValueError as exc:
            db.rollback()
            parser.error(str(exc))
    print(
        f"T09: {result}; 500 синтетических нарядов. Пароли не выводятся. Логины: t09-{args.seed}-{args.as_of}-master-01/02, worker-03..17"
    )


if __name__ == "__main__":
    main()
