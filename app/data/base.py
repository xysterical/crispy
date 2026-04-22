from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase

try:
    from sqlalchemy.dialects.postgresql import JSONB
except Exception:  # pragma: no cover - dialect import should exist with SQLAlchemy
    JSONB = None


class Base(DeclarativeBase):
    pass


def json_type():
    """Use JSONB on PostgreSQL and JSON elsewhere."""
    if JSONB is None:
        return JSON
    return JSON().with_variant(JSONB, "postgresql")

