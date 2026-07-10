from pydantic import BaseModel


class ShopifyProductData(BaseModel):
    shopify_product_id: str
    title: str
    handle: str
    vendor: str
    product_type: str
    status: str
    variants: list[dict]
    images: list[dict]
    tags: list[str]


class ShopifyOrderLineItem(BaseModel):
    product_id: str | None = None
    variant_id: str | None = None
    variant_sku: str | None = None
    product_title: str
    quantity: int
    price: float
    total_discount: float


class ShopifyOrderData(BaseModel):
    shopify_order_id: str
    created_at: str
    total_price: float
    currency: str
    financial_status: str
    shipping_country: str | None = None
    line_items: list[ShopifyOrderLineItem]


class MetaCampaignData(BaseModel):
    campaign_id: str
    name: str
    objective: str
    status: str
    ad_account_id: str


class MetaInsightsRow(BaseModel):
    date_start: str
    date_stop: str
    campaign_id: str | None = None
    campaign_name: str | None = None
    ad_id: str
    ad_name: str
    creative_id: str | None = None
    impressions: int = 0
    clicks: int = 0
    spend: float = 0.0
    conversions: int = 0
    revenue: float = 0.0
    ctr: float = 0.0
    cpc: float = 0.0
    cpa: float = 0.0
    roas: float = 0.0


class SyncResult(BaseModel):
    platform: str
    sync_type: str
    status: str
    items_synced: int
    memory_entries_created: int
    error: str | None = None
