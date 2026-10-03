from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import psycopg
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import settings


router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"


class NotReadyResponse(BaseModel):
    status: Literal["not_ready"] = "not_ready"


@router.get("/health/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    return LivenessResponse()


def _database_ready() -> bool:
    if settings.database_url is None:
        return False
    try:
        url = make_url(settings.database_url.get_secret_value())
        if url.drivername not in {"postgresql", "postgresql+psycopg"}:
            return False
        dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
        with psycopg.connect(dsn, connect_timeout=3, options="-c statement_timeout=3000") as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except (psycopg.Error, ArgumentError, ValueError, TypeError):
        return False


@router.get("/health/ready", response_model=ReadyResponse, responses={503: {"model": NotReadyResponse}})
def readiness() -> ReadyResponse | JSONResponse:
    if _database_ready():
        return ReadyResponse()
    return JSONResponse(status_code=503, content=NotReadyResponse().model_dump())
