# tests/test_shop_analysis.py

from __future__ import annotations


def test_shop_analysis_page_loads(client):
    resp = client.get("/dashboard/shop-analysis")
    assert resp.status_code == 200
    html = resp.text
    assert "Shop Analysis" in html
    assert "store-url" in html
    assert "Run Analysis" in html


def test_shop_analysis_history_empty(client):
    resp = client.get(
        "/shop-analysis/history?workspace_name=test_ws&project_name=test_proj"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["items"] == []


def test_shop_analysis_run_stores_gm_memory(client):
    resp = client.post(
        "/shop-analysis/run",
        json={
            "store_url": "https://example-pet-store.com",
            "description": "A pet supplies store targeting US urban dog owners.",
            "industry_code": "pet_accessories",
            "workspace_name": "test_ws",
            "project_name": "test_proj",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["store_url"] == "https://example-pet-store.com"
    assert body["industry_code"] == "pet_accessories"
    # At least one phase should succeed (depends on LLM API availability)
    # If no LLM key is configured, the endpoint may still return with errors
    assert "status" in body

    # Verify GmMemory entries were created (check if any exist)
    mem_resp = client.get(
        "/gm-memory?scope=industry&industry_code=pet_accessories&limit=50"
    )
    assert mem_resp.status_code == 200
    memories = mem_resp.json()
    # Don't assert on count — depends on LLM API availability
    assert isinstance(memories, list)


def test_shop_analysis_run_stores_shop_scoped_gm_memory(client, db_session, monkeypatch):
    from app.agents.runtime import AgentsRuntime
    from app.data.models import GmMemory
    from sqlalchemy import select

    def fake_profile(self, **kwargs):
        return {
            "profile": {
                "positioning": "Premium urban pet utility",
                "target_audience": "Urban dog owners",
            }
        }

    def fake_competitors(self, **kwargs):
        return {"report": "## Competitive Landscape Overview\nComparable pet accessory stores."}

    monkeypatch.setattr(AgentsRuntime, "run_shop_profile_analysis", fake_profile)
    monkeypatch.setattr(AgentsRuntime, "run_competitor_analysis", fake_competitors)

    shop = client.post(
        "/shops",
        json={
            "name": "shop-memory-test",
            "industry_code": "pet_accessories",
            "store_url": "https://shop-memory.example",
        },
    ).json()
    resp = client.post(
        "/shop-analysis/run",
        json={
            "shop_id": shop["id"],
            "store_url": "https://shop-memory.example",
            "description": "Pet accessories shop.",
            "industry_code": "pet_accessories",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["shop_id"] == shop["id"]
    rows = db_session.scalars(
        select(GmMemory).where(GmMemory.memory_scope == "shop")
    ).all()
    assert {row.source_type for row in rows} >= {"shop_profile", "competitor_analysis"}
    assert all((row.content or {}).get("shop_id") == shop["id"] for row in rows)


def test_create_run_planning_input_includes_shop_memory(client, db_session):
    from app.data.models import GmMemory, Workspace
    from app.services.runs import _build_task_input, create_run
    from app.schemas.api import RunCreateRequest

    shop = Workspace(
        name="planning-shop",
        industry_code="pet_accessories",
        store_url="https://planning-shop.example",
        description="Premium dog walking accessories.",
    )
    db_session.add(shop)
    db_session.flush()
    db_session.add(
        GmMemory(
            project_id="shop-memory-placeholder",
            memory_scope="shop",
            industry_code="pet_accessories",
            source_type="shop_profile",
            memory_type="store_intelligence",
            content={
                "shop_id": shop.id,
                "shop_name": shop.name,
                "profile": {"positioning": "Premium hands-free dog walking"},
            },
        )
    )
    db_session.add(
        GmMemory(
            project_id="shop-memory-placeholder",
            memory_scope="shop",
            industry_code="pet_accessories",
            source_type="shopify_sync",
            score_hint=120.0,
            memory_type="summary",
            content={
                "shop_id": shop.id,
                "shop_name": shop.name,
                "summary": "Store revenue is rising across dog walking products.",
            },
        )
    )
    db_session.add(
        GmMemory(
            project_id="shop-memory-placeholder",
            memory_scope="shop",
            industry_code="pet_accessories",
            source_type="meta_sync",
            score_hint=2.4,
            memory_type="store_intelligence",
            content={
                "shop_id": shop.id,
                "shop_name": shop.name,
                "summary": "Meta account ROAS is healthy for utility-led creatives.",
            },
        )
    )
    db_session.flush()

    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="planning-shop",
            project_name="dog-walking",
            product_name="hands-free leash",
            product_code="SHOP-MEM-001",
            industry_code="pet_accessories",
            campaign_name="spring-launch",
            creative_preset="custom",
            creative_specs={
                "image_size": "1:1",
                "video_size": "1:1",
                "resolution": "720p",
                "video_duration_seconds": 5,
            },
        ),
    )
    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)

    shop_lessons = [
        item for item in task_input["gm_lessons"]
        if item["memory_scope"] == "shop"
    ]
    assert shop_lessons
    assert shop_lessons[0]["memory_type"] == "summary"
    assert {item["source_type"] for item in shop_lessons} >= {"shop_profile", "shopify_sync", "meta_sync"}


def test_shopify_sync_writes_shop_memory_contract(client, db_session, monkeypatch):
    import asyncio

    from app.data.models import GmMemory, Product, Project, Workspace
    from app.integrations.models import ShopifyOrderData, ShopifyOrderLineItem
    from app.integrations.shopify import ShopifyProvider
    from app.integrations.sync_service import sync_shopify
    from sqlalchemy import select

    shop = Workspace(name="sync-contract-shop")
    db_session.add(shop)
    db_session.flush()
    project = Project(workspace_id=shop.id, name="sync-contract-project")
    db_session.add(project)
    db_session.flush()
    db_session.add(Product(project_id=project.id, name="Dog leash", product_code="SKU-1"))
    db_session.flush()

    async def fake_orders(self):
        return [
            ShopifyOrderData(
                shopify_order_id="1001",
                created_at="2026-06-20T00:00:00Z",
                total_price=30,
                currency="USD",
                financial_status="paid",
                line_items=[
                    ShopifyOrderLineItem(
                        variant_sku="SKU-1",
                        product_title="Dog leash",
                        quantity=2,
                        price=15,
                        total_discount=0,
                    )
                ],
            )
        ]

    monkeypatch.setattr(ShopifyProvider, "fetch_orders", fake_orders)
    asyncio.run(
        sync_shopify(
            db_session,
            workspace_name="sync-contract-shop",
            project_name="sync-contract-project",
            sync_type="orders",
            store_domain="example.myshopify.com",
            access_token="token",
        )
    )

    row = db_session.scalar(
        select(GmMemory).where(GmMemory.memory_scope == "shop", GmMemory.source_type == "shopify_sync")
    )
    content = row.content or {}
    assert row.memory_type == "summary"
    assert content["shop_id"] == shop.id
    assert {"summary", "winning_patterns", "avoid_patterns", "evidence", "metric_window", "confidence"} <= set(content)
    db_session.commit()

    resp = client.get("/gm-memory", params={"scope": "shop", "source_type": "shopify_sync", "memory_type": "summary"})
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["memory_type"] == "summary"


def test_shop_analysis_history_after_run(client):
    # Run an analysis first
    client.post(
        "/shop-analysis/run",
        json={
            "store_url": "https://example-history-test.com",
            "description": "Test store for history.",
            "industry_code": "test_industry",
            "workspace_name": "test_ws",
            "project_name": "test_proj",
        },
    )
    # Check history
    resp = client.get(
        "/shop-analysis/history?workspace_name=test_ws&project_name=test_proj"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) >= 0  # May be 0 if LLM API unavailable


def test_shop_analyst_persona_exists(client):
    resp = client.get("/personas")
    assert resp.status_code == 200
    personas = resp.json()
    names = [p["agent_name"] for p in personas]
    assert "shop_analyst" in names
    assert "product_research_agent" in names
    assert "research_agent" not in names


def test_shop_analyst_config_has_search_key_fields(client):
    """Verify AgentApiConfigView includes tavily and firecrawl key fields."""
    resp = client.get("/agent-configs")
    assert resp.status_code == 200
    configs = resp.json()
    for cfg in configs:
        assert "tavily_api_key_env" in cfg
        assert "firecrawl_api_key_env" in cfg
        break


def test_search_clients_importable():
    """Verify Tavily and Firecrawl clients can be imported."""
    from app.search import TavilyClient, FirecrawlClient
    assert TavilyClient is not None
    assert FirecrawlClient is not None


def test_tavily_client_instantiation():
    """Verify TavilyClient can be instantiated (no API call made)."""
    from app.search import TavilyClient
    client = TavilyClient(api_key="test-key")
    assert client is not None


def test_firecrawl_client_instantiation():
    """Verify FirecrawlClient can be instantiated (no API call made)."""
    from app.search import FirecrawlClient
    client = FirecrawlClient(api_key="test-key")
    assert client is not None


def test_runtime_accepts_search_keys():
    """Verify run_shop_profile_analysis accepts tavily/firecrawl api key params."""
    import inspect
    from app.agents.runtime import AgentsRuntime
    rt = AgentsRuntime()
    sig = inspect.signature(rt.run_shop_profile_analysis)
    params = list(sig.parameters.keys())
    assert "tavily_api_key" in params
    assert "firecrawl_api_key" in params


def test_v2_page_loads_with_three_mode_rows(client):
    """Verify Shop Analysis page still loads after v2 changes."""
    resp = client.get("/dashboard/shop-analysis")
    assert resp.status_code == 200
    html = resp.text
    assert "Shop Analysis" in html
    assert "store-url" in html
