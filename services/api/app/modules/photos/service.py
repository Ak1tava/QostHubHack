"""Decoded images and authorization are checked before persisting evidence."""

import hashlib
import logging
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.security import AuthError, can_access_order
from app.modules.auth.models import User
from app.modules.photos.schemas import PhotoType, PhotoView
from app.modules.photos.storage import FileSystemPhotoStorage
from app.modules.work_orders.models import Photo, WorkOrder
from app.modules.work_orders.queries import is_responsible
from app.modules.work_orders.service import lock_order

MAX_BYTES = 5 * 1024 * 1024
MAX_DIMENSION = 8192
MAX_PIXELS = 16 * 1024 * 1024
FORMATS = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"),
           "WEBP": ("image/webp", ".webp")}
EDITABLE_STATUSES = {"ISSUED", "ACCEPTED", "QUEUED", "IN_PROGRESS", "PAUSED", "REWORK"}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PhotoUpload:
    file: UploadFile
    type: PhotoType
    captured_at: datetime | None = None


def _invalid_image() -> AuthError:
    return AuthError(422, "invalid_photo", "Нужно изображение JPEG, PNG или WebP до 5 МБ")


def _normalize(upload: UploadFile) -> tuple[bytes, str, str, str, str]:
    content = upload.file.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
        raise _invalid_image()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                fmt = source.format
                if fmt not in FORMATS or upload.content_type != FORMATS[fmt][0]:
                    raise _invalid_image()
                width, height = source.size
                if (max(width, height) > MAX_DIMENSION or width * height > MAX_PIXELS):
                    raise _invalid_image()
                source.verify()
            with Image.open(BytesIO(content)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                mode = "RGBA" if "A" in oriented.getbands() and fmt != "JPEG" else "RGB"
                # Copy pixels into a fresh image to strip EXIF, text and other metadata.
                clean = Image.new(mode, oriented.size)
                clean.paste(oriented.convert(mode))
                small = clean.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
                pixels = list(small.get_flattened_data())
                bits = 0
                for y in range(8):
                    for x in range(8):
                        bits = (bits << 1) | (pixels[y * 9 + x] > pixels[y * 9 + x + 1])
                output = BytesIO()
                clean.save(output, format=fmt, quality=85, optimize=True)
                normalized = output.getvalue()
                if len(normalized) > MAX_BYTES:
                    raise _invalid_image()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _invalid_image() from exc
    mime, suffix = FORMATS[fmt]
    return normalized, mime, suffix, hashlib.sha256(content).hexdigest(), f"{bits:016x}"


def photo_view(photo: Photo) -> PhotoView:
    return PhotoView(id=photo.id, work_order_id=photo.work_order_id, type=photo.type,
                     received_at=photo.received_at, captured_at=photo.captured_at,
                     content_hash=photo.content_hash, perceptual_hash=photo.perceptual_hash,
                     read_url=f"/api/v1/photos/{photo.id}")


class PhotoService:
    def __init__(self, db: Session, storage: FileSystemPhotoStorage | None = None):
        self.db = db
        self.storage = storage or FileSystemPhotoStorage(settings.photo_storage_path)

    def store_photo(self, order_id: UUID, actor: User, upload: PhotoUpload) -> PhotoView:
        key = None
        stored = False
        try:
            # The same NO KEY UPDATE lock as transitions freezes status/assignment.
            order = lock_order(self.db, order_id)
            if not can_access_order(self.db, actor, order):
                raise AuthError(404, "not_found", "Объект не найден")
            if actor.role != "worker" or not is_responsible(order, actor):
                raise AuthError(403, "forbidden", "Фото добавляет ответственный исполнитель")
            if order.status not in EDITABLE_STATUSES:
                raise AuthError(409, "evidence_frozen", "Для этого состояния фото недоступны")
            if upload.type not in {"before", "after"} or (upload.captured_at is not None and
                    (upload.captured_at.tzinfo is None or upload.captured_at.utcoffset() is None)):
                raise AuthError(422, "invalid_photo", "Проверьте тип фото и время с часовым поясом")
            content, mime, suffix, content_hash, perceptual_hash = _normalize(upload.file)
            key = uuid4().hex + suffix
            try:
                self.storage.save(key, content)
                stored = True
            except OSError as exc:
                raise AuthError(503, "storage_unavailable", "Хранилище фото временно недоступно") from exc
            photo = Photo(id=uuid4(), work_order_id=order.id, uploaded_by=actor.id,
                          type=upload.type, storage_key=key, mime_type=mime,
                          content_hash=content_hash, perceptual_hash=perceptual_hash,
                          received_at=datetime.now(timezone.utc),
                          captured_at=upload.captured_at.astimezone(timezone.utc)
                          if upload.captured_at else None)
            self.db.add(photo)
            self.db.flush()
            view = photo_view(photo)
            self.db.commit()
            return view
        except Exception:
            self.db.rollback()
            if stored:
                try:
                    self.storage.delete(key)
                except OSError:
                    logger.exception("Photo rollback cleanup failed")
            raise

    def get_photo(self, photo_id: UUID, actor: User) -> tuple[Photo, Path]:
        photo = self.db.get(Photo, photo_id)
        order = self.db.get(WorkOrder, photo.work_order_id) if photo else None
        if order is None or not can_access_order(self.db, actor, order):
            raise AuthError(404, "not_found", "Объект не найден")
        try:
            return photo, self.storage.readable_path(photo.storage_key)
        except FileNotFoundError as exc:
            raise AuthError(404, "not_found", "Объект не найден") from exc


def store_photo(order_id: UUID, actor: User, upload: PhotoUpload, *, db: Session) -> PhotoView:
    return PhotoService(db).store_photo(order_id, actor, upload)
