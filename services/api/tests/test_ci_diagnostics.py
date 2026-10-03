from pathlib import Path
import runpy
import shutil
import subprocess
from types import SimpleNamespace
from urllib.parse import quote


def test_ci_diagnostics_redact_file_and_environment_secrets(tmp_path, monkeypatch):
    script = tmp_path / "infra" / "collect_diagnostics.py"
    script.parent.mkdir()
    source = Path(__file__).resolve().parents[3] / "infra" / script.name
    shutil.copyfile(source, script)
    app_password = "test-only-db/password"
    browser_password = "00test-only-browser/password"
    url = f"postgresql+psycopg://user:{app_password}@db/qosthub_demo"
    (tmp_path / ".env").write_text(f"POSTGRES_PASSWORD={app_password}\nDATABASE_URL={url}\n")
    monkeypatch.setenv("E2E_PASSWORD", browser_password)
    output = "\n".join([app_password, quote(app_password, safe=""), browser_password, quote(browser_password, safe=""), url])
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=output, stderr=""))
    runpy.run_path(str(script), run_name="__main__")
    logs = list((tmp_path / "artifacts").glob("*.txt"))
    assert len(logs) == 2
    for log in logs:
        content = log.read_text()
        assert "[REDACTED]" in content
        for secret in (app_password, browser_password, url):
            assert secret not in content
            assert quote(secret, safe="") not in content
