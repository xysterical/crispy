from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.personas import ensure_default_personas
from app.api.routes import router
from app.core.config import get_settings
from app.data.session import init_db
from app.orchestrator.worker import worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    init_db()
    ensure_default_personas()
    if settings.enable_worker:
        await worker.start()
    try:
        yield
    finally:
        if settings.enable_worker:
            await worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
