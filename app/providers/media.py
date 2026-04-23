from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


class LocalMediaProvider:
    """Stores generated media artifacts in local filesystem for MVP."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def write_text_artifact(self, run_id: str, filename: str, content: str) -> str:
        run_dir = self.settings.assets_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / filename
        path.write_text(content, encoding="utf-8")
        return str(path)

    def reserve_binary_artifact(self, run_id: str, filename: str) -> str:
        run_dir = self.settings.assets_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / filename
        if not path.exists():
            path.write_bytes(b"")
        return str(path)

    def write_binary_artifact(self, run_id: str, filename: str, content: bytes) -> str:
        run_dir = self.settings.assets_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / filename
        path.write_bytes(content)
        return str(path)
