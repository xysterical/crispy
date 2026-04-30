from typing import Literal

from pydantic import BaseModel, Field


class SalesVelocityResult(BaseModel):
    current_daily_avg: float
    previous_daily_avg: float
    change_pct: float
    trend: Literal["rising", "stable", "declining"]
    trend_confidence: float
    insufficient_data: bool = False
    outliers_detected: list[str] = Field(default_factory=list)
    interpretation: str


class ProductContributionResult(BaseModel):
    pareto_threshold: int
    hero_products: list[str] = Field(default_factory=list)
    tail_products: list[str] = Field(default_factory=list)
    contributions: dict[str, float] = Field(default_factory=dict)
    insufficient_data: bool = False
    interpretation: str


class CreativeFatigueResult(BaseModel):
    ctr_trend: Literal["healthy", "fatigued", "insufficient_data"]
    ctr_slope: float
    ctr_slope_p_value: float
    cpc_trend: Literal["stable", "rising"]
    estimated_effective_days_remaining: int | None = None
    insufficient_data: bool = False
    outliers_detected: list[str] = Field(default_factory=list)
    interpretation: str


class CreativeCompareResult(BaseModel):
    winner_creative_key: str | None = None
    significant: bool
    metrics: list[dict] = Field(default_factory=list)
    insufficient_data: bool = False
    interpretation: str


class SpendEfficiencyResult(BaseModel):
    total_spend: float
    total_revenue: float
    overall_roas: float
    marginal_roas_trend: Literal["declining", "stable", "improving"]
    saturation_point: float | None = None
    insufficient_data: bool = False
    interpretation: str


class AdSalesLagResult(BaseModel):
    optimal_lag_days: int = 0
    cross_correlation: float = 0.0
    conversion_type: Literal["impulse", "considered", "uncertain"]
    insufficient_data: bool = False
    interpretation: str


class BundlingResult(BaseModel):
    bundles: list[dict] = Field(default_factory=list)
    insufficient_data: bool = False
    interpretation: str
