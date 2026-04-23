from collections.abc import Generator
import os
from pathlib import Path
from threading import RLock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.data.base import Base


settings = get_settings()
_state_lock = RLock()


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _build_engine(database_url: str):
    return create_engine(
        database_url,
        echo=settings.debug,
        future=True,
        connect_args=_sqlite_connect_args(database_url),
    )


_active_database_url = settings.database_url
engine = _build_engine(_active_database_url)
_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)


def _sqlite_url_to_path(database_url: str) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    raw = database_url.removeprefix("sqlite:///")
    if raw == ":memory:":
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _path_to_sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve()}"


def get_active_database_url() -> str:
    return _active_database_url


def list_local_sqlite_database_urls(search_root: Path | None = None) -> list[str]:
    active_path = _sqlite_url_to_path(_active_database_url)
    roots: list[Path] = []
    if active_path:
        roots.append(active_path.parent)
    roots.append(search_root or Path.cwd())

    seen: set[str] = set()
    urls: list[str] = []
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__"}
    for root in roots:
        root = root.resolve()
        for current_dir, dir_names, file_names in os.walk(root):
            dir_names[:] = [name for name in dir_names if name not in skip_dirs and not name.startswith(".pytest_cache")]
            for name in file_names:
                if not name.endswith(".db"):
                    continue
                path = Path(current_dir) / name
                url = _path_to_sqlite_url(path)
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
    if _active_database_url not in seen:
        urls.insert(0, _active_database_url)
    return sorted(urls, key=lambda item: (0 if item == _active_database_url else 1, item))


def switch_database_url(database_url: str) -> str:
    global _active_database_url, engine, _session_factory
    normalized = database_url.strip()
    if not normalized:
        raise ValueError("database url cannot be empty")
    with _state_lock:
        if normalized == _active_database_url:
            return _active_database_url
        new_engine = _build_engine(normalized)
        with new_engine.connect():
            pass
        Base.metadata.create_all(bind=new_engine)
        old_engine = engine
        _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=new_engine, class_=Session)
        engine = new_engine
        _active_database_url = normalized
        old_engine.dispose()
    return _active_database_url


def SessionLocal() -> Session:
    return _session_factory()


def init_db() -> None:
    from app.data import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
