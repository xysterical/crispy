from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.base import BaseAnalyzer
from app.analytics.schemas import CreativeCompareResult, CreativeFatigueResult, SpendEfficiencyResult
from app.data.models import PerformanceSnapshot


class AdAnalyzer(BaseAnalyzer):
    def __init__(self, db: Session, project_id: str) -> None:
        self.db = db
        self.project_id = project_id

    def creative_fatigue(
        self, creative_key: str, window_days: int = 30
    ) -> CreativeFatigueResult:
        snapshots = self.db.scalars(
            select(PerformanceSnapshot)
            .where(
                PerformanceSnapshot.project_id == self.project_id,
                PerformanceSnapshot.creative_key == creative_key,
            )
            .order_by(PerformanceSnapshot.created_at.asc())
        ).all()

        if not self._check_sample_size(len(snapshots)):
            return CreativeFatigueResult(
                ctr_trend="insufficient_data",
                ctr_slope=0,
                ctr_slope_p_value=1,
                cpc_trend="stable",
                insufficient_data=True,
                interpretation="Insufficient performance data for fatigue analysis.",
            )

        daily_ctr: dict[str, float] = defaultdict(float)
        daily_cpc: dict[str, float] = defaultdict(float)
        for snap in snapshots:
            m = snap.metrics or {}
            day = str(snap.period_start or snap.created_at.date())
            ctr = float(m.get("ctr", 0))
            cpc = float(m.get("cpc", 0))
            if ctr > 0:
                daily_ctr[day] = max(daily_ctr.get(day, 0), ctr)
            if cpc > 0:
                daily_cpc[day] = max(daily_cpc.get(day, 0), cpc)

        sorted_days = sorted(daily_ctr.keys())
        if len(sorted_days) < 7:
            return CreativeFatigueResult(
                ctr_trend="insufficient_data",
                ctr_slope=0,
                ctr_slope_p_value=1,
                cpc_trend="stable",
                insufficient_data=True,
                interpretation=f"Only {len(sorted_days)} days of CTR data, need at least 7.",
            )

        from scipy.stats import linregress

        ctr_vals = [daily_ctr[d] for d in sorted_days]
        outliers = self._iqr_outliers(ctr_vals)
        outlier_dates = [sorted_days[i] for i in outliers]

        x = list(range(len(sorted_days)))
        reg = linregress(x, ctr_vals)
        slope = reg.slope
        p_value = reg.pvalue if reg.pvalue is not None else 1.0

        fatigued = slope < 0 and p_value < 0.05
        days_remaining = None
        if fatigued and slope < 0:
            last_ctr = ctr_vals[-1]
            threshold_ctr = max(0.5, last_ctr * 0.3)
            if last_ctr > threshold_ctr:
                days_remaining = int((threshold_ctr - last_ctr) / slope)

        cpc_vals = [daily_cpc.get(d, 0) for d in sorted_days if daily_cpc.get(d, 0) > 0]
        cpc_trend = "stable"
        if len(cpc_vals) >= 7:
            cpc_reg = linregress(list(range(len(cpc_vals))), cpc_vals)
            if cpc_reg.slope > 0 and (cpc_reg.pvalue or 1) < 0.05:
                cpc_trend = "rising"

        return CreativeFatigueResult(
            ctr_trend="fatigued" if fatigued else "healthy",
            ctr_slope=round(slope, 6),
            ctr_slope_p_value=round(p_value, 4),
            cpc_trend=cpc_trend,
            estimated_effective_days_remaining=days_remaining,
            outliers_detected=outlier_dates,
            interpretation=(
                f"CTR is {'declining' if fatigued else 'stable'} "
                f"(slope={slope:.6f}/day, p={p_value:.4f}). "
                + (f"Estimated {days_remaining} effective days remaining. " if days_remaining else "")
                + ("CPC is also rising, compounding fatigue." if cpc_trend == "rising" else "")
            ),
        )

    def compare_creatives(
        self, creative_keys: list[str], metric: str = "ctr"
    ) -> CreativeCompareResult:
        if len(creative_keys) < 2:
            return CreativeCompareResult(
                insufficient_data=True,
                interpretation="Need at least 2 creatives to compare.",
            )

        per_creative: dict[str, list[dict]] = defaultdict(list)
        for key in creative_keys:
            snapshots = self.db.scalars(
                select(PerformanceSnapshot)
                .where(
                    PerformanceSnapshot.project_id == self.project_id,
                    PerformanceSnapshot.creative_key == key,
                )
            ).all()
            for snap in snapshots:
                per_creative[key].append(snap.metrics or {})

        results = []
        for key in creative_keys:
            metrics_list = per_creative[key]
            if not self._check_sample_size(len(metrics_list)):
                results.append({
                    "creative_key": key,
                    "snapshots": len(metrics_list),
                    "insufficient_data": True,
                })
                continue

            ctr_vals = [float(m.get("ctr", 0)) for m in metrics_list if float(m.get("ctr", 0)) > 0]
            if not ctr_vals:
                results.append({"creative_key": key, "snapshots": len(metrics_list), "insufficient_data": True})
                continue

            total_impressions = sum(int(m.get("impressions", 0)) for m in metrics_list)
            total_clicks = sum(int(m.get("clicks", 0)) for m in metrics_list)
            low, center, high = self._wilson_ci(total_clicks, total_impressions)

            cpa_vals = [float(m.get("cpa", 0)) for m in metrics_list if float(m.get("cpa", 0)) > 0]
            roas_vals = [float(m.get("roas", 0)) for m in metrics_list if float(m.get("roas", 0)) > 0]

            avg_cpa = sum(cpa_vals) / len(cpa_vals) if cpa_vals else 0
            avg_roas = sum(roas_vals) / len(roas_vals) if roas_vals else 0

            results.append({
                "creative_key": key,
                "snapshots": len(metrics_list),
                "ctr_wilson_low": round(low, 4),
                "ctr_wilson_center": round(center, 4),
                "ctr_wilson_high": round(high, 4),
                "avg_cpa": round(avg_cpa, 2),
                "avg_roas": round(avg_roas, 4),
                "insufficient_data": False,
            })

        valid = [r for r in results if not r["insufficient_data"]]
        if len(valid) < 2:
            return CreativeCompareResult(
                metrics=results,
                insufficient_data=True,
                interpretation="Not enough creatives with sufficient data to compare.",
            )

        best = max(valid, key=lambda r: r["ctr_wilson_center"])
        significant = False
        for other in valid:
            if other["creative_key"] == best["creative_key"]:
                continue
            if best["ctr_wilson_low"] > other["ctr_wilson_high"]:
                significant = True
                break

        return CreativeCompareResult(
            winner_creative_key=best["creative_key"] if significant else None,
            significant=significant,
            metrics=results,
            interpretation=(
                f"{best['creative_key']} has highest CTR ({best['ctr_wilson_center']:.4f}). "
                + ("Difference is statistically significant." if significant else "No significant difference.")
            ),
        )

    def spend_efficiency(
        self, creative_key: str, window_days: int = 30
    ) -> SpendEfficiencyResult:
        snapshots = self.db.scalars(
            select(PerformanceSnapshot)
            .where(
                PerformanceSnapshot.project_id == self.project_id,
                PerformanceSnapshot.creative_key == creative_key,
            )
            .order_by(PerformanceSnapshot.created_at.asc())
        ).all()

        if not self._check_sample_size(len(snapshots)):
            return SpendEfficiencyResult(
                total_spend=0,
                total_revenue=0,
                overall_roas=0,
                marginal_roas_trend="stable",
                insufficient_data=True,
                interpretation="Insufficient data for spend efficiency analysis.",
            )

        rows = []
        for snap in snapshots:
            m = snap.metrics or {}
            spend = float(m.get("spend", 0))
            revenue = float(m.get("revenue", 0))
            if spend > 0:
                rows.append((spend, revenue))

        if len(rows) < 5:
            return SpendEfficiencyResult(
                total_spend=sum(r[0] for r in rows),
                total_revenue=sum(r[1] for r in rows),
                overall_roas=round(sum(r[1] for r in rows) / sum(r[0] for r in rows), 4),
                marginal_roas_trend="stable",
                insufficient_data=True,
                interpretation="Need at least 5 spend data points.",
            )

        rows.sort(key=lambda r: r[0])
        total_spend = sum(r[0] for r in rows)
        total_revenue = sum(r[1] for r in rows)
        overall_roas = round(total_revenue / total_spend, 4) if total_spend > 0 else 0

        cumulative_spend = 0.0
        cumulative_revenue = 0.0
        marginal_roas_vals: list[float] = []
        for i, (spend, revenue) in enumerate(rows):
            if i >= 2:
                last_spend = cumulative_spend
                last_revenue = cumulative_revenue
                inc_spend = spend
                inc_revenue = revenue
                if inc_spend > 0:
                    marginal_roas_vals.append(inc_revenue / inc_spend)
            cumulative_spend += spend
            cumulative_revenue += revenue

        if not marginal_roas_vals:
            return SpendEfficiencyResult(
                total_spend=round(total_spend, 2),
                total_revenue=round(total_revenue, 2),
                overall_roas=overall_roas,
                marginal_roas_trend="stable",
                interpretation="Not enough data points to compute marginal ROAS.",
            )

        from scipy.stats import linregress

        x = list(range(len(marginal_roas_vals)))
        reg = linregress(x, marginal_roas_vals)
        m_slope = reg.slope
        m_p = reg.pvalue if reg.pvalue is not None else 1.0

        if m_slope < 0 and m_p < 0.05:
            trend = "declining"
        elif m_slope > 0 and m_p < 0.05:
            trend = "improving"
        else:
            trend = "stable"

        saturation_point = None
        if trend == "declining":
            sat_spend = 0.0
            for i, (spend, _revenue) in enumerate(rows):
                sat_spend += spend
                if i < len(marginal_roas_vals) and marginal_roas_vals[i] < 1.0:
                    saturation_point = round(sat_spend, 2)
                    break

        return SpendEfficiencyResult(
            total_spend=round(total_spend, 2),
            total_revenue=round(total_revenue, 2),
            overall_roas=overall_roas,
            marginal_roas_trend=trend,
            saturation_point=saturation_point,
            interpretation=(
                f"Overall ROAS: {overall_roas:.2f}. "
                f"Marginal ROAS is {trend}. "
                + (f"Saturation point at ${saturation_point:.0f} spend." if saturation_point else "")
            ),
        )

    def analyze_creative_fatigue(
        self, creative_key: str, window_days: int = 30
    ) -> CreativeFatigueResult:
        return self.creative_fatigue(creative_key, window_days)

    def compare_creatives(
        self, creative_keys: list[str], metric: str = "ctr"
    ) -> CreativeCompareResult:
        return self.compare_creatives(creative_keys, metric)

    def analyze_spend_efficiency(
        self, creative_key: str, window_days: int = 30
    ) -> SpendEfficiencyResult:
        return self.spend_efficiency(creative_key, window_days)
