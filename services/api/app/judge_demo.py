"""Explicit isolated T18 judge fixtures; no remote provider or notifications."""

import argparse
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_engine
from app.core.security import hash_password
from app.modules.auth.models import User, UserArea
from app.modules.ai_review.schemas import (
    Finding, ImageEvidence, ProviderOutcome, ReviewInput, ReviewResult, StagePlan,
)
from app.modules.work_orders.models import AIReview
from app.seed_demo import TABLES, _png, build_dataset, validate_target
from app.prepared_judge_demo import PreparedJudgeProvider, prepare_dataset, prepared_png, save_prepared_reviews

NAMESPACE = UUID("80a492aa-354c-4462-93f5-539d110193db")


class SyntheticJudgeProvider:
    """Local deterministic provider: demonstrates evidence, certifies no repair."""

    def review(
        self, value: ReviewInput, plan: StagePlan, *,
        images: dict[str, ImageEvidence], previous: ProviderOutcome | None = None,
    ) -> ProviderOutcome:
        refs = ["problem", "work_description"] + [p["id"] for p in value.photo_refs]
        return ProviderOutcome(
            is_mock=True,
            result=ReviewResult(
                verdict="human_review", score=None,
                findings=[Finding(
                    code="synthetic_demo", severity="warning",
                    message="MOCK: показ структуры evidence, реальный ремонт не проверялся.",
                    evidence_refs=refs,
                )],
                missing_evidence=["Реальные фотографии ремонта"],
                limitations=[
                    "MOCK / СИНТЕТИЧЕСКИЙ TEST-PROVIDER: сохранённый пример, не вызов OpenAI.",
                    "Рисунки до/после синтетические; безопасность и качество ремонта не подтверждены.",
                ],
            ),
        )


def _saved_review(namespace: UUID, dataset: dict, report: dict) -> dict:
    order = next(o for o in dataset["work_orders"] if o["id"] == report["work_order_id"])
    value = ReviewInput(
        work_order_id=order["id"], submission_revision=report["revision"],
        assignment_version=report["assignment_version"], problem=order["description"],
        work_description=report["work_description"], material_checks=[],
        timing_checks=[], checklist=[],
        photo_refs=[{"id": f"photo:{p['id']}"} for p in dataset["photos"] if p["submission_id"] == report["id"]],
    )
    outcome = SyntheticJudgeProvider().review(
        value, StagePlan(stage="primary", model="t18-synthetic-test-provider", reasoning="low"), images={},
    )
    return dict(
        id=uuid5(namespace, f"review:{report['id']}"), submission_id=report["id"],
        order_version=order["version"] - (1 if order["status"] == "REWORK" else 0),
        assignment_version=report["assignment_version"], verdict=outcome.result.verdict,
        model="t18-synthetic-test-provider", prompt_version="t18-mock-v1", latency_ms=0,
        usage={"is_mock": True, "calls": [], "fixture": True},
        created_at=report["submitted_at"], result=outcome.result.model_dump(mode="json"),
    )


def build_judge_dataset(cohort: str, as_of: date) -> dict:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", cohort) or len(cohort) > 40:
        raise ValueError("Группа судей: 1–40 латинских букв/цифр/дефисов")
    source = build_dataset(18, as_of)
    selected = [source["work_orders"][0], source["work_orders"][1]]
    selected += [next(o for o in source["work_orders"] if o["status"] == s) for s in ("ISSUED", "AI_REVIEW", "REWORK")]
    order_ids = {o["id"] for o in selected}
    submissions = [s for s in source["submissions"] if s["work_order_id"] in order_ids]
    submission_ids = {s["id"] for s in submissions}
    equipment_ids = {o["equipment_id"] for o in selected}
    codes = {s["work_code_id"] for s in submissions}
    dataset = {name: [] for name in TABLES}
    dataset.update(work_orders=selected, submissions=submissions)
    for name in ("photos", "master_decisions", "work_order_events", "work_order_intervals", "downtime_intervals"):
        dataset[name] = [r for r in source[name] if r["work_order_id"] in order_ids]
    dataset["material_usage"] = [r for r in source["material_usage"] if r["submission_id"] in submission_ids]
    dataset["materials"] = [source["materials"][0]]
    dataset["equipment"] = [r for r in source["equipment"] if r["id"] in equipment_ids]
    dataset["work_codes"] = [r for r in source["work_codes"] if r["id"] in codes]
    dataset["material_norms"] = [r for r in source["material_norms"] if r["equipment_id"] in equipment_ids and r["work_code_id"] in codes]
    dataset["areas"] = [source["areas"][0]]
    dataset["brigades"] = [source["brigades"][0]]
    historical_shifts = {e["payload"]["shift_id"] for e in dataset["work_order_events"]}
    dataset["shifts"] = [s for s in source["shifts"] if str(s["id"]) in historical_shifts]
    dataset["users"] = [source["users"][0], source["users"][2]]
    master, worker = dataset["users"]
    namespace = uuid5(NAMESPACE, cohort)
    replacements = {str(u["id"]): str(master["id"] if u["role"] == "master" else worker["id"]) for u in source["users"]}
    replacements.update({str(a["id"]): str(dataset["areas"][0]["id"]) for a in source["areas"]})
    replacements.update({str(b["id"]): str(dataset["brigades"][0]["id"]) for b in source["brigades"]})

    def mapped(value):
        if isinstance(value, UUID):
            return uuid5(namespace, replacements.get(str(value), str(value)))
        if isinstance(value, str):
            try:
                return str(mapped(UUID(value)))
            except ValueError:
                return value
        if isinstance(value, dict):
            return {k: mapped(v) for k, v in value.items()}
        if isinstance(value, list):
            return [mapped(v) for v in value]
        return value

    dataset = mapped(dataset)
    master, worker = dataset["users"]
    area, brigade = dataset["areas"][0], dataset["brigades"][0]
    area["name"] = f"[T18 СИНТЕТИКА] Участок судей {cohort}"
    brigade["name"] = f"[T18 СИНТЕТИКА] Бригада судей {cohort}"
    now = datetime.combine(as_of, datetime.min.time(), timezone.utc)
    shift = dict(id=uuid5(namespace, "current-shift"), start_at=now, end_at=now + timedelta(days=1))
    dataset["shifts"].append(shift)
    for user in dataset["users"]:
        user.update(login=f"judge-{cohort}-{user['role']}", display_name=f"[T18 СИНТЕТИКА] {'Мастер' if user['role'] == 'master' else 'Исполнитель'} судей", shift_id=shift["id"])
    dataset["user_areas"] = [dict(user_id=u["id"], area_id=area["id"]) for u in dataset["users"]]
    for n, order in enumerate(dataset["work_orders"], 1):
        order["number"] = f"T18-{cohort}-{n:02d}"
        order["description"] = "[T18 СИНТЕТИКА] " + order["description"]
        if order["status"] == "ISSUED":
            order["created_at"], order["due_at"] = now, now + timedelta(days=1)
            for item in dataset["work_order_events"]:
                if item["work_order_id"] == order["id"]:
                    item["occurred_at"] = now
                    item["payload"]["shift_id"] = str(shift["id"])
                    item["payload"]["after"]["due_at"] = order["due_at"].isoformat()
        dataset["photos"].append(dict(id=uuid5(namespace, f"before:{n}"), work_order_id=order["id"], submission_id=None, uploaded_by=master["id"], type="before", storage_key=f"t18/{cohort}/{order['id']}/before.png", mime_type="image/png", content_hash=hashlib.sha256(_png()).hexdigest(), received_at=order["created_at"]))
    for photo in dataset["photos"]:
        photo["storage_key"] = f"t18/{cohort}/{photo['work_order_id']}/{photo['type']}.png"
    for code in dataset["work_codes"]:
        code["code"] = f"T18-{cohort}-" + code["code"].rsplit("-", 1)[-1]
    dataset["ai_reviews"] = [_saved_review(namespace, dataset, s) for s in dataset["submissions"]]
    return dataset


def setup_judge_demo(db: Session, *, cohort: str, as_of: date, master_password: str, worker_password: str, photo_root: Path, scenario_set: str = "legacy-v1") -> str:
    """Caller commits; repeats preserve passwords and judge actions, never widen access."""
    validate_target(db.get_bind().url.render_as_string(hide_password=False))
    if any(not 12 <= len(p) <= 128 for p in (master_password, worker_password)) or master_password == worker_password:
        raise ValueError("Два разных пароля длиной 12–128 символов обязательны")
    if scenario_set not in {"legacy-v1", "prepared-v2"}:
        raise ValueError("Неизвестная версия демонстрационных сценариев")
    if scenario_set == "prepared-v2":
        cohort += "-prepared-v2"
    dataset = build_judge_dataset(cohort, as_of)
    if scenario_set == "prepared-v2":
        prepare_dataset(dataset)
    tables = {**TABLES, "ai_reviews": AIReview}
    db.execute(text("SELECT pg_advisory_xact_lock(718018)"))
    expected = dataset["users"]
    existing = db.scalars(select(User).where(User.login.in_([u["login"] for u in expected]) | User.id.in_([u["id"] for u in expected]))).all()
    if existing:
        if len(existing) != 2 or {u.id for u in existing} != {u["id"] for u in expected}:
            raise ValueError("Коллизия существующих аккаунтов; ничего не изменено")
        for user, values in [(u, next(v for v in expected if v["id"] == u.id)) for u in existing]:
            if any(getattr(user, k) != values[k] for k in ("login", "role", "brigade_id", "shift_id", "is_active")) or set(db.scalars(select(UserArea.area_id).where(UserArea.user_id == user.id))) != {dataset["areas"][0]["id"]}:
                raise ValueError("Доступ судей изменён; setup не расширяет права")
        for name, model in tables.items():
            for row in dataset[name]:
                key = tuple(row[c.name] for c in model.__table__.primary_key.columns)
                if db.get(model, key) is None:
                    raise ValueError("Частичный набор судей; setup не восстанавливает изменённые данные")
        if any(not (photo_root / p["storage_key"]).is_file() for p in dataset["photos"]):
            raise ValueError("Фото судей отсутствуют; восстановите резервную копию")
        if scenario_set == "prepared-v2":
            from app.modules.ai_review.jobs_models import ReviewJob
            for report in dataset["submissions"]:
                if not db.scalar(select(AIReview.id).where(AIReview.submission_id == report["id"])) or not db.scalar(select(ReviewJob.id).where(ReviewJob.submission_id == report["id"])):
                    raise ValueError("Частичный набор судей; setup не восстанавливает изменённые данные")
        return "unchanged"
    # Reject collisions before any row or file is created.
    for name, model in tables.items():
        for row in dataset[name]:
            key = tuple(row[c.name] for c in model.__table__.primary_key.columns)
            if db.get(model, key) is not None:
                raise ValueError("Коллизия / частичный набор судей; ничего не изменено")
            for col in model.__table__.columns:
                if col.unique and col.name in row and db.scalar(select(model).where(col == row[col.name]).limit(1)):
                    raise ValueError("Коллизия существующих демоданных; ничего не изменено")
    if any((photo_root / p["storage_key"]).exists() for p in dataset["photos"]):
        raise ValueError("Фото уже существуют; setup не перезаписывает файлы")
    created_files = []

    def cleanup(session):
        for path in created_files:
            path.unlink(missing_ok=True)
        created_files.clear()

    event.listen(db, "after_rollback", cleanup, once=True)
    event.listen(db, "after_commit", lambda session: created_files.clear(), once=True)
    try:
        for name, model in tables.items():
            for row in dataset[name]:
                values = dict(row)
                if name == "users":
                    values["password_hash"] = hash_password(master_password if row["role"] == "master" else worker_password)
                db.execute(model.__table__.insert(), values)
        for photo in dataset["photos"]:
            path = photo_root / photo["storage_key"]
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                created_files.append(path)
                handle.write(prepared_png(photo) if scenario_set == "prepared-v2" else _png())
        if scenario_set == "prepared-v2":
            save_prepared_reviews(db, dataset, photo_root)
    except Exception:
        cleanup(db)
        raise
    return "created"


def main():
    parser = argparse.ArgumentParser(description="Изолированные синтетические аккаунты судей T18")
    parser.add_argument("--confirm-demo", action="store_true", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--scenario-set", choices=["legacy-v1", "prepared-v2"], default="legacy-v1")
    args = parser.parse_args()
    try:
        if not settings.database_url:
            raise ValueError("DATABASE_URL не задан")
        validate_target(settings.database_url.get_secret_value())
        cohort = args.cohort + ("-prepared-v2" if args.scenario_set == "prepared-v2" else "")
        build_judge_dataset(cohort, args.as_of)
        master_password = getpass("Пароль мастера судей (12–128 символов): ")
        worker_password = getpass("Другой пароль исполнителя судей (12–128 символов): ")
        with Session(get_engine()) as db:
            result = setup_judge_demo(db, cohort=args.cohort, as_of=args.as_of, master_password=master_password, worker_password=worker_password, photo_root=settings.photo_storage_path, scenario_set=args.scenario_set)
            db.commit()
    except ValueError as exc:
        parser.error(str(exc))
    count = 3 if args.scenario_set == "prepared-v2" else 5
    print(f"T18: {result}; {count} синтетических нарядов, MOCK, {args.scenario_set}; логины judge-{cohort}-master/worker. Пароли не выводятся.")


if __name__ == "__main__":
    main()
