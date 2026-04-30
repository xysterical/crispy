from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.base import BaseAnalyzer
from app.analytics.schemas import BundlingResult
from app.data.models import GmMemory


class OrderAnalyzer(BaseAnalyzer):
    def __init__(self, db: Session, project_id: str) -> None:
        self.db = db
        self.project_id = project_id

    def bundles(self, product_code: str, min_cooccurrence: int = 3) -> BundlingResult:
        memories = self.db.scalars(
            select(GmMemory)
            .where(
                GmMemory.project_id == self.project_id,
                GmMemory.source_type == "shopify_sync",
            )
        ).all()

        if not memories:
            return BundlingResult(
                insufficient_data=True,
                interpretation="No Shopify sync data found for bundling analysis.",
            )

        product_pairs: dict[tuple[str, str], int] = defaultdict(int)
        product_orders: dict[str, set[str]] = defaultdict(set)

        for mem in memories:
            code = mem.product_code or ""
            content = mem.content or {}
            order_id = content.get("source", "unknown")
            product_orders[code].add(order_id)

        if not self._check_sample_size(len(memories)):
            return BundlingResult(
                insufficient_data=True,
                interpretation="Insufficient order data for bundling analysis.",
            )

        bundles = []
        seen = set()
        all_codes = list(product_orders.keys())
        for i, code_a in enumerate(all_codes):
            if code_a == product_code:
                continue
            for code_b in all_codes[i + 1 :]:
                if code_b == product_code:
                    continue
                key = tuple(sorted([code_a, code_b]))
                if key in seen:
                    continue
                seen.add(key)
                orders_a = product_orders.get(code_a, set())
                orders_b = product_orders.get(code_b, set())
                if not orders_a or not orders_b:
                    continue
                intersection = len(orders_a & orders_b)
                if intersection < min_cooccurrence:
                    continue
                support_a = len(orders_a)
                support_b = len(orders_b)
                if support_a <= 0 or support_b <= 0:
                    continue
                confidence = intersection / support_a
                lift_base = support_b / max(len(memories), 1)
                lift = confidence / lift_base if lift_base > 0 else 0

                bundles.append({
                    "product_a": code_a,
                    "product_b": code_b,
                    "cooccurrence": intersection,
                    "confidence": round(confidence, 3),
                    "lift": round(lift, 2),
                })

        bundles.sort(key=lambda b: b["confidence"], reverse=True)

        return BundlingResult(
            bundles=bundles[:5],
            interpretation=(
                f"Found {len(bundles)} product pairs with >= {min_cooccurrence} co-occurrences. "
                f"Top bundle: {bundles[0]['product_a']} + {bundles[0]['product_b']}"
                if bundles
                else f"No significant bundles found for {product_code}."
            ),
        )

    def analyze_product_bundles(
        self, product_code: str, min_cooccurrence: int = 3
    ) -> BundlingResult:
        return self.bundles(product_code, min_cooccurrence)
