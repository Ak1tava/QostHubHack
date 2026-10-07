from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import ErrorResponse
from app.modules.photos.schemas import PhotoType, PhotoView
from app.modules.photos.service import PhotoService, PhotoUpload

router = APIRouter(tags=["photos"])
ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}


@router.post("/work-orders/{order_id}/photos", response_model=PhotoView,
             status_code=201, responses=ERRORS)
def upload_photo(order_id: UUID, response: Response,
                 file: Annotated[UploadFile, File()], type: Annotated[PhotoType, Form()],
                 captured_at: Annotated[AwareDatetime | None, Form()] = None,
                 expected_version: Annotated[int | None, Form(ge=1)] = None,
                 assignment_version: Annotated[int | None, Form(ge=1)] = None,
                 actor: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return PhotoService(db).store_photo(order_id, actor, PhotoUpload(file, type, captured_at,
                                                                   expected_version, assignment_version))


@router.get("/photos/{photo_id}", response_class=FileResponse, responses=ERRORS)
def download_photo(photo_id: UUID, actor: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    photo, path = PhotoService(db).get_photo(photo_id, actor)
    return FileResponse(path, media_type=photo.mime_type,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
