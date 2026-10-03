import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.main import app


def test_export_is_stable_and_matches_runtime_schema():
    if importlib.util.find_spec("app.export_openapi") is None:
        pytest.fail("OpenAPI export command is not implemented")
    destination = Path(__file__).resolve().parents[3] / "packages/contracts/openapi.json"
    before = destination.read_bytes() if destination.exists() else None
    try:
        command = [sys.executable, "-m", "app.export_openapi"]
        env = {**os.environ, "DATABASE_URL": "invalid-url", "OPENAI_API_KEY": ""}
        first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        assert first.returncode == 0, first.stderr
        exported = destination.read_bytes()
        second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        assert second.returncode == 0, second.stderr
        assert destination.read_bytes() == exported
        schema = json.loads(exported)
        assert schema == app.openapi()
        assert "503" in schema["paths"]["/health/ready"]["get"]["responses"]
    finally:
        if before is not None:
            destination.write_bytes(before)
        elif destination.exists():
            destination.unlink()
