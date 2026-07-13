from __future__ import annotations

from datetime import date

import pytest

from app.data.models import ContentSchedule, Project, ShopChannelAccount, Workspace
from app.integrations.social_publishing import PublishResult


def _seed_schedule(db_session, *, platform: str = "tiktok") -> tuple[ContentSchedule, ShopChannelAccount]:
    shop = Workspace(name=f"{platform}-calendar-shop")
    db_session.add(shop)
    db_session.flush()
    project = Project(workspace_id=shop.id, name="default")
    db_session.add(project)
    db_session.flush()
    account = ShopChannelAccount(
        workspace_id=shop.id,
        platform=platform,
        account_key="main",
        label="Main account",
        account_id="target-1",
        credential_env_vars={"access_token": "CRISPY_API_KEY_TEST_PUBLISH"},
        is_primary=True,
    )
    db_session.add(account)
    db_session.flush()
    schedule = ContentSchedule(
        workspace_id=shop.id,
        project_id=project.id,
        channel=platform,
        channel_account_id=account.id,
        title="Launch creative",
        scheduled_date=date(2026, 7, 15),
        state="scheduled",
        publish_payload={"media_url": "https://cdn.example.com/video.mp4"},
    )
    db_session.add(schedule)
    db_session.commit()
    return schedule, account


def test_publish_schedule_marks_posted(client, db_session, monkeypatch):
    schedule, account = _seed_schedule(db_session, platform="tiktok")

    async def fake_publish_tiktok(schedule_arg, account_arg, payload):
        assert schedule_arg.id == schedule.id
        assert account_arg.id == account.id
        assert payload["media_url"] == "https://cdn.example.com/video.mp4"
        return PublishResult(platform="tiktok", post_id="publish-123", raw={"data": {"publish_id": "publish-123"}})

    monkeypatch.setattr("app.integrations.social_publishing._publish_tiktok", fake_publish_tiktok)

    resp = client.post(f"/content-schedules/{schedule.id}/publish", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "published"
    assert body["platform_post_id"] == "publish-123"
    assert body["publish_error"] is None
    updated = db_session.get(ContentSchedule, schedule.id)
    db_session.refresh(updated)
    assert updated.published_at is not None


def test_publish_schedule_failure_is_governed(client, db_session, monkeypatch):
    schedule, _ = _seed_schedule(db_session, platform="meta")

    async def fake_publish_meta(schedule_arg, account_arg, payload):
        raise ValueError("Meta publishing requires page access")

    monkeypatch.setattr("app.integrations.social_publishing._publish_meta", fake_publish_meta)

    resp = client.post(f"/content-schedules/{schedule.id}/publish", json={})

    assert resp.status_code == 400
    updated = db_session.get(ContentSchedule, schedule.id)
    db_session.refresh(updated)
    assert updated.state == "failed"
    assert updated.publish_error == "Meta publishing requires page access"


def test_calendar_page_exposes_manual_publish_controls(client):
    resp = client.get("/dashboard/calendar")

    assert resp.status_code == 200
    assert "Publish Media URL" in resp.text
    assert "sched-channel-account" in resp.text
    assert "publishSchedule" in resp.text
    assert "/content-schedules/' + id + '/publish" in resp.text
