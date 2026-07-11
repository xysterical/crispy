from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.data.models import ResearchTask
from app.data.session import SessionLocal
from app.services.shop_analysis import execute_next_queued_research_task

logger = logging.getLogger(__name__)


class ResearchWorker:
    def __init__(self) -> None:
        settings = get_settings()
        self._poll_interval = max(0.5, settings.polling_interval_seconds)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._started_at: datetime | None = None
        self._total_completed = 0
        self._total_failed = 0

    async def start(self) -> None:
        if self._task:
            return
        self._stop_event.clear()
        self._started_at = datetime.now(UTC)
        self._recover_orphaned_tasks()
        self._task = asyncio.create_task(self._worker_loop(), name="crispy-research-worker")
        logger.info("ResearchWorker started | poll=%.1fs", self._poll_interval)

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._started_at = None
        logger.info("ResearchWorker stopped")

    def get_status(self) -> dict[str, Any]:
        db = SessionLocal()
        try:
            rows = db.execute(select(ResearchTask.status, func.count()).group_by(ResearchTask.status)).all()
            status_counts = {row[0]: row[1] for row in rows}
            return {
                "status": "running" if self._task else "stopped",
                "status_counts": status_counts,
                "total_completed": self._total_completed,
                "total_failed": self._total_failed,
                "started_at": self._started_at.isoformat() if self._started_at else None,
            }
        finally:
            db.close()

    async def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                ran = await asyncio.to_thread(self._execute_one_task)
                if not ran:
                    await self._sleep_interruptible(self._poll_interval)
            except Exception:
                logger.exception("Research worker loop error")
                await self._sleep_interruptible(self._poll_interval)

    async def _sleep_interruptible(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _execute_one_task(self) -> bool:
        db = SessionLocal()
        try:
            status = execute_next_queued_research_task(db)
            if not status:
                return False
            if status == "completed":
                self._total_completed += 1
            elif status == "failed":
                self._total_failed += 1
            return True
        except Exception:
            db.rollback()
            self._total_failed += 1
            logger.exception("Research task execution failed")
            return False
        finally:
            db.close()

    def _recover_orphaned_tasks(self) -> None:
        db = SessionLocal()
        try:
            rows = db.scalars(select(ResearchTask).where(ResearchTask.status == "running")).all()
            for task in rows:
                task.status = "queued"
                task.error_message = "Recovered after worker restart"
            if rows:
                db.commit()
                logger.info("Recovered %d orphaned research tasks", len(rows))
        finally:
            db.close()


research_worker = ResearchWorker()
