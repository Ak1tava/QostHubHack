from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

PhotoType = Literal["before", "after"]


class PhotoView(BaseModel):
    id: UUID
    work_order_id: UUID
    type: PhotoType
    received_at: datetime
    captured_at: datetime | None = None
    content_hash: str
    perceptual_hash: str | None
    read_url: str
