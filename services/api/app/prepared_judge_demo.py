"""Explicit seed-only examples. Never registered as a runtime provider."""

import hashlib
from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import uuid4

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.modules.ai_review.schemas import Finding, ProviderOutcome, ReviewResult, StagePlan

MARKER = "Подготовленный демонстрационный результат"
MODEL = "t18-prepared-demo-provider-v2"
VERDICTS = ("accepted", "requires_rework", "human_review")


class PreparedJudgeProvider:
    def __init__(self, verdict):
        if verdict not in VERDICTS:
            raise ValueError("Unknown prepared scenario")
        self.verdict = verdict

    def review(self, value, plan, *, images, previous=None):
        after = [p["id"] for p in value.photo_refs if p.get("phase") == "after"]
        photos = [p["id"] for p in value.photo_refs]
        if self.verdict == "accepted":
            code, severity = "work_matches_problem", "info"
            message = "Описание очистки соответствует заявке; синтетический рисунок после показывает очищенный кожух."
        elif self.verdict == "requires_rework":
            code, severity = "work_problem_mismatch", "error"
            message = "Заявка требует очистить кожух, а отчёт описывает замену лампы. Выполненные работы не соответствуют заявке."
        else:
            code, severity = "comparison_unavailable", "warning"
            message = "По синтетическим рисункам нельзя подтвердить полноту очистки кожуха. Видимый результат должен проверить мастер."
        return ProviderOutcome(is_mock=True, legible_refs=after, result=ReviewResult(
            verdict=self.verdict, score=5 if self.verdict == "accepted" else 2 if self.verdict == "requires_rework" else None,
            findings=[Finding(code=code, severity=severity, message=message,
                              evidence_refs=["problem", "work_description", *photos])],
            missing_evidence=[], limitations=[MARKER, "MOCK: синтетические рисунки; OpenAI не вызывался."]))


def prepared_png(photo):
    """Legible diagrams with genuinely different pixels for every evidence item."""
    digest = hashlib.sha256(str(photo["id"]).encode()).digest()
    image = Image.new("RGB", (320, 240), (240, 244, 248))
    draw = ImageDraw.Draw(image)
    draw.text((12, 10), "SYNTHETIC DEMO - NOT A REPAIR PHOTO", fill=(20, 30, 40))
    draw.text((12, 28), photo["type"].upper(), fill=(20, 30, 40))
    draw.rectangle((60, 60, 260, 205), fill=(50, 110, 170), outline=(20, 30, 40), width=5)
    if photo["type"] == "before":
        for x in range(75, 251, 22):
            draw.ellipse((x, 90, x + 14, 130 + digest[x % 32] % 40), fill=(130, 70, 30))
    else:
        draw.rectangle((82, 82, 238, 180), fill=(180, 215, 235))
        draw.line((95, 135, 130, 165, 220, 100), fill=(20, 120, 50), width=10)
    # Distinct visible stripe patterns also prevent cross-order pixel duplicates.
    for i, byte in enumerate(digest):
        draw.rectangle((i * 10, 220, i * 10 + 9, 239), fill=(byte, 255 - byte, digest[(i + 1) % 32]))
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def prepare_dataset(dataset):
    from starlette.datastructures import Headers, UploadFile
    from app.modules.photos.service import _normalize
    from app.modules.work_orders.templates import snapshot
    reports = dataset["submissions"][:3]
    ids = {r["work_order_id"] for r in reports}
    dataset["work_orders"] = [o for o in dataset["work_orders"] if o["id"] in ids]
    dataset["submissions"] = reports
    dataset["photos"] = [p for p in dataset["photos"] if p["work_order_id"] in ids]
    dataset["work_order_events"] = [e for e in dataset["work_order_events"]
                                    if e["work_order_id"] in ids and e["version"] <= 2]
    for name in ("ai_reviews", "master_decisions", "material_usage", "work_order_intervals", "downtime_intervals"):
        dataset[name] = []
    now = datetime.now(timezone.utc)
    for order in dataset["work_orders"]:
        order.update(status="ACCEPTED", version=2, queue_position=None, work_type="emergency",
                     due_at=now + timedelta(hours=2),
                     template_snapshot=snapshot("visible_element"),
                     description="[T18 СИНТЕТИКА] Очистить загрязнённый кожух оборудования.")
        for e in dataset["work_order_events"]:
            if e["work_order_id"] == order["id"]:
                e["payload"]["after"]["due_at"] = order["due_at"].isoformat()
                if e["payload"]["before"]:
                    e["payload"]["before"]["due_at"] = order["due_at"].isoformat()
    for index, report in enumerate(reports):
        report["template_answers"] = [dict(id=item["id"], checked=True)
                                      for item in snapshot("visible_element")["checklist"]]
        report.update(no_materials_used=True, work_description=(
            "[T18 СИНТЕТИКА] Заменена лампа освещения." if index == 1
            else "[T18 СИНТЕТИКА] Кожух очищен; видимые загрязнения удалены."))
    for photo in dataset["photos"]:
        photo["storage_key"] = f"{photo['id']}.png"
        content = prepared_png(photo)
        photo["content_hash"] = hashlib.sha256(content).hexdigest()
        upload = UploadFile(BytesIO(content), filename="synthetic.png", headers=Headers({"content-type": "image/png"}))
        photo["perceptual_hash"] = _normalize(upload)[4]


def save_prepared_reviews(db, dataset, photo_root):
    from app.modules.ai_review.inputs import build_input, read_images
    from app.modules.ai_review.jobs_models import ReviewJob, ReviewReceipt
    from app.modules.ai_review.rules import assess_rules
    from app.modules.ai_review.service import finalize_result
    from app.modules.work_orders import queries
    from app.modules.work_orders.internal import apply_internal
    from app.modules.work_orders.models import OutboxEvent, Submission, WorkOrder
    from app.modules.work_orders.schemas import ActionCommand, InternalActionCommand
    from app.modules.work_orders.service import WorkOrderService
    from app.workers.reviews import _save_final

    class TransactionalSeedService(WorkOrderService):
        # Keep the standard command guards while preserving caller-owned atomic setup.
        def _finish(self, record, order, actor, status):
            self.db.flush()
            result = queries.view(self.db, order, actor)
            record.work_order_id, record.response_status = order.id, status
            record.response_body = result.model_dump(mode="json")
            return result

    from app.modules.auth.models import User
    worker = db.get(User, dataset["users"][1]["id"])
    service = TransactionalSeedService(db)
    for index, row in enumerate(dataset["submissions"]):
        report = db.get(Submission, row["id"])
        order = db.get(WorkOrder, report.work_order_id)
        service.apply_action(order.id, worker, ActionCommand(action="start", expected_version=order.version),
                             f"prepared-v2-start:{order.id}")
        report.submitted_at = datetime.now(timezone.utc)
        db.flush()
        for action in ("submit", "begin_review"):
            apply_internal(db, order.id, InternalActionCommand(action=action,
                expected_version=order.version, assignment_version=order.assignment_version,
                submission_id=report.id), actor=worker if action == "submit" else None)
        value, images = read_images(db, report, build_input(db, order, report), photo_root)
        rules = assess_rules(value)
        plan = StagePlan(stage="primary", model=MODEL, reasoning="low", prompt_version="t18-prepared-v2")
        outcome = PreparedJudgeProvider(VERDICTS[index]).review(value, plan, images=images)
        result = finalize_result(value, rules, outcome)
        if result.verdict != VERDICTS[index]:
            raise ValueError(f"Демонстрационный сценарий отклонён: {result.verdict}; "
                             + ", ".join(f.code for f in result.findings))
        now, token = datetime.now(timezone.utc), uuid4()
        job = ReviewJob(submission_id=report.id, work_order_id=order.id, submission_revision=report.revision,
                        assignment_version=order.assignment_version, order_version=order.version,
                        status="running", stage="primary", lease_token=token, lease_until=now + timedelta(minutes=3),
                        calls=[dict(is_mock=True, status="completed", model=MODEL, provider=MODEL, latency_ms=0)],
                        stage_outputs={"primary": outcome.model_dump(mode="json")})
        db.add(job)
        db.flush()
        if not _save_final(db, order, job, report, (job.id, token),
                           lambda: datetime.now(timezone.utc), result, plan):
            raise ValueError("Демонстрационная проверка потеряла lease")
        # Receipt only for this seed's submit: later real submissions reach the real worker.
        for outbox in db.scalars(select(OutboxEvent).where(OutboxEvent.work_order_id == order.id)):
            db.add(ReviewReceipt(outbox_id=outbox.id, consumed_at=now))
    db.flush()
