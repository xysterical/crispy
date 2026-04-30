from __future__ import annotations

import logging
from typing import Any

import httpx

from app.integrations.calendar_base import BaseCalendarProvider, CalendarScheduleData

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion database property names — kept as constants so they can be
# customised later without touching the provider logic.
PROP_TITLE = "Title"
PROP_DATE = "Date"
PROP_CHANNEL = "Channel"
PROP_STATUS = "Status"
PROP_CRISPY_LINK = "Crispy Link"
PROP_NOTES = "Notes"

CHANNEL_OPTIONS = [
    {"name": "Meta Ads", "color": "blue"},
    {"name": "TikTok", "color": "black"},
    {"name": "YouTube", "color": "red"},
    {"name": "Google Ads", "color": "green"},
    {"name": "Amazon", "color": "orange"},
]

STATUS_OPTIONS = [
    {"name": "Draft", "color": "gray"},
    {"name": "Scheduled", "color": "yellow"},
    {"name": "Published", "color": "green"},
    {"name": "Failed", "color": "red"},
    {"name": "Cancelled", "color": "brown"},
]


def _channel_label(channel: str) -> str:
    mapping = {
        "meta": "Meta Ads",
        "tiktok": "TikTok",
        "youtube": "YouTube",
        "google": "Google Ads",
        "amazon": "Amazon",
    }
    return mapping.get(channel, channel)


def _state_label(state: str) -> str:
    return state.capitalize()


class NotionProvider(BaseCalendarProvider):
    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._api_key = config.get("api_key", "")
        self._database_id = config.get("database_id", "")
        self._client = httpx.AsyncClient(
            base_url=NOTION_API_BASE,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # connection check
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        try:
            resp = await self._client.get(f"/databases/{self._database_id}")
            if resp.status_code == 200:
                return True
            logger.warning("Notion test_connection http %s: %s", resp.status_code, resp.text[:300])
            return False
        except Exception as exc:
            logger.warning("Notion test_connection error: %s", exc)
            return False

    # ------------------------------------------------------------------
    # push / update / delete
    # ------------------------------------------------------------------

    async def push_schedule(self, data: CalendarScheduleData) -> str:
        properties = self._build_properties(data)
        payload: dict[str, Any] = {
            "parent": {"database_id": self._database_id},
            "properties": properties,
        }
        resp = await self._client.post("/pages", json=payload)
        resp.raise_for_status()
        body = resp.json()
        page_id = body["id"]
        logger.info("Notion page created %s", page_id)
        return page_id

    async def update_schedule(self, external_id: str, data: CalendarScheduleData) -> None:
        properties = self._build_properties(data)
        resp = await self._client.patch(f"/pages/{external_id}", json={"properties": properties})
        resp.raise_for_status()

    async def delete_schedule(self, external_id: str) -> None:
        resp = await self._client.patch(
            f"/pages/{external_id}", json={"archived": True}
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # pull (reserved)
    # ------------------------------------------------------------------

    async def pull_schedules(self, since: str | None = None) -> list[CalendarScheduleData]:
        results: list[CalendarScheduleData] = []
        filter_clause: dict[str, Any] | None = None
        if since:
            filter_clause = {
                "property": PROP_DATE,
                "date": {"on_or_after": since},
            }
        payload: dict[str, Any] = {"page_size": 100}
        if filter_clause:
            payload["filter"] = filter_clause

        while True:
            resp = await self._client.post(f"/databases/{self._database_id}/query", json=payload)
            resp.raise_for_status()
            body = resp.json()
            for page in body.get("results", []):
                parsed = self._parse_page(page)
                if parsed:
                    results.append(parsed)
            if not body.get("has_more"):
                break
            payload["start_cursor"] = body.get("next_cursor")

        return results

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _build_properties(self, data: CalendarScheduleData) -> dict[str, Any]:
        props: dict[str, Any] = {
            PROP_TITLE: {
                "title": [{"text": {"content": data.title[:256]}}]
            },
            PROP_DATE: {
                "date": {
                    "start": data.scheduled_date,
                }
            },
            PROP_CHANNEL: {
                "select": {"name": _channel_label(data.channel)}
            },
            PROP_STATUS: {
                "status": {"name": _state_label(data.state)}
            },
            PROP_NOTES: {
                "rich_text": [
                    {"text": {"content": (data.notes or "")[:2000]}}
                ]
            },
        }
        if data.scheduled_time:
            props[PROP_DATE]["date"]["start"] = (
                f"{data.scheduled_date}T{data.scheduled_time}:00"
            )
        if data.crispy_variant_url:
            props[PROP_CRISPY_LINK] = {"url": data.crispy_variant_url}
        return props

    def _parse_page(self, page: dict) -> CalendarScheduleData | None:
        try:
            props = page.get("properties", {})
            title_text = ""
            title_prop = props.get(PROP_TITLE, {})
            for t in title_prop.get("title", []):
                title_text += t.get("plain_text", "")

            date_value = ""
            date_prop = props.get(PROP_DATE, {})
            d = date_prop.get("date", {})
            if d:
                date_value = (d.get("start") or "")[:10]

            channel_value = ""
            ch_prop = props.get(PROP_CHANNEL, {})
            sel = ch_prop.get("select")
            if sel:
                channel_value = sel.get("name", "")

            status_value = "draft"
            st_prop = props.get(PROP_STATUS, {})
            st = st_prop.get("status")
            if st:
                status_value = st.get("name", "").lower()

            notes_text = ""
            notes_prop = props.get(PROP_NOTES, {})
            for rt in notes_prop.get("rich_text", []):
                notes_text += rt.get("plain_text", "")

            variant_url = ""
            link_prop = props.get(PROP_CRISPY_LINK, {})
            if link_prop.get("url"):
                variant_url = link_prop["url"]

            return CalendarScheduleData(
                title=title_text,
                scheduled_date=date_value,
                channel=channel_value,
                state=status_value,
                notes=notes_text or None,
                crispy_variant_url=variant_url or None,
                external_id=page["id"],
            )
        except Exception:
            logger.exception("Failed to parse Notion page %s", page.get("id"))
            return None

    async def close(self) -> None:
        await self._client.aclose()
