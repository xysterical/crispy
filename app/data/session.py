from collections.abc import Generator
import os
from pathlib import Path
from threading import RLock

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.data.base import Base


settings = get_settings()
_state_lock = RLock()


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


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False, "timeout": 15}
    return {}


def _build_engine(database_url: str):
    connect_args = _sqlite_connect_args(database_url)
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        from sqlalchemy.pool import NullPool

        kwargs["poolclass"] = NullPool
        # Enable WAL mode once at engine creation so it sticks
        import sqlite3 as _sqlite3

        path = _sqlite_url_to_path(database_url)
        if path and path.exists():
            raw = _sqlite3.connect(str(path), timeout=15)
            raw.execute("PRAGMA journal_mode=WAL")
            raw.close()
    engine = create_engine(
        database_url,
        echo=settings.debug,
        future=True,
        connect_args=connect_args,
        **kwargs,
    )
    return engine


_active_database_url = settings.database_url
engine = _build_engine(_active_database_url)
_session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)


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
        apply_runtime_migrations(new_engine)
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
    apply_runtime_migrations(engine)


def _add_column_if_missing(target_engine, table_name: str, column_name: str, ddl_sql: str) -> None:
    inspector = inspect(target_engine)
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with target_engine.begin() as conn:
        conn.execute(text(ddl_sql))


def apply_runtime_migrations(target_engine) -> None:
    # lightweight migration path without alembic, compatible with sqlite/postgresql
    _add_column_if_missing(target_engine, "product", "product_code", "ALTER TABLE product ADD COLUMN product_code VARCHAR(128)")
    _add_column_if_missing(target_engine, "pipeline_run", "product_code", "ALTER TABLE pipeline_run ADD COLUMN product_code VARCHAR(128)")
    _add_column_if_missing(target_engine, "pipeline_run", "industry_code", "ALTER TABLE pipeline_run ADD COLUMN industry_code VARCHAR(128)")
    _add_column_if_missing(target_engine, "pipeline_run", "creative_preset", "ALTER TABLE pipeline_run ADD COLUMN creative_preset VARCHAR(64)")
    _add_column_if_missing(target_engine, "pipeline_run", "creative_specs", "ALTER TABLE pipeline_run ADD COLUMN creative_specs JSON")
    _add_column_if_missing(target_engine, "pipeline_run", "pipeline_mode", "ALTER TABLE pipeline_run ADD COLUMN pipeline_mode VARCHAR(32)")
    _add_column_if_missing(target_engine, "pipeline_run", "enable_research", "ALTER TABLE pipeline_run ADD COLUMN enable_research BOOLEAN")
    _add_column_if_missing(target_engine, "pipeline_run", "manual_research_brief", "ALTER TABLE pipeline_run ADD COLUMN manual_research_brief TEXT")
    _add_column_if_missing(target_engine, "pipeline_run", "business_context", "ALTER TABLE pipeline_run ADD COLUMN business_context JSON")
    _add_column_if_missing(target_engine, "pipeline_run", "category_tags", "ALTER TABLE pipeline_run ADD COLUMN category_tags JSON")
    _add_column_if_missing(target_engine, "stage_task", "failure_category", "ALTER TABLE stage_task ADD COLUMN failure_category VARCHAR(32)")
    _add_column_if_missing(target_engine, "gm_memory", "memory_scope", "ALTER TABLE gm_memory ADD COLUMN memory_scope VARCHAR(32)")
    _add_column_if_missing(target_engine, "gm_memory", "product_code", "ALTER TABLE gm_memory ADD COLUMN product_code VARCHAR(128)")
    _add_column_if_missing(target_engine, "gm_memory", "industry_code", "ALTER TABLE gm_memory ADD COLUMN industry_code VARCHAR(128)")
    _add_column_if_missing(target_engine, "gm_memory", "source_type", "ALTER TABLE gm_memory ADD COLUMN source_type VARCHAR(64)")
    _add_column_if_missing(target_engine, "gm_memory", "score_hint", "ALTER TABLE gm_memory ADD COLUMN score_hint FLOAT")
    _add_column_if_missing(target_engine, "agent_api_config", "thinking_mode", "ALTER TABLE agent_api_config ADD COLUMN thinking_mode VARCHAR(16)")
    _add_column_if_missing(target_engine, "agent_api_config", "thinking_budget_tokens", "ALTER TABLE agent_api_config ADD COLUMN thinking_budget_tokens INTEGER")
    _add_column_if_missing(target_engine, "agent_api_config", "max_output_tokens", "ALTER TABLE agent_api_config ADD COLUMN max_output_tokens INTEGER")
    _add_column_if_missing(target_engine, "agent_api_config", "request_timeout_seconds", "ALTER TABLE agent_api_config ADD COLUMN request_timeout_seconds INTEGER")
    _add_column_if_missing(target_engine, "agent_api_config", "streaming_enabled", "ALTER TABLE agent_api_config ADD COLUMN streaming_enabled BOOLEAN")
    _add_column_if_missing(target_engine, "stage_task", "priority", "ALTER TABLE stage_task ADD COLUMN priority INTEGER DEFAULT 2")
    _add_column_if_missing(target_engine, "stage_task", "max_retries", "ALTER TABLE stage_task ADD COLUMN max_retries INTEGER DEFAULT 3")
    _add_column_if_missing(target_engine, "stage_task", "retry_at", "ALTER TABLE stage_task ADD COLUMN retry_at DATETIME")
    _add_column_if_missing(target_engine, "pipeline_run", "approval_mode", "ALTER TABLE pipeline_run ADD COLUMN approval_mode VARCHAR(16) DEFAULT 'manual'")
    _add_column_if_missing(target_engine, "workspace", "industry_code", "ALTER TABLE workspace ADD COLUMN industry_code VARCHAR(128) DEFAULT 'general'")

    with target_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS agent_trace_event ("
                "id VARCHAR(36) PRIMARY KEY, "
                "run_id VARCHAR(36) NOT NULL, "
                "stage_task_id VARCHAR(36), "
                "stage_name VARCHAR(64) NOT NULL, "
                "agent_name VARCHAR(64) NOT NULL, "
                "event_type VARCHAR(64) NOT NULL, "
                "visibility VARCHAR(16), "
                "message TEXT, "
                "provider_name VARCHAR(64), "
                "model_name VARCHAR(128), "
                "payload JSON, "
                "created_at DATETIME"
                ")"
            )
        )
        conn.execute(text("UPDATE product SET product_code = 'legacy_' || id WHERE product_code IS NULL OR product_code = ''"))
        conn.execute(
            text(
                "UPDATE pipeline_run "
                "SET product_code = (SELECT product.product_code FROM product WHERE product.id = pipeline_run.product_id) "
                "WHERE product_code IS NULL OR product_code = ''"
            )
        )
        conn.execute(text("UPDATE pipeline_run SET industry_code = 'general' WHERE industry_code IS NULL OR industry_code = ''"))
        conn.execute(text("UPDATE pipeline_run SET creative_preset = 'meta_square_5s' WHERE creative_preset IS NULL OR creative_preset = ''"))
        conn.execute(text("UPDATE pipeline_run SET creative_specs = '{}' WHERE creative_specs IS NULL"))
        conn.execute(text("UPDATE pipeline_run SET pipeline_mode = 'full_multimodal' WHERE pipeline_mode IS NULL OR pipeline_mode = ''"))
        conn.execute(text("UPDATE pipeline_run SET enable_research = 0 WHERE enable_research IS NULL"))
        conn.execute(text("UPDATE pipeline_run SET manual_research_brief = '' WHERE manual_research_brief IS NULL"))
        conn.execute(text("UPDATE pipeline_run SET business_context = '{}' WHERE business_context IS NULL"))
        conn.execute(text("UPDATE pipeline_run SET category_tags = '[]' WHERE category_tags IS NULL"))
        conn.execute(text("UPDATE gm_memory SET memory_scope = 'industry' WHERE memory_scope IS NULL OR memory_scope = ''"))
        conn.execute(text("UPDATE gm_memory SET source_type = 'feedback_import' WHERE source_type IS NULL OR source_type = ''"))
        conn.execute(text("UPDATE agent_api_config SET thinking_mode = 'auto' WHERE thinking_mode IS NULL OR thinking_mode = ''"))
        conn.execute(text("UPDATE agent_api_config SET streaming_enabled = 0 WHERE streaming_enabled IS NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_product_product_code ON product(product_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pipeline_run_product_code ON pipeline_run(product_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pipeline_run_industry_code ON pipeline_run(industry_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_gm_memory_scope_product ON gm_memory(memory_scope, product_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_gm_memory_scope_industry ON gm_memory(memory_scope, industry_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_stage_task_failure_category ON stage_task(failure_category)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_variant_run_id ON run_variant(run_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_variant_status ON run_variant(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_variant_asset_run_variant ON variant_asset(run_variant_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_variant_asset_run_id ON variant_asset(run_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_variant_review_run_variant ON variant_review(run_variant_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_variant_score_run_variant ON variant_score(run_variant_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_trace_run_id ON agent_trace_event(run_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_trace_stage_task ON agent_trace_event(stage_task_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_trace_created_at ON agent_trace_event(created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_stage_task_queue ON stage_task(status, priority, created_at)"))
        conn.execute(text("UPDATE stage_task SET priority = 2 WHERE priority IS NULL"))
        conn.execute(text("UPDATE stage_task SET max_retries = 3 WHERE max_retries IS NULL"))
        conn.execute(text("UPDATE pipeline_run SET approval_mode = 'manual' WHERE approval_mode IS NULL OR approval_mode = ''"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
