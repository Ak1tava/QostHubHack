"""Private image storage, decoded content and current object authorization."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from conftest import sign_in
from work_order_helpers import add_user, headers, seed_order


def test_photo_module_exists():
    assert (Path(__file__).parents[1] / "app/modules/photos/service.py").is_file()


def image_bytes(fmt="JPEG", *, size=(32, 24), exif=False):
    from PIL import Image

    output = BytesIO()
    image = Image.new("RGB", size, "blue")
    metadata = Image.Exif()
    if exif:
        metadata[0x010E] = "Private camera metadata"
    image.save(output, format=fmt, exif=metadata if exif else b"")
    return output.getvalue()


@pytest.fixture
def photo_client(database, monkeypatch, tmp_path):
    from app.core.config import settings
    from app.core.db import get_db
    from app.modules.auth.router import register_auth_handlers, router as auth_router

    app = FastAPI()
    register_auth_handlers(app)
    api = APIRouter(prefix="/api/v1")
    api.include_router(auth_router)
    if (Path(__file__).parents[1] / "app/modules/photos/router.py").is_file():
        from app.modules.photos.router import router as photo_router
        api.include_router(photo_router)
    app.include_router(api)
    app.dependency_overrides[get_db] = lambda: database["session"]
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:5173")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "photo_storage_path", tmp_path)
    with TestClient(app, base_url="http://localhost:5173") as client:
        yield client


def upload(client, order_id, token, *, content=None, mime="image/jpeg", type="after", **data):
    return client.post(
        f"/api/v1/work-orders/{order_id}/photos",
        headers=headers(token), data={"type": type, **data},
        files={"file": ("../../untrusted.jpg", content if content is not None else image_bytes(), mime)},
    )


@pytest.mark.parametrize("fmt,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_upload_stores_normalized_private_image(photo_client, database, tmp_path, fmt, mime):
    from PIL import Image
    from app.modules.work_orders.models import Photo

    order = seed_order(database, "IN_PROGRESS")
    token = sign_in(photo_client)
    original = image_bytes(fmt, exif=True)
    response = upload(photo_client, order["id"], token, content=original, mime=mime,
                      captured_at="2026-10-04T10:00:00+05:00")
    assert response.status_code == 201, response.text
    body = response.json()
    photo = database["session"].get(Photo, UUID(body["id"]))
    assert body["work_order_id"] == order["id"] and body["type"] == "after"
    assert body["read_url"] == f"/api/v1/photos/{photo.id}"
    assert photo.uploaded_by == database["worker"].id
    assert photo.content_hash == sha256((tmp_path / photo.storage_key).read_bytes()).hexdigest()
    assert photo.perceptual_hash and len(photo.perceptual_hash) == 16
    assert photo.captured_at == datetime(2026, 10, 4, 5, tzinfo=timezone.utc)
    assert Path(photo.storage_key).name == photo.storage_key
    assert len(list(tmp_path.iterdir())) == 1
    with Image.open(tmp_path / photo.storage_key) as image:
        assert not image.getexif()
    download = photo_client.get(body["read_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == mime
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("content,mime", [
    (b"not an image", "image/jpeg"),
    (b"\xff\xd8\xff" + b"broken", "image/jpeg"),
    (b"<svg></svg>", "image/svg+xml"),
    (b"", "image/jpeg"),
])
def test_reject_invalid_image_without_file_or_row(photo_client, database, tmp_path, content, mime):
    from app.modules.work_orders.models import Photo

    order = seed_order(database)
    response = upload(photo_client, order["id"], sign_in(photo_client), content=content, mime=mime)
    assert response.status_code == 422, response.text
    assert database["session"].scalar(select(func.count()).select_from(Photo)) == 0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("case", ["mismatch", "too_large", "too_wide", "too_many_pixels", "naive_time", "invalid_type"])
def test_reject_limits_and_metadata(photo_client, database, tmp_path, case):
    order = seed_order(database)
    kwargs = {
        "mismatch": {"content": image_bytes("PNG"), "mime": "image/jpeg"},
        "too_large": {"content": b"x" * (5 * 1024 * 1024 + 1)},
        "too_wide": {"content": image_bytes(size=(8193, 1))},
        "too_many_pixels": {"content": image_bytes(size=(4097, 4096))},
        "naive_time": {"captured_at": "2026-10-04T10:00:00"},
        "invalid_type": {"type": "other"},
    }[case]
    response = upload(photo_client, order["id"], sign_in(photo_client), **kwargs)
    assert response.status_code == 422, response.text
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("status", ["ISSUED", "ACCEPTED", "QUEUED", "IN_PROGRESS", "PAUSED", "REWORK"])
def test_responsible_worker_can_upload_before_or_after(photo_client, database, status):
    order = seed_order(database, status)
    response = upload(photo_client, order["id"], sign_in(photo_client), type="before")
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("status", ["REJECTED", "SUBMITTED", "AI_REVIEW", "CLOSED", "CANCELLED"])
def test_upload_is_blocked_when_evidence_is_frozen(photo_client, database, tmp_path, status):
    order = seed_order(database, status)
    response = upload(photo_client, order["id"], sign_in(photo_client))
    assert response.status_code == 409, response.text
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("login,expected", [("master", 403), ("outsider", 404)])
def test_non_responsible_actor_cannot_upload(photo_client, database, tmp_path, login, expected):
    order = seed_order(database)
    response = upload(photo_client, order["id"], sign_in(photo_client, login))
    assert response.status_code == expected, response.text
    assert list(tmp_path.iterdir()) == []


def test_brigade_member_can_read_but_only_responsible_uploads(photo_client, database):
    member = add_user(database, "member", brigade_id=database["brigade"].id)
    order = seed_order(database, assignee_id=None, brigade_id=member.brigade_id,
                       responsible_id=database["worker"].id)
    photo = upload(photo_client, order["id"], sign_in(photo_client)).json()
    member_token = sign_in(photo_client, "member")
    assert photo_client.get(photo["read_url"]).status_code == 200
    assert upload(photo_client, order["id"], member_token).status_code == 403


def test_download_requires_current_order_access(photo_client, database):
    from app.modules.work_orders.models import WorkOrder

    order = seed_order(database)
    photo = upload(photo_client, order["id"], sign_in(photo_client)).json()
    sign_in(photo_client, "master")
    assert photo_client.get(photo["read_url"]).status_code == 200
    sign_in(photo_client, "outsider")
    assert photo_client.get(photo["read_url"]).status_code == 404
    assert photo_client.get(f"/api/v1/photos/{uuid4()}").status_code == 404
    sign_in(photo_client)
    db_order = database["session"].get(WorkOrder, UUID(order["id"]))
    db_order.assignee_id = database["outsider"].id
    database["session"].commit()
    assert photo_client.get(photo["read_url"]).status_code == 404
    photo_client.cookies.clear()
    assert photo_client.get(photo["read_url"]).status_code == 401


def test_upload_requires_authentication_and_csrf(photo_client, database, tmp_path):
    order = seed_order(database)
    assert upload(photo_client, order["id"], "invalid").status_code == 401
    sign_in(photo_client)
    assert upload(photo_client, order["id"], "invalid").status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_storage_compensates_database_commit_failure(photo_client, database, tmp_path, monkeypatch):
    from app.modules.photos.service import PhotoService, PhotoUpload
    from starlette.datastructures import Headers, UploadFile

    order = seed_order(database)
    upload_file = UploadFile(BytesIO(image_bytes()), filename="photo.jpg",
                             headers=Headers({"content-type": "image/jpeg"}))

    def fail_commit():
        raise RuntimeError("Synthetic database failure")

    monkeypatch.setattr(database["session"], "commit", fail_commit)
    with pytest.raises(RuntimeError, match="Synthetic database failure"):
        PhotoService(database["session"]).store_photo(UUID(order["id"]), database["worker"],
                                                      PhotoUpload(upload_file, "after"))
    assert list(tmp_path.iterdir()) == []
    from app.modules.work_orders.models import Photo
    assert database["session"].scalar(select(func.count()).select_from(Photo)) == 0


def test_storage_failure_does_not_leave_row(photo_client, database, monkeypatch):
    from app.modules.photos.storage import FileSystemPhotoStorage
    from app.modules.work_orders.models import Photo

    order = seed_order(database)

    def fail_write(*args):
        raise OSError("Synthetic storage failure")

    monkeypatch.setattr(FileSystemPhotoStorage, "save", fail_write)
    response = upload(photo_client, order["id"], sign_in(photo_client))
    assert response.status_code == 503
    assert database["session"].scalar(select(func.count()).select_from(Photo)) == 0


def test_failed_storage_collision_preserves_existing_file(photo_client, database, tmp_path, monkeypatch):
    from app.modules.photos import service

    order = seed_order(database)
    fixed_id = uuid4()
    existing = tmp_path / (fixed_id.hex + ".jpg")
    existing.write_bytes(b"Existing committed photo")
    monkeypatch.setattr(service, "uuid4", lambda: fixed_id)
    response = upload(photo_client, order["id"], sign_in(photo_client))
    assert response.status_code == 503
    assert existing.read_bytes() == b"Existing committed photo"


def test_missing_or_unsafe_storage_key_returns_404(photo_client, database, tmp_path):
    from app.modules.work_orders.models import Photo

    order = seed_order(database)
    photo = upload(photo_client, order["id"], sign_in(photo_client)).json()
    row = database["session"].get(Photo, UUID(photo["id"]))
    (tmp_path / row.storage_key).unlink()
    assert photo_client.get(photo["read_url"]).status_code == 404
    row.storage_key = "../secret"
    database["session"].commit()
    assert photo_client.get(photo["read_url"]).status_code == 404


@pytest.mark.parametrize("change,expected", [("submit", 409), ("reassign", 404)])
def test_upload_rechecks_order_after_waiting_for_transition_lock(photo_client, database, tmp_path, change, expected):
    from app.core.security import AuthError
    from app.modules.auth.models import User
    from app.modules.photos.service import PhotoService, PhotoUpload
    from app.modules.work_orders.models import Photo, WorkOrder
    from starlette.datastructures import Headers, UploadFile

    order = seed_order(database, "IN_PROGRESS")
    order_id = UUID(order["id"])
    actor_id = database["worker"].id
    replacement_id = database["outsider"].id
    db = database["session"]
    locked = db.scalar(select(WorkOrder).where(WorkOrder.id == order_id)
                       .with_for_update(key_share=True))
    started = Event()
    process = {}

    def concurrent_upload():
        with Session(database["engine"], expire_on_commit=False) as session:
            actor = session.get(User, actor_id)
            process["pid"] = session.scalar(text("SELECT pg_backend_pid()"))
            started.set()
            file = UploadFile(BytesIO(image_bytes()), filename="test.jpg",
                              headers=Headers({"content-type": "image/jpeg"}))
            try:
                PhotoService(session).store_photo(order_id, actor, PhotoUpload(file, "after"))
            except AuthError as error:
                return error.status_code
            return 201

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(concurrent_upload)
        try:
            assert started.wait(3)
            deadline = monotonic() + 3
            waiting = False
            with database["engine"].connect() as observer:
                while monotonic() < deadline:
                    waiting = observer.scalar(text(
                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": process["pid"]})
                    observer.commit()
                    if waiting:
                        break
                    sleep(0.02)
            assert waiting, "Upload must wait for the work order transition lock"
            if change == "submit":
                locked.status = "SUBMITTED"
            else:
                locked.assignee_id = replacement_id
                locked.assignment_version += 1
            db.commit()
            assert future.result(timeout=5) == expected
        finally:
            db.rollback()
    assert db.scalar(select(func.count()).select_from(Photo)) == 0
    assert list(tmp_path.iterdir()) == []
