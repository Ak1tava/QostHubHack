"""Development/test harness until participant A connects the routers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import APIRouter, FastAPI

from app.modules.auth.router import register_auth_handlers
from app.modules.auth.router import router as auth_router
from app.modules.catalog.router import router as catalog_router
from app.modules.catalog.router import shift_router

app = FastAPI(title="НарядAI — проверка T02")
register_auth_handlers(app)
api = APIRouter(prefix="/api/v1")
api.include_router(auth_router)
api.include_router(catalog_router)
api.include_router(shift_router)
app.include_router(api)
