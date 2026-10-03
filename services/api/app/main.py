from fastapi import APIRouter, FastAPI

from app.core.config import settings
from app.health import router as health_router


app = FastAPI(title=settings.app_name, version="0.1.0")


app.include_router(health_router)
api_router = APIRouter(prefix="/api/v1")
# T01 registers actual T02 routers here, before including api_router in app.
app.include_router(api_router)
