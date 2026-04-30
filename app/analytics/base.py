from math import sqrt


class BaseAnalyzer:
    min_sample_size: int = 5
    confidence_level: float = 0.95

    def _check_sample_size(self, n: int) -> bool:
        return n >= self.min_sample_size

    def _wilson_ci(self, successes: int, trials: int) -> tuple[float, float, float]:
        if trials <= 0:
            return 0.0, 0.0, 0.0
        from scipy.stats import norm as _norm

        p_hat = successes / trials
        z = _norm.ppf(1 - (1 - self.confidence_level) / 2)
        denominator = 1 + z * z / trials
        center = (p_hat + z * z / (2 * trials)) / denominator
        margin = z * sqrt((p_hat * (1 - p_hat) + z * z / (4 * trials)) / trials) / denominator
        return max(0.0, center - margin), center, min(1.0, center + margin)

    def _iqr_outliers(self, series: list[float]) -> list[int]:
        if len(series) < 4:
            return []
        sorted_vals = sorted(series)
        n = len(sorted_vals)
        q1_idx = max(0, n // 4)
        q3_idx = min(n - 1, 3 * n // 4)
        q1 = sorted_vals[q1_idx]
        q3 = sorted_vals[q3_idx]
        iqr = q3 - q1
        if iqr <= 0:
            return []
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        return [i for i, v in enumerate(series) if v < lower or v > upper]
