import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.db import get_db
from app.core.security import AuthError
from app.modules.auth import service


def test_production_app_exposes_real_contracts_under_one_prefix():
    paths = main.app.openapi()["paths"]
    assert {
        "/api/v1/auth/csrf", "/api/v1/auth/login", "/api/v1/auth/me",
        "/api/v1/auth/logout", "/api/v1/catalog/{kind}", "/api/v1/shift",
        "/health/live", "/health/ready",
    } <= paths.keys()
    assert not any("/api/v1/api/v1" in path for path in paths)


def test_production_app_disposes_engine_at_shutdown(monkeypatch):
    disposed = []
    monkeypatch.setattr(main, "dispose_engine", lambda: disposed.append(True), raising=False)
    with TestClient(main.app) as client:
        assert client.get("/health/live").status_code == 200
        assert disposed == []
    assert disposed == [True]


@pytest.mark.parametrize("payload,status,code", [
    ({"login": "worker", "password": "0042"}, 403, "csrf_failed"),
    ({"login": "worker", "password": "0042", "role": "admin"}, 422, "validation_error"),
])
def test_production_auth_errors_are_safe_and_not_cached(monkeypatch, payload, status, code):
    def reject(*args):
        raise AuthError(403, "csrf_failed", "Проверка безопасности запроса не пройдена")

    monkeypatch.setattr(service, "login", reject)
    main.app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(main.app) as client:
            response = client.post("/api/v1/auth/login", json=payload)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        assert response.headers["cache-control"] == "no-store"
        assert "0042" not in response.text
    finally:
        main.app.dependency_overrides.clear()
