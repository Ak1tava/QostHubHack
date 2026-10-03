"""Save Compose diagnostics while removing values from secret environment fields."""
from pathlib import Path
import subprocess
from urllib.parse import quote


root = Path(__file__).resolve().parents[1]
redactions = set()
env_path = root / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and value and any(part in key for part in ("PASSWORD", "SECRET", "TOKEN", "KEY", "DATABASE_URL")):
            redactions.update((value, quote(value, safe="")))

destination = root / "artifacts"
destination.mkdir(exist_ok=True)
for filename, arguments in [("compose-status.txt", ["ps", "--all"]), ("compose-logs.txt", ["logs", "--no-color", "--tail", "200"])]:
    result = subprocess.run(["docker", "compose", *arguments], cwd=root, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    for value in sorted(redactions, key=len, reverse=True):
        output = output.replace(value, "[REDACTED]")
    (destination / filename).write_text(output, encoding="utf-8")
print("Saved sanitized Compose diagnostics")
