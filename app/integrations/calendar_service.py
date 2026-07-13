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


def _get_notion_credentials() -> tuple[str, str]:
    """Resolve Notion API key and database ID from environment.

    All credentials use the CRISPY_API_KEY_* prefix — this is the single
    naming convention for every env var in the project.
    """
    api_key = os.getenv("CRISPY_API_KEY_NOTION", "")
    database_id = os.getenv("CRISPY_API_KEY_NOTION_DATABASE", "")
    return api_key, database_id


def _get_notion_provider(db: Session) -> NotionProvider | None:
    """Build a NotionProvider from env vars. Returns None if not configured."""
    api_key, database_id = _get_notion_credentials()
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


async def push_to_notion(db: Session, schedule: ContentSchedule, variant_url: str = "") -> tuple[str | None, str | None]:
    """Push a ContentSchedule to Notion.

    Returns (page_id, error_message). On success error_message is None.
    On failure page_id is None and error_message describes what went wrong.
    """
    provider = _get_notion_provider(db)
    if not provider:
        return None, "Notion not configured (missing API key or Database ID)"
    try:
        data = _to_calendar_data(schedule, variant_url)
        if schedule.notion_page_id:
            await provider.update_schedule(schedule.notion_page_id, data)
            return schedule.notion_page_id, None
        else:
            page_id = await provider.push_schedule(data)
            return page_id, None
    except Exception as exc:
        logger.exception("Notion push failed for schedule %s", schedule.id)
        msg = str(exc)
        # Notion API returns helpful JSON errors — try to extract
        if hasattr(exc, "response") and exc.response is not None:
            try:
                body = exc.response.json()
                msg = body.get("message", msg)
            except Exception:
                pass
        return None, msg
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
    api_key, database_id = _get_notion_credentials()
    if not api_key and not database_id:
        return {"ok": False, "error": "Notion API key and Database ID are not configured"}
    if not api_key:
        return {"ok": False, "error": "Notion API key is not set (CRISPY_API_KEY_NOTION)"}
    if not database_id:
        return {"ok": False, "error": "Notion Database ID is not set (CRISPY_API_KEY_NOTION_DATABASE)"}

    provider = _get_notion_provider(db)
    if not provider:
        return {"ok": False, "error": "Failed to initialise Notion provider"}
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
    channel_account_id: str | None = None,
    scheduled_time: str | None = None,
    publish_payload: dict | None = None,
    notes: str | None = None,
    variant_url: str = "",
) -> ContentSchedule:
    schedule = ContentSchedule(
        workspace_id=workspace_id,
        project_id=project_id,
        variant_id=variant_id or None,
        campaign_id=campaign_id or None,
        channel_account_id=channel_account_id or None,
        title=title,
        channel=channel,
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        publish_payload=publish_payload or {},
        notes=notes,
        state="scheduled",
    )
    db.add(schedule)
    db.flush()

    notion_id, notion_error = await push_to_notion(db, schedule, variant_url)
    if notion_id:
        schedule.notion_page_id = notion_id
        schedule.notion_sync_error = None
    elif notion_error:
        schedule.notion_sync_error = notion_error
    db.flush()

    return schedule
