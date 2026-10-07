"""Build review evidence from the current immutable report and server calculations."""
import hashlib
from io import BytesIO

from PIL import Image
from sqlalchemy import or_, select

from app.modules.ai_review.schemas import ReviewInput
from app.modules.catalog.models import Material, MaterialNorm, WorkCode
from app.modules.photos.storage import FileSystemPhotoStorage
from app.modules.work_orders.models import MaterialUsage, Photo, WorkOrder, WorkOrderInterval
from app.modules.work_orders.queries import report_view


def build_input(db, order, report):
    view = report_view(db, order, report)
    materials = []
    for usage in db.scalars(select(MaterialUsage).where(MaterialUsage.submission_id == report.id)
                            .order_by(MaterialUsage.material_id)):
        material = db.get(Material, usage.material_id)
        norm = db.scalar(select(MaterialNorm).where(
            MaterialNorm.equipment_id == order.equipment_id,
            MaterialNorm.work_code_id == report.work_code_id,
            MaterialNorm.material_id == usage.material_id))
        materials.append(dict(id=f"material:{usage.material_id}", material_id=str(usage.material_id),
                              name=material.name if material else '', unit=material.unit if material else '',
                              quantity=float(usage.quantity), norm_quantity=float(norm.quantity) if norm else None,
                              status=('above_norm' if usage.quantity > norm.quantity else 'within_norm') if norm else 'no_norm'))
    photos = []
    # Immutable report photos and earlier before evidence from its worker or issuing master.
    query = select(Photo).where(Photo.work_order_id == order.id, or_(
        Photo.submission_id == report.id,
        (Photo.type == 'before') & (Photo.uploaded_by.in_([report.worker_id, order.master_id]))
        & (Photo.received_at <= report.submitted_at),
    )).order_by(Photo.id)
    for photo in db.scalars(query):
        historical = db.scalar(select(Photo.id).where(
            Photo.id != photo.id, Photo.received_at < photo.received_at,
            or_(Photo.content_hash == photo.content_hash,
                (Photo.perceptual_hash == photo.perceptual_hash) if photo.perceptual_hash else False),
        ).limit(1))
        photos.append(dict(id=f"photo:{photo.id}", phase=photo.type, quality='unknown',
                           content_fingerprint=photo.content_hash,
                           duplicate_of=f"photo:{historical}" if historical else None))
    minutes = sum(max(0, ((row.end_at or report.submitted_at) - row.start_at).total_seconds()) / 60
                  for row in db.scalars(select(WorkOrderInterval).where(
                      WorkOrderInterval.work_order_id == order.id, WorkOrderInterval.kind == 'active',
                      WorkOrderInterval.start_at <= report.submitted_at)))
    timing = [dict(id='timing:submission', duration_minutes=round(minutes, 2), norm_minutes=None,
                   late_minutes=max(0, (report.submitted_at - order.due_at).total_seconds() / 60),
                   status='late' if report.submitted_at > order.due_at else 'within_window')]
    code = db.get(WorkCode, report.work_code_id)
    checklist = [dict(id='checklist:report_fields', code='report_fields', required=True,
                      complete=not any(e != 'after_photo' for e in view.missing_evidence),
                      detail=f"Шифр: {code.code if code else 'отсутствует'}"),
                 dict(id='checklist:mandatory_after_photo', code='mandatory_after_photo',
                      required=order.work_type == 'emergency',
                      complete=bool(view.after_photo_ids) or order.work_type != 'emergency'),
                 dict(id='checklist:work_type', code='work_type', work_type=order.work_type, complete=True)]
    return ReviewInput(work_order_id=order.id, submission_revision=report.revision,
                       assignment_version=order.assignment_version, problem=order.description,
                       work_description=report.work_description, material_checks=materials,
                       timing_checks=timing, photo_refs=photos, checklist=checklist)


def read_images(db, report, review_input, root):
    from app.modules.ai_review.provider import ImageEvidence
    storage = FileSystemPhotoStorage(root)
    images, refs = {}, []
    order = db.get(WorkOrder, report.work_order_id)
    for source in review_input.photo_refs:
        ref = dict(source)
        from uuid import UUID
        photo = db.get(Photo, UUID(ref['id'].removeprefix('photo:')))
        associated = photo and photo.work_order_id == report.work_order_id and (
            photo.submission_id == report.id or (photo.type == 'before'
                and photo.uploaded_by in {report.worker_id, order.master_id if order else None}
                and photo.received_at <= report.submitted_at))
        try:
            if not associated:
                raise ValueError('invalid_photo_association')
            content = storage.readable_path(photo.storage_key).read_bytes()
            if hashlib.sha256(content).hexdigest() != photo.content_hash:
                raise ValueError('photo_hash_mismatch')
            with Image.open(BytesIO(content)) as image:
                image.load()
                if min(image.size) < 160:
                    raise ValueError('photo_too_small')
                image = image.convert('RGB')
                image.thumbnail((1600, 1600))
                output = BytesIO()
                image.save(output, format='JPEG', quality=85)
            images[ref['id']] = ImageEvidence(media_type='image/jpeg', data=output.getvalue())
        except (OSError, ValueError, Image.DecompressionBombError):
            ref['quality'] = 'unusable'
        refs.append(ref)
    return review_input.model_copy(update={'photo_refs': refs}), images
