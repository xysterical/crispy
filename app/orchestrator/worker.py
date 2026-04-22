from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


logger = logging.getLogger(__name__)


class PipelineWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="crispy-pipeline-worker")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def _loop(self) -> None:
        interval = max(0.2, self.settings.polling_interval_seconds)
        while not self._stop_event.is_set():
            try:
                with SessionLocal() as db:
                    task = execute_next_queued_stage(db)
                    db.commit()
                    if task:
                        logger.info("Processed task %s (%s)", task.id, task.stage_name)
            except Exception as exc:  # pragma: no cover - runtime safety
                logger.exception("Worker loop error: %s", exc)
            await asyncio.sleep(interval)


worker = PipelineWorker()

