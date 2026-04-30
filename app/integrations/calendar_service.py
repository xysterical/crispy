from __future__ import annotations

import logging
import os
from datetime import date, datetime, UTC

from sqlalchemy.orm import Session

from app.data.models import ContentSchedule
from app.integrations.calendar_base import BaseCalendarProvider, CalendarScheduleData
from app.integrations.notion import NotionProvider

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _get_notion_provider(db: Session) -> NotionProvider | None:
    """Build a NotionProvider from env vars. Returns None if not configured."""
    from app.core.config import get_settings

    settings = get_settings()
    api_key = settings.notion_api_key or os.getenv("CRISPY_API_KEY_NOTION", "")
    database_id = settings.notion_database_id or os.getenv("CRISPY_NOTION_DATABASE_ID", "")
    if not api_key or not database_id:
        return None
    return NotionProvider(config={"api_key": api_key, "database_id": database_id})


def _to_calendar_data(schedule: ContentSchedule, variant_url: str = "") -> CalendarScheduleData:
    return CalendarScheduleData(
        title=schedule.title,
        scheduled_date=schedule.scheduled_date.isoformat(),
        channel=schedule.channel,
        state=schedule.state,
        scheduled_time=schedule.scheduled_time,
        notes=schedule.notes,
        crispy_variant_url=variant_url or None,
        external_id=schedule.notion_page_id,
    )


async def push_to_notion(db: Session, schedule: ContentSchedule, variant_url: str = "") -> str | None:
    """Push a ContentSchedule to Notion. Returns the Notion page ID on success, None on failure."""
    provider = _get_notion_provider(db)
    if not provider:
        return None
    try:
        data = _to_calendar_data(schedule, variant_url)
        if schedule.notion_page_id:
            await provider.update_schedule(schedule.notion_page_id, data)
            return schedule.notion_page_id
        else:
            page_id = await provider.push_schedule(data)
            return page_id
    except Exception:
        logger.exception("Notion push failed for schedule %s", schedule.id)
        return None
    finally:
        await provider.close()


async def delete_from_notion(db: Session, notion_page_id: str) -> bool:
    provider = _get_notion_provider(db)
    if not provider:
        return False
    try:
        await provider.delete_schedule(notion_page_id)
        return True
    except Exception:
        logger.exception("Notion delete failed for page %s", notion_page_id)
        return False
    finally:
        await provider.close()


async def test_notion_connection(db: Session) -> dict:
    provider = _get_notion_provider(db)
    if not provider:
        return {"ok": False, "error": "Notion API key and Database ID are not configured"}
    try:
        ok = await provider.test_connection()
        return {"ok": ok, "error": None if ok else "Connection test failed — check credentials and database ID"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        await provider.close()


async def schedule_variant(
    db: Session,
    *,
    workspace_id: str,
    project_id: str,
    variant_id: str | None,
    campaign_id: str | None,
    title: str,
    channel: str,
    scheduled_date: date,
    scheduled_time: str | None = None,
    notes: str | None = None,
    variant_url: str = "",
) -> ContentSchedule:
    schedule = ContentSchedule(
        workspace_id=workspace_id,
        project_id=project_id,
        variant_id=variant_id or None,
        campaign_id=campaign_id or None,
        title=title,
        channel=channel,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        notes=notes,
        state="scheduled",
    )
    db.add(schedule)
    db.flush()

    notion_id = await push_to_notion(db, schedule, variant_url)
    if notion_id:
        schedule.notion_page_id = notion_id
        db.flush()

    return schedule
