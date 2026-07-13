from __future__ import annotations

import io

from sqlalchemy import select

from app.data.models import GmMemory, PerformanceSnapshot
from app.integrations.models import MetaInsightsRow
from app.integrations.tiktok import TikTokProvider


def test_tiktok_sync_imports_performance(client, db_session, monkeypatch):
    monkeypatch.setenv("CRISPY_API_KEY_TIKTOK", "test-token")
    monkeypatch.setenv("CRISPY_API_KEY_TIKTOK_ADVERTISER", "adv-1")

    async def fake_fetch_ad_performance(self):
        return [
            MetaInsightsRow(
                date_start="2026-07-01",
                date_stop="2026-07-07",
                campaign_id="tt-camp-1",
                campaign_name="TikTok Prospecting",
                ad_id="tt-ad-1",
                ad_name="Hook test",
                creative_id="tt-creative-1",
                impressions=2500,
                clicks=125,
                spend=75.0,
                conversions=12,
                revenue=240.0,
                ctr=5.0,
                cpc=0.6,
                cpa=6.25,
                roas=3.2,
            )
        ]

    async def fake_close(self):
        return None

    monkeypatch.setattr(TikTokProvider, "fetch_ad_performance", fake_fetch_ad_performance)
    monkeypatch.setattr(TikTokProvider, "close", fake_close)

    resp = client.post(
        "/integrations/tiktok/sync",
        params={"workspace_name": "w-tt", "project_name": "p-tt", "sync_type": "performance"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["platform"] == "tiktok"
    assert payload["status"] == "completed"
    assert payload["items_synced"] == 1

    snapshots = db_session.scalars(select(PerformanceSnapshot)).all()
    assert len(snapshots) == 1
    metrics = snapshots[0].metrics
    assert metrics["platform"] == "tiktok"
    assert metrics["platform_ad_id"] == "tt-ad-1"
    assert metrics["extra_metrics"]["roas"] == 3.2

    memory = db_session.scalar(select(GmMemory).where(GmMemory.source_type == "tiktok_sync"))
    assert memory is not None
    assert memory.content["total_spend"] == 75.0
    assert memory.content["overall_roas"] == 3.2

    health = client.get("/integrations/health", params={"workspace_name": "w-tt", "project_name": "p-tt"})
    rows = {item["platform"]: item for item in health.json()["platforms"]}
    assert rows["tiktok"]["ready"] is True
    assert rows["tiktok"]["latest_sync"]["status"] == "completed"


def test_tiktok_offline_csv_import_uses_ad_performance_contract(client, db_session):
    csv_content = (
        "creative_key,ad_id,impressions,clicks,spend,conversions,attributed_revenue\n"
        "tt-offline-1,tt-ad-1,2000,100,50,10,150\n"
    ).encode("utf-8")

    resp = client.post(
        "/data-dashboard/offline-csv-import/tiktok",
        data={"workspace_name": "w-tt-csv", "project_name": "p-tt-csv"},
        files={"file": ("tiktok.csv", io.BytesIO(csv_content), "text/csv")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["platform"] == "tiktok"
    assert payload["snapshots_created"] == 1

    snapshot = db_session.scalar(select(PerformanceSnapshot))
    assert snapshot is not None
    assert snapshot.metrics["platform"] == "tiktok"
    assert snapshot.metrics["offline_platform"] == "tiktok"
