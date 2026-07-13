from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import ContentSchedule, ShopChannelAccount


@dataclass
class PublishResult:
    platform: str
    post_id: str
    post_url: str | None = None
    raw: dict | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _env(name: str | None) -> str:
    return os.getenv(str(name or "").strip(), "") if name else ""


def _credential(account: ShopChannelAccount, *keys: str) -> str:
    envs = account.credential_env_vars if isinstance(account.credential_env_vars, dict) else {}
    for key in keys:
        value = _env(envs.get(key))
        if value:
            return value
    return ""


def _settings(account: ShopChannelAccount) -> dict:
    return account.sync_settings if isinstance(account.sync_settings, dict) else {}


def _payload(schedule: ContentSchedule, override: dict | None = None) -> dict:
    base = dict(schedule.publish_payload or {})
    if override:
        base.update({k: v for k, v in override.items() if v is not None})
    return base


def _caption(schedule: ContentSchedule, payload: dict) -> str:
    return str(payload.get("caption") or schedule.notes or schedule.title or "").strip()


def _media_url(payload: dict) -> str:
    return str(payload.get("media_url") or payload.get("video_url") or payload.get("image_url") or "").strip()


def _is_video(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith((".mp4", ".mov", ".m4v", ".webm"))


def _resolve_account(
    db: Session,
    schedule: ContentSchedule,
    *,
    channel_account_id: str | None = None,
) -> ShopChannelAccount:
    target_id = channel_account_id or schedule.channel_account_id
    platform = "tiktok" if schedule.channel == "tiktok" else "meta"
    stmt = select(ShopChannelAccount).where(
        ShopChannelAccount.workspace_id == schedule.workspace_id,
        ShopChannelAccount.platform == platform,
        ShopChannelAccount.status != "archived",
    )
    if target_id:
        account = db.scalar(stmt.where(ShopChannelAccount.id == target_id))
    else:
        account = db.scalar(stmt.order_by(desc(ShopChannelAccount.is_primary), ShopChannelAccount.created_at).limit(1))
    if not account:
        raise ValueError(f"No active {platform} channel account is configured for this shop")
    return account


async def publish_schedule(
    db: Session,
    schedule: ContentSchedule,
    *,
    channel_account_id: str | None = None,
    publish_payload: dict | None = None,
) -> PublishResult:
    account = _resolve_account(db, schedule, channel_account_id=channel_account_id)
    payload = _payload(schedule, publish_payload)
    if account.platform == "tiktok":
        result = await _publish_tiktok(schedule, account, payload)
    elif account.platform == "meta":
        result = await _publish_meta(schedule, account, payload)
    else:
        raise ValueError(f"Publishing is not supported for platform: {account.platform}")

    schedule.channel = account.platform
    schedule.channel_account_id = account.id
    schedule.publish_payload = payload
    schedule.platform_post_id = result.post_id
    schedule.platform_post_url = result.post_url
    schedule.publish_error = None
    schedule.published_at = _utcnow()
    schedule.state = "published"
    return result


async def _publish_meta(schedule: ContentSchedule, account: ShopChannelAccount, payload: dict) -> PublishResult:
    settings = _settings(account)
    token = _credential(account, "page_access_token", "access_token")
    target_id = str(settings.get("page_id") or settings.get("publish_target_id") or account.account_id or account.account_key).strip()
    if not token:
        raise ValueError("Meta publishing requires page_access_token or access_token env var on the channel account")
    if not target_id:
        raise ValueError("Meta publishing requires page_id/publish_target_id or account_id on the channel account")

    caption = _caption(schedule, payload)
    media = _media_url(payload)
    api_version = str(settings.get("api_version") or "v21.0")
    base_url = f"https://graph.facebook.com/{api_version}"
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        if media and _is_video(media):
            response = await client.post(
                f"/{target_id}/videos",
                data={"access_token": token, "file_url": media, "description": caption},
            )
        elif media:
            response = await client.post(
                f"/{target_id}/photos",
                data={"access_token": token, "url": media, "caption": caption, "published": "true"},
            )
        else:
            response = await client.post(
                f"/{target_id}/feed",
                data={"access_token": token, "message": caption},
            )
        body = _raise_for_meta(response)
    post_id = str(body.get("post_id") or body.get("id") or "")
    if not post_id:
        raise ValueError("Meta publish response did not include a post id")
    return PublishResult(platform="meta", post_id=post_id, post_url=f"https://facebook.com/{post_id}", raw=body)


def _raise_for_meta(response: httpx.Response) -> dict:
    if response.status_code in {401, 403}:
        raise PermissionError("Meta publish token is invalid, expired, or missing publishing permissions")
    response.raise_for_status()
    body = response.json()
    if isinstance(body, dict) and body.get("error"):
        error = body["error"]
        raise ValueError(f"Meta publish error: {error.get('message') or error}")
    return body if isinstance(body, dict) else {}


async def _publish_tiktok(schedule: ContentSchedule, account: ShopChannelAccount, payload: dict) -> PublishResult:
    token = _credential(account, "user_access_token", "access_token")
    video_url = _media_url(payload)
    if not token:
        raise ValueError("TikTok publishing requires user_access_token or access_token env var on the channel account")
    if not video_url:
        raise ValueError("TikTok direct post requires a public video URL in publish_payload.media_url")
    caption = _caption(schedule, payload)
    privacy_level = str(payload.get("privacy_level") or "SELF_ONLY")
    post_info = {
        "title": caption[:2200],
        "privacy_level": privacy_level,
        "disable_duet": bool(payload.get("disable_duet", False)),
        "disable_comment": bool(payload.get("disable_comment", False)),
        "disable_stitch": bool(payload.get("disable_stitch", False)),
        "brand_content_toggle": bool(payload.get("brand_content_toggle", False)),
        "brand_organic_toggle": bool(payload.get("brand_organic_toggle", True)),
        "is_aigc": bool(payload.get("is_aigc", True)),
    }
    request_body = {
        "post_info": post_info,
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        },
    }
    async with httpx.AsyncClient(base_url="https://open.tiktokapis.com", timeout=30.0) as client:
        response = await client.post(
            "/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json=request_body,
        )
        body = _raise_for_tiktok(response)
    data = body.get("data") or {}
    publish_id = str(data.get("publish_id") or "")
    if not publish_id:
        raise ValueError("TikTok publish response did not include publish_id")
    return PublishResult(platform="tiktok", post_id=publish_id, post_url=None, raw=body)


def _raise_for_tiktok(response: httpx.Response) -> dict:
    if response.status_code in {401, 403}:
        raise PermissionError("TikTok publish token is invalid, expired, or missing video.publish permission")
    response.raise_for_status()
    body = response.json()
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("code") not in {None, "ok"}:
        raise ValueError(f"TikTok publish error: {error.get('message') or error.get('code')}")
    return body if isinstance(body, dict) else {}
