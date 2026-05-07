from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("CRISPY_DATABASE_URL", "sqlite:///./test_crispy.db")
os.environ.setdefault("CRISPY_ENABLE_WORKER", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.data import models  # noqa: E402,F401
from app.data import session as data_session  # noqa: E402
from app.data.base import Base  # noqa: E402
from app.data.session import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402

data_session.BACKUP_DIR = Path("test_backups")
data_session.BACKUP_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    with SessionLocal() as session:
        yield session
