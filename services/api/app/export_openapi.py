import json

from app.core.config import REPO_ROOT
from app.main import app


def main() -> None:
    destination = REPO_ROOT / "packages" / "contracts" / "openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Exported packages/contracts/openapi.json")


if __name__ == "__main__":
    main()
