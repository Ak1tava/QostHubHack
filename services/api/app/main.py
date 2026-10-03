from typing import Literal

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from app.core.config import settings


app = FastAPI(title=settings.app_name, version="0.1.0")


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


@app.get("/health/live", response_model=LivenessResponse, tags=["health"])
def liveness() -> LivenessResponse:
    return LivenessResponse()


api_router = APIRouter(prefix="/api/v1")
# T01 registers actual T02 routers here, before including api_router in app.
app.include_router(api_router)
