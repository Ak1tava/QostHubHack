"""Synthetic accounts only on the disposable CI demo database."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))

from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_engine
from app.modules.auth.demo import create_demo_accounts, validate_demo_target
from app.modules.auth.models import User
from app.modules.catalog.models import Area, Equipment, Material, WorkCode
from sqlalchemy import select


if os.environ.get("CI") != "true" or not settings.database_url:
    raise SystemExit("Disposable CI database required")
url = make_url(settings.database_url.get_secret_value())
validate_demo_target(url.render_as_string(hide_password=False))
if url.host == "db":
    url = url.set(host="127.0.0.1")
settings.database_url = SecretStr(url.render_as_string(hide_password=False))
prefix, password = os.environ["E2E_LOGIN"], os.environ["E2E_PASSWORD"]
with Session(get_engine(), expire_on_commit=False) as db:
    for scenario in ("session", "credentials", "expiry", "offline"):
        create_demo_accounts(db, f"{prefix}-master-{scenario}", password, f"{prefix}-{scenario}", password)
    area = db.scalar(select(Area).where(Area.name == "Демонстрационный участок"))
    if db.scalar(select(Equipment.id).where(Equipment.area_id == area.id, Equipment.name == "Демо насос Т04")) is None:
        db.add(Equipment(name="Демо насос Т04", area_id=area.id))
        db.commit()
    if db.scalar(select(Material.id).where(Material.name == "Демо масло Т05")) is None:
        db.add(Material(name="Демо масло Т05", unit="л"))
    if db.scalar(select(WorkCode.id).where(WorkCode.code == "T05-DEMO")) is None:
        db.add(WorkCode(code="T05-DEMO", name="Демо ремонт Т05"))
    db.commit()
    for scenario in ("t04-browser", "t04-mobile", "t04-reconnect", "t04-deeplink", "t05-execution", "t05-retry", "t06-worker", "t07-review"):
        create_demo_accounts(db, f"{prefix}-master-{scenario}", password, f"{prefix}-{scenario}", password)
        worker = db.scalar(select(User).where(User.login == f"{prefix}-{scenario}"))
        worker.display_name = f"Исполнитель {scenario}"
        db.commit()
print("PASS: synthetic browser accounts created without printing secrets")
