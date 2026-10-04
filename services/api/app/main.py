from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core.config import settings
from app.core.db import dispose_engine
from app.health import router as health_router
from app.modules.auth.router import register_auth_handlers, router as auth_router
from app.modules.catalog.router import router as catalog_router, shift_router
from app.modules.work_orders.router import router as work_orders_router
from app.modules.work_orders.realtime import router as events_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        dispose_engine()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
register_auth_handlers(app)


app.include_router(health_router)
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(catalog_router)
api_router.include_router(shift_router)
api_router.include_router(work_orders_router)
api_router.include_router(events_router)
app.include_router(api_router)
