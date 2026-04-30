from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.base import BaseAnalyzer
from app.analytics.schemas import AdSalesLagResult
from app.data.models import GmMemory, PerformanceSnapshot


class CrossPlatformAnalyzer(BaseAnalyzer):
    def __init__(self, db: Session, project_id: str) -> None:
        self.db = db
        self.project_id = project_id

    def ad_sales_lag(
        self, product_code: str, max_lag_days: int = 7
    ) -> AdSalesLagResult:
        snapshots = self.db.scalars(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.project_id == self.project_id)
            .order_by(PerformanceSnapshot.created_at.asc())
        ).all()

        memories = self.db.scalars(
            select(GmMemory)
            .where(
                GmMemory.project_id == self.project_id,
                GmMemory.memory_scope == "product",
                GmMemory.product_code == product_code,
                GmMemory.source_type == "shopify_sync",
            )
        ).all()

        if not snapshots or not memories:
            return AdSalesLagResult(
                optimal_lag_days=0,
                cross_correlation=0,
                conversion_type="uncertain",
                insufficient_data=True,
                interpretation="Need both ad performance and sales data for lag analysis.",
            )

        daily_spend: dict[str, float] = defaultdict(float)
        for snap in snapshots:
            m = snap.metrics or {}
            spend = float(m.get("spend", 0))
            if spend > 0:
                day = str(snap.period_start or snap.created_at.date())
                daily_spend[day] += spend

        daily_revenue: dict[str, float] = defaultdict(float)
        for mem in memories:
            content = mem.content or {}
            rev = float(content.get("total_revenue", 0) or content.get("daily_avg_revenue", 0))
            if rev > 0:
                day = mem.created_at.strftime("%Y-%m-%d")
                daily_revenue[day] += rev

        all_days = sorted(set(list(daily_spend.keys()) + list(daily_revenue.keys())))
        if len(all_days) < 14:
            return AdSalesLagResult(
                optimal_lag_days=0,
                cross_correlation=0,
                conversion_type="uncertain",
                insufficient_data=True,
                interpretation=f"Need at least 14 days of combined data, got {len(all_days)}.",
            )

        spend_series = [daily_spend.get(d, 0) for d in all_days]
        revenue_series = [daily_revenue.get(d, 0) for d in all_days]

        from scipy.signal import correlate

        spend_mean = sum(spend_series) / len(spend_series)
        rev_mean = sum(revenue_series) / len(revenue_series)
        spend_std = (sum((s - spend_mean) ** 2 for s in spend_series) / len(spend_series)) ** 0.5
        rev_std = (sum((r - rev_mean) ** 2 for r in revenue_series) / len(revenue_series)) ** 0.5

        if spend_std <= 0 or rev_std <= 0:
            return AdSalesLagResult(
                optimal_lag_days=0,
                cross_correlation=0,
                conversion_type="uncertain",
                insufficient_data=True,
                interpretation="No variance in spend or revenue data.",
            )

        max_ccf = -1
        best_lag = 0
        for lag in range(0, max_lag_days + 1):
            shifted_rev = revenue_series[lag:] + [0] * lag
            cross_cov = sum(
                (spend_series[i] - spend_mean) * (shifted_rev[i] - rev_mean)
                for i in range(len(spend_series))
            ) / len(spend_series)
            ccf = cross_cov / (spend_std * rev_std)
            if ccf > max_ccf:
                max_ccf = ccf
                best_lag = lag

        if best_lag <= 1:
            conv_type = "impulse"
        elif best_lag <= 4:
            conv_type = "considered"
        else:
            conv_type = "uncertain"

        return AdSalesLagResult(
            optimal_lag_days=best_lag,
            cross_correlation=round(max_ccf, 4),
            conversion_type=conv_type,
            interpretation=(
                f"Best ad-to-sale lag: {best_lag} days (corr={max_ccf:.3f}). "
                f"Conversion type: {conv_type}."
            ),
        )

    def analyze_ad_sales_lag(
        self, product_code: str, max_lag_days: int = 7
    ) -> AdSalesLagResult:
        return self.ad_sales_lag(product_code, max_lag_days)
