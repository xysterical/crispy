from __future__ import annotations

import httpx

from app.integrations.base import BaseIntegrationProvider
from app.integrations.models import ShopifyOrderData, ShopifyOrderLineItem, ShopifyProductData


class ShopifyProvider(BaseIntegrationProvider):
    def __init__(self, config: dict) -> None:
        super().__init__(config)
        domain = str(config.get("store_domain", "")).strip()
        if domain.startswith("http"):
            domain = domain.split("//")[-1]
        if not domain.endswith(".myshopify.com"):
            domain = f"{domain}.myshopify.com"
        self.store_domain = domain
        self.access_token = str(config.get("access_token", ""))
        self.api_version = "2024-10"
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return f"https://{self.store_domain}/admin/api/{self.api_version}"

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "X-Shopify-Access-Token": self.access_token,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def test_connection(self) -> bool:
        try:
            response = await self.client.get("/shop.json")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def fetch_products(self, limit: int = 250) -> list[ShopifyProductData]:
        all_products: list[ShopifyProductData] = []
        url = f"/products.json?limit={min(limit, 250)}"
        while url:
            response = await self.client.get(url)
            if response.status_code == 401:
                raise PermissionError("Shopify access token is invalid or expired")
            if response.status_code == 404:
                raise ValueError(f"Shopify store not found: {self.store_domain}")
            response.raise_for_status()
            data = response.json()
            for product in data.get("products", []):
                all_products.append(ShopifyProductData(
                    shopify_product_id=str(product["id"]),
                    title=product.get("title", ""),
                    handle=product.get("handle", ""),
                    vendor=product.get("vendor", ""),
                    product_type=product.get("product_type", ""),
                    status=product.get("status", "active"),
                    variants=[
                        {
                            "variant_id": str(v["id"]),
                            "sku": v.get("sku", ""),
                            "title": v.get("title", ""),
                            "price": float(v.get("price", 0)),
                            "compare_at_price": float(v.get("compare_at_price") or 0),
                            "inventory_quantity": int(v.get("inventory_quantity", 0)),
                        }
                        for v in product.get("variants", [])
                    ],
                    images=[
                        {
                            "image_id": str(img["id"]),
                            "src": img.get("src", ""),
                            "alt": img.get("alt", ""),
                            "width": img.get("width"),
                            "height": img.get("height"),
                            "position": img.get("position", 1),
                        }
                        for img in product.get("images", [])
                    ],
                    tags=[t.strip() for t in product.get("tags", "").split(",") if t.strip()],
                ))
            link_header = response.headers.get("Link", "")
            url = ""
            if 'rel="next"' in link_header:
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        start = part.find("<") + 1
                        end = part.find(">")
                        url = part[start:end]
                        if url.startswith(self.base_url):
                            url = url[len(self.base_url):]
                        break
        return all_products

    async def fetch_orders(self, limit: int = 250, status: str = "any") -> list[ShopifyOrderData]:
        all_orders: list[ShopifyOrderData] = []
        url = f"/orders.json?status={status}&limit={min(limit, 250)}"
        while url:
            response = await self.client.get(url)
            if response.status_code == 401:
                raise PermissionError("Shopify access token is invalid or expired")
            response.raise_for_status()
            data = response.json()
            for order in data.get("orders", []):
                billing = order.get("billing_address") or {}
                shipping = order.get("shipping_address") or billing or {}
                all_orders.append(ShopifyOrderData(
                    shopify_order_id=str(order["id"]),
                    created_at=order.get("created_at", ""),
                    total_price=float(order.get("total_price", 0)),
                    currency=order.get("currency", "USD"),
                    financial_status=order.get("financial_status", ""),
                    shipping_country=shipping.get("country"),
                    line_items=[
                        ShopifyOrderLineItem(
                            product_id=str(item.get("product_id")) if item.get("product_id") else None,
                            variant_id=str(item.get("variant_id")) if item.get("variant_id") else None,
                            variant_sku=item.get("sku"),
                            product_title=item.get("name") or item.get("title", ""),
                            quantity=int(item.get("quantity", 0)),
                            price=float(item.get("price", 0)),
                            total_discount=float(item.get("total_discount", 0)),
                        )
                        for item in order.get("line_items", [])
                    ],
                ))
            link_header = response.headers.get("Link", "")
            url = ""
            if 'rel="next"' in link_header:
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        start = part.find("<") + 1
                        end = part.find(">")
                        url = part[start:end]
                        if url.startswith(self.base_url):
                            url = url[len(self.base_url):]
                        break
        return all_orders
