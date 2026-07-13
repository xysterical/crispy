from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import httpx

from app.integrations.base import BaseIntegrationProvider
from app.integrations.models import MetaInsightsRow, TikTokCampaignData


class TikTokProvider(BaseIntegrationProvider):
    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.access_token = str(config.get("access_token", ""))
        self.advertiser_id = str(config.get("advertiser_id", ""))
        self.api_version = str(config.get("api_version") or "v1.3")
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return f"https://business-api.tiktok.com/open_api/{self.api_version}"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        return self._client

    @property
    def headers(self) -> dict[str, str]:
        return {"Access-Token": self.access_token}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def test_connection(self) -> bool:
        if not self.access_token or not self.advertiser_id:
            return False
        try:
            response = await self.client.get(
                "/advertiser/info/",
                headers=self.headers,
                params={"advertiser_ids": json.dumps([self.advertiser_id])},
            )
            return response.status_code == 200 and int((response.json().get("code") or 0)) == 0
        except Exception:
            return False

    async def fetch_campaigns(self) -> list[TikTokCampaignData]:
        rows: list[TikTokCampaignData] = []
        page = 1
        while True:
            response = await self.client.get(
                "/campaign/get/",
                headers=self.headers,
                params={
                    "advertiser_id": self.advertiser_id,
                    "page": page,
                    "page_size": 100,
                },
            )
            self._raise_for_tiktok_error(response)
            body = response.json()
            data = body.get("data") or {}
            for item in data.get("list") or []:
                rows.append(
                    TikTokCampaignData(
                        campaign_id=str(item.get("campaign_id") or ""),
                        name=str(item.get("campaign_name") or item.get("name") or ""),
                        objective=str(item.get("objective_type") or item.get("objective") or ""),
                        status=str(item.get("operation_status") or item.get("status") or ""),
                        advertiser_id=self.advertiser_id,
                    )
                )
            page_info = data.get("page_info") or {}
            if page >= int(page_info.get("total_page") or page):
                break
            page += 1
        return [row for row in rows if row.campaign_id]

    async def fetch_ad_performance(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[MetaInsightsRow]:
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=30))
        rows: list[MetaInsightsRow] = []
        page = 1
        while True:
            response = await self.client.get(
                "/report/integrated/get/",
                headers=self.headers,
                params={
                    "advertiser_id": self.advertiser_id,
                    "report_type": "BASIC",
                    "data_level": "AUCTION_AD",
                    "dimensions": json.dumps(["ad_id"]),
                    "metrics": json.dumps([
                        "campaign_id",
                        "campaign_name",
                        "ad_id",
                        "ad_name",
                        "impressions",
                        "clicks",
                        "spend",
                        "conversion",
                        "total_purchase_value",
                        "ctr",
                        "cpc",
                        "cost_per_conversion",
                    ]),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "page": page,
                    "page_size": 1000,
                },
            )
            self._raise_for_tiktok_error(response)
            body = response.json()
            data = body.get("data") or {}
            for item in data.get("list") or []:
                metrics = item.get("metrics") or item
                dimensions = item.get("dimensions") or {}
                rows.append(
                    MetaInsightsRow(
                        date_start=start.isoformat(),
                        date_stop=end.isoformat(),
                        campaign_id=_str(dimensions.get("campaign_id") or metrics.get("campaign_id")) or None,
                        campaign_name=_str(metrics.get("campaign_name")),
                        ad_id=_str(dimensions.get("ad_id") or metrics.get("ad_id")),
                        ad_name=_str(metrics.get("ad_name")),
                        creative_id=_str(metrics.get("creative_id")) or None,
                        impressions=_int(metrics.get("impressions")),
                        clicks=_int(metrics.get("clicks")),
                        spend=_float(metrics.get("spend")),
                        conversions=_int(metrics.get("conversion") or metrics.get("conversions")),
                        revenue=_float(metrics.get("total_purchase_value") or metrics.get("purchase_value") or metrics.get("revenue")),
                        ctr=_float(metrics.get("ctr")),
                        cpc=_float(metrics.get("cpc")),
                        cpa=_float(metrics.get("cost_per_conversion") or metrics.get("cpa")),
                        roas=_roas(metrics),
                    )
                )
            page_info = data.get("page_info") or {}
            if page >= int(page_info.get("total_page") or page):
                break
            page += 1
        return [row for row in rows if row.ad_id]

    def _raise_for_tiktok_error(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise PermissionError("TikTok access token is invalid, expired, or missing advertiser access")
        response.raise_for_status()
        body = response.json()
        if int(body.get("code") or 0) != 0:
            message = body.get("message") or body.get("msg") or "unknown TikTok API error"
            raise ValueError(f"TikTok API error: {message}")


def _str(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", ""))
    except ValueError:
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(float(str(value or 0).replace(",", "")))
    except ValueError:
        return 0


def _roas(metrics: dict) -> float:
    explicit = _float(metrics.get("roas") or metrics.get("purchase_roas"))
    if explicit:
        return explicit
    spend = _float(metrics.get("spend"))
    revenue = _float(metrics.get("total_purchase_value") or metrics.get("purchase_value") or metrics.get("revenue"))
    return round(revenue / spend, 4) if spend > 0 else 0.0
