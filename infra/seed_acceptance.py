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
print("PASS: synthetic browser accounts created without printing secrets")
