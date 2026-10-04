"""Revision creation and submit transition share one idempotent transaction."""
from uuid import UUID

from sqlalchemy import func, select

from app.core.security import AuthError
from app.modules.auth.models import User
from app.modules.catalog.models import Material, WorkCode
from app.modules.work_orders import queries
from app.modules.work_orders.internal import apply_internal
from app.modules.work_orders.models import MaterialUsage, Photo, Submission
from app.modules.work_orders.schemas import InternalActionCommand, SubmissionCreate, SubmissionView
from app.modules.work_orders.service import WorkOrderService, authorize, check_version, lock_order


class SubmissionService(WorkOrderService):
    def submit_order(self, order_id: UUID, actor: User, payload: SubmissionCreate, key: str) -> SubmissionView:
        try:
            record, replay = self._reserve(actor, f"POST /work-orders/{order_id}/submissions", payload, key)
            order = lock_order(self.db, order_id)
            authorize(self.db, order, actor, "submit")
            if replay:
                result = SubmissionView.model_validate(record.response_body)
                self.db.commit()
                return result
            check_version(order, payload.expected_version)
            if order.assignment_version != payload.assignment_version:
                raise AuthError(409, "assignment_conflict", "Назначение наряда изменено")
            if self.db.get(WorkCode, payload.fault_code_id) is None:
                raise AuthError(422, "invalid_work_code", "Шифр работ не найден")
            material_ids = {item.material_id for item in payload.materials}
            known = set(self.db.scalars(select(Material.id).where(Material.id.in_(material_ids)))) if material_ids else set()
            if known != material_ids:
                raise AuthError(422, "invalid_material", "Материал не найден")
            photos = list(self.db.scalars(select(Photo).where(Photo.id.in_(payload.after_photo_ids))
                          .order_by(Photo.id).with_for_update())) if payload.after_photo_ids else []
            if len(photos) != len(payload.after_photo_ids) or any(
                p.work_order_id != order.id or p.type != "after" or p.uploaded_by != actor.id
                or p.submission_id is not None for p in photos
            ):
                raise AuthError(422, "invalid_photos", "Требуются новые фото после работы, загруженные исполнителем этого наряда")
            revision = (self.db.scalar(select(func.max(Submission.revision)).where(Submission.work_order_id == order.id)) or 0) + 1
            report = Submission(work_order_id=order.id, revision=revision,
                                assignment_version=order.assignment_version, worker_id=actor.id,
                                work_description=payload.work_description, work_code_id=payload.fault_code_id,
                                no_materials_used=payload.no_materials_used, comment=payload.comment)
            self.db.add(report)
            self.db.flush()
            self.db.add_all([MaterialUsage(submission_id=report.id, material_id=item.material_id, quantity=item.quantity)
                             for item in payload.materials])
            for photo in photos:
                photo.submission_id = report.id
            apply_internal(self.db, order.id, InternalActionCommand(
                action="submit", expected_version=payload.expected_version,
                assignment_version=payload.assignment_version, submission_id=report.id,
            ), actor=actor)
            result = queries.report_view(self.db, order, report)
            record.work_order_id = order.id
            record.response_status = 201
            record.response_body = result.model_dump(mode="json")
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise


def submit_order(order_id: UUID, actor: User, payload: SubmissionCreate, key: str, *, db) -> SubmissionView:
    return SubmissionService(db).submit_order(order_id, actor, payload, key)
