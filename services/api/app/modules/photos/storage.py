"""Private filesystem adapter; client filenames are never storage keys."""

from pathlib import Path
from uuid import UUID


class FileSystemPhotoStorage:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def path(self, key: str) -> Path:
        name = Path(key)
        if name.name != key or name.suffix not in {".jpg", ".png", ".webp"}:
            raise FileNotFoundError("Invalid storage key")
        try:
            UUID(name.stem)
        except ValueError as exc:
            raise FileNotFoundError("Invalid storage key") from exc
        path = self.root / key
        if path.is_symlink() or path.resolve().parent != self.root:
            raise FileNotFoundError("Invalid storage key")
        return path

    def save(self, key: str, content: bytes) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.path(key)
        created = False
        try:
            with path.open("xb") as output:
                created = True
                path.chmod(0o600)
                output.write(content)
        except OSError:
            if created:
                path.unlink(missing_ok=True)
            raise

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def readable_path(self, key: str) -> Path:
        path = self.path(key)
        if not path.is_file():
            raise FileNotFoundError("Photo not found")
        return path
