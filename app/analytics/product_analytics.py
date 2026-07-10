from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.base import BaseAnalyzer
from app.analytics.schemas import ProductContributionResult, SalesVelocityResult
from app.data.models import GmMemory, PerformanceSnapshot


class ProductAnalyzer(BaseAnalyzer):
    def __init__(self, db: Session, project_id: str) -> None:
        self.db = db
        self.project_id = project_id

    def sales_velocity(
        self, product_code: str, window_days: int = 30
    ) -> SalesVelocityResult:
        half = window_days // 2
        today = date.today()

        snapshots = self.db.scalars(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.project_id == self.project_id)
            .order_by(PerformanceSnapshot.created_at.desc())
        ).all()

        daily_data: dict[str, float] = defaultdict(float)
        for snap in snapshots:
            m = snap.metrics or {}
            revenue = float(m.get("revenue", 0))
            if snap.period_start:
                daily_data[str(snap.period_start)] += revenue
            else:
                daily_data[str(snap.created_at.date())] += revenue

        if not daily_data:
            return SalesVelocityResult(
                current_daily_avg=0,
                previous_daily_avg=0,
                change_pct=0,
                trend="stable",
                trend_confidence=0,
                insufficient_data=True,
                interpretation=f"No order data found for {product_code}.",
            )

        sorted_dates = sorted(daily_data.keys())
        current_dates = sorted_dates[-half:]
        previous_dates = sorted_dates[-window_days:-half]

        current_vals = [daily_data[d] for d in current_dates]
        previous_vals = [daily_data[d] for d in previous_dates]

        current_avg = sum(current_vals) / len(current_vals) if current_vals else 0
        previous_avg = sum(previous_vals) / len(previous_vals) if previous_vals else 0

        if not self._check_sample_size(len(current_vals)):
            return SalesVelocityResult(
                current_daily_avg=round(current_avg, 2),
                previous_daily_avg=round(previous_avg, 2),
                change_pct=round((current_avg - previous_avg) / previous_avg * 100, 1) if previous_avg > 0 else 0,
                trend="stable",
                trend_confidence=0,
                insufficient_data=True,
                interpretation=f"Insufficient data: only {len(current_vals)} days available.",
            )

        outliers = self._iqr_outliers(current_vals)
        outlier_dates = [current_dates[i] for i in outliers]

        from scipy.stats import linregress

        x = list(range(len(current_vals)))
        reg = linregress(x, current_vals)
        slope = reg.slope
        p_value = reg.pvalue if reg.pvalue is not None else 1.0
        confidence = round(1 - p_value, 4)

        if p_value < 0.05 and slope > 0:
            trend = "rising"
        elif p_value < 0.05 and slope < 0:
            trend = "declining"
        else:
            trend = "stable"

        change_pct = round((current_avg - previous_avg) / previous_avg * 100, 1) if previous_avg > 0 else 0

        return SalesVelocityResult(
            current_daily_avg=round(current_avg, 2),
            previous_daily_avg=round(previous_avg, 2),
            change_pct=change_pct,
            trend=trend,
            trend_confidence=confidence,
            outliers_detected=outlier_dates,
            interpretation=(
                f"近{half}天日均营收${current_avg:.2f}，环比{'增长' if change_pct > 0 else '下降'}{abs(change_pct)}%，"
                f"趋势{'向上' if trend == 'rising' else '向下' if trend == 'declining' else '平稳'}"
                f"({confidence:.0%}置信度)"
            ),
        )

    def contribution(
        self, product_codes: list[str], period_days: int = 30
    ) -> ProductContributionResult:
        today = date.today()
        cutoff = today.strftime("%Y-%m-%d") if period_days <= 0 else ""

        memories = self.db.scalars(
            select(GmMemory)
            .where(
                GmMemory.project_id == self.project_id,
                GmMemory.memory_scope == "product",
                GmMemory.source_type.in_(["shopify_sync", "feedback_import", "offline_csv_import"]),
            )
            .order_by(GmMemory.created_at.desc())
        ).all()

        contributions: dict[str, float] = {}
        for mem in memories:
            code = mem.product_code or ""
            if product_codes and code not in product_codes:
                continue
            content = mem.content or {}
            revenue = float(content.get("total_revenue", 0) or content.get("daily_avg_revenue", 0))
            if revenue > 0:
                contributions[code] = contributions.get(code, 0) + revenue

        total = sum(contributions.values())
        if total <= 0:
            return ProductContributionResult(
                pareto_threshold=0,
                insufficient_data=True,
                interpretation="No revenue data found for contribution analysis.",
            )

        for code in contributions:
            contributions[code] = round(contributions[code] / total * 100, 2)

        sorted_contrib = sorted(contributions.items(), key=lambda item: item[1], reverse=True)
        cumulative = 0
        pareto_threshold = 0
        for code, pct in sorted_contrib:
            cumulative += pct
            pareto_threshold += 1
            if cumulative >= 80:
                break

        hero_products = [code for code, pct in sorted_contrib[:pareto_threshold]]
        tail_products = [code for code, pct in sorted_contrib if pct < 5]

        return ProductContributionResult(
            pareto_threshold=pareto_threshold,
            hero_products=hero_products,
            tail_products=tail_products,
            contributions=dict(sorted_contrib),
            interpretation=(
                f"Top {pareto_threshold} products contribute 80% of revenue. "
                f"Hero products: {hero_products}. "
                f"{len(tail_products)} tail products identified."
            ),
        )

    def analyze_product_sales_velocity(
        self, product_code: str, window_days: int = 30
    ) -> SalesVelocityResult:
        return self.sales_velocity(product_code, window_days)

    def analyze_product_contribution(
        self, product_codes: list[str] | None = None, period_days: int = 30
    ) -> ProductContributionResult:
        return self.contribution(product_codes or [], period_days)
