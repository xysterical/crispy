from __future__ import annotations

import httpx

from app.integrations.base import BaseIntegrationProvider
from app.integrations.models import MetaCampaignData, MetaInsightsRow


class MetaProvider(BaseIntegrationProvider):
    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.access_token = str(config.get("access_token", ""))
        self.ad_account_id = str(config.get("ad_account_id", ""))
        self.api_version = "v21.0"
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def test_connection(self) -> bool:
        try:
            response = await self.client.get(
                f"/act_{self.ad_account_id}",
                params={"access_token": self.access_token, "fields": "id"},
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def fetch_campaigns(self) -> list[MetaCampaignData]:
        all_campaigns: list[MetaCampaignData] = []
        url = f"/act_{self.ad_account_id}/campaigns"
        params: dict = {
            "access_token": self.access_token,
            "fields": "id,name,objective,status",
            "limit": 100,
        }
        while url:
            response = await self.client.get(url, params=params if url == f"/act_{self.ad_account_id}/campaigns" else None)
            if response.status_code == 401:
                raise PermissionError("Meta access token is invalid or expired")
            if response.status_code == 400:
                err = response.json().get("error", {})
                raise ValueError(f"Meta API error: {err.get('message', 'unknown')}")
            response.raise_for_status()
            data = response.json()
            for campaign in data.get("data", []):
                all_campaigns.append(MetaCampaignData(
                    campaign_id=str(campaign["id"]),
                    name=campaign.get("name", ""),
                    objective=campaign.get("objective", ""),
                    status=campaign.get("status", ""),
                    ad_account_id=self.ad_account_id,
                ))
            paging = data.get("paging", {})
            url = paging.get("next", "")
            params = {}
        return all_campaigns

    async def fetch_ad_performance(
        self,
        date_preset: str = "last_30d",
    ) -> list[MetaInsightsRow]:
        all_rows: list[MetaInsightsRow] = []
        url = f"/act_{self.ad_account_id}/insights"
        params: dict = {
            "access_token": self.access_token,
            "fields": (
                "ad_id,ad_name,creative,"
                "impressions,clicks,spend,"
                "actions,action_values,"
                "date_start,date_stop"
            ),
            "date_preset": date_preset,
            "level": "ad",
            "limit": 100,
        }
        first = True
        while url:
            response = await self.client.get(url, params=params if first else None)
            if response.status_code == 401:
                raise PermissionError("Meta access token is invalid or expired")
            if response.status_code == 400:
                err = response.json().get("error", {})
                raise ValueError(f"Meta API error: {err.get('message', 'unknown')}")
            response.raise_for_status()
            data = response.json()
            first = False

            for insight in data.get("data", []):
                actions_list = insight.get("actions", [])
                action_values_list = insight.get("action_values", [])

                conversions = 0
                for action in actions_list:
                    if action.get("action_type") in ("offsite_conversion", "purchase", "onsite_conversion"):
                        conversions += int(action.get("value", 0))

                revenue = 0.0
                for av in action_values_list:
                    if av.get("action_type") in ("offsite_conversion", "purchase"):
                        revenue += float(av.get("value", 0))

                imps = int(insight.get("impressions", 0))
                clicks = int(insight.get("clicks", 0))
                spend = float(insight.get("spend", 0))

                ctr = (clicks / imps * 100) if imps > 0 else 0.0
                cpc = (spend / clicks) if clicks > 0 else 0.0
                cpa = (spend / conversions) if conversions > 0 else 0.0
                roas = (revenue / spend) if spend > 0 else 0.0

                creative_data = insight.get("creative", {})
                creative_id = str(creative_data.get("id")) if isinstance(creative_data, dict) and creative_data.get("id") else None

                all_rows.append(MetaInsightsRow(
                    date_start=insight.get("date_start", ""),
                    date_stop=insight.get("date_stop", ""),
                    ad_id=str(insight.get("ad_id", "")),
                    ad_name=insight.get("ad_name", ""),
                    creative_id=creative_id,
                    impressions=imps,
                    clicks=clicks,
                    spend=spend,
                    conversions=conversions,
                    revenue=revenue,
                    ctr=round(ctr, 4),
                    cpc=round(cpc, 4),
                    cpa=round(cpa, 2),
                    roas=round(roas, 4),
                ))

            paging = data.get("paging", {})
            url = paging.get("next", "")
            params = {}

        return all_rows

    async def fetch_ads(self) -> list[dict]:
        all_ads: list[dict] = []
        url = f"/act_{self.ad_account_id}/ads"
        params: dict = {
            "access_token": self.access_token,
            "fields": "id,name,creative{id},campaign_id,adset_id",
            "limit": 100,
        }
        first = True
        while url:
            response = await self.client.get(url, params=params if first else None)
            if response.status_code == 401:
                raise PermissionError("Meta access token is invalid or expired")
            response.raise_for_status()
            data = response.json()
            first = False
            for ad in data.get("data", []):
                creative_data = ad.get("creative", {})
                all_ads.append({
                    "ad_id": str(ad["id"]),
                    "ad_name": ad.get("name", ""),
                    "creative_id": str(creative_data.get("id")) if isinstance(creative_data, dict) and creative_data.get("id") else None,
                    "campaign_id": str(ad.get("campaign_id", "")),
                    "adset_id": str(ad.get("adset_id", "")),
                })
            paging = data.get("paging", {})
            url = paging.get("next", "")
            params = {}
        return all_ads
