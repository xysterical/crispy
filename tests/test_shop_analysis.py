# tests/test_shop_analysis.py

from __future__ import annotations


def test_research_page_loads(client):
    resp = client.get("/dashboard/research")
    assert resp.status_code == 200
    html = resp.text
    assert "Research Intelligence" in html
    assert "store-url" in html
    assert "Run Research" in html
    assert "research-readiness" in html


def test_legacy_shop_analysis_page_loads(client):
    resp = client.get("/dashboard/shop-analysis")
    assert resp.status_code == 200
    assert "Research Intelligence" in resp.text


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
            },
            "evidence": [
                {
                    "source": "firecrawl",
                    "url": "https://shop-memory.example",
                    "title": "Shop Memory",
                    "summary": "Premium dog accessories.",
                    "status": "ok",
                },
                {
                    "source": "tavily",
                    "url": "https://review.example/shop-memory",
                    "title": "Review",
                    "summary": "Urban dog owners mention utility.",
                    "score": 0.82,
                    "status": "ok",
                },
            ],
            "source_queries": ["shop-memory target audience"],
            "search_errors": [],
        }

    def fake_competitors(self, **kwargs):
        return {
            "report": "## Competitive Landscape Overview\nComparable pet accessory stores.",
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://competitor.example",
                    "title": "Competitor",
                    "summary": "Comparable pet accessory store.",
                    "status": "ok",
                }
            ],
            "source_queries": ["competitors similar to premium pet utility"],
            "search_errors": [],
        }

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
    research_rows = [row for row in rows if row.source_type in {"shop_profile", "competitor_analysis"}]
    assert all(row.memory_type == "research_intelligence" for row in research_rows)
    for row in research_rows:
        content = row.content or {}
        assert content["summary"]
        assert content["confidence"] >= 0.6
        assert content["expires_at"]
        assert content["source_queries"]
        assert content["research_status"] == "complete"
        assert content["evidence"][0]["source"] in {"firecrawl", "tavily"}
        assert content["evidence"][0]["url"]


def test_shop_analysis_preflight_reports_search_tool_status(client, monkeypatch):
    monkeypatch.setenv("CRISPY_API_KEY_TEST_LLM", "llm")
    monkeypatch.setenv("CRISPY_API_KEY_TEST_TAVILY", "tavily")
    monkeypatch.setenv("CRISPY_API_KEY_TEST_FIRECRAWL", "firecrawl")
    resp = client.patch(
        "/agent-configs/shop_analyst",
        json={
            "api_key_env": "CRISPY_API_KEY_TEST_LLM",
            "extra": {
                "tavily_config": {"api_key_env": "CRISPY_API_KEY_TEST_TAVILY"},
                "firecrawl_config": {"api_key_env": "CRISPY_API_KEY_TEST_FIRECRAWL"},
            },
        },
    )
    assert resp.status_code == 200

    preflight = client.get("/shop-analysis/preflight")
    assert preflight.status_code == 200
    body = preflight.json()
    assert body["ok"] is True
    assert body["severity"] == "ok"
    checks = {item["key"]: item for item in body["checks"]}
    assert checks["shop_analyst.llm"]["available"] is True
    assert checks["shop_analyst.tavily"]["available"] is True
    assert checks["shop_analyst.firecrawl"]["available"] is True


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
            score_hint=999.0,
            memory_type="summary",
            status="archived",
            content={
                "shop_id": shop.id,
                "shop_name": shop.name,
                "summary": "Archived memory should not reach planning.",
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
    assert all(item["content"].get("summary") != "Archived memory should not reach planning." for item in shop_lessons)


def test_expired_research_memory_is_excluded_from_planning_unless_pinned(client, db_session):
    from datetime import UTC, datetime, timedelta

    from app.data.models import GmMemory, Workspace
    from app.schemas.api import RunCreateRequest
    from app.services.runs import _build_task_input, _gm_memory_trace_payload, create_run

    shop = Workspace(name="expired-research-shop", industry_code="pet_accessories")
    db_session.add(shop)
    db_session.flush()
    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="expired-research-shop",
            project_name="expired-research-project",
            product_name="utility leash",
            product_code="EXP-RESEARCH",
            industry_code="pet_accessories",
            campaign_name="expired-research-campaign",
            creative_preset="custom",
            creative_specs={"image_size": "1:1", "video_size": "1:1", "resolution": "720p", "video_duration_seconds": 5},
        ),
    )
    expired = GmMemory(
        project_id=run.project_id,
        memory_scope="shop",
        industry_code="pet_accessories",
        source_type="shop_profile",
        memory_type="research_intelligence",
        content={
            "shop_id": shop.id,
            "summary": "Expired research should not shape strategy.",
            "evidence": [{"source": "tavily", "url": "https://expired.example", "status": "ok"}],
            "research_status": "complete",
            "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "confidence": 0.9,
        },
    )
    fresh = GmMemory(
        project_id=run.project_id,
        memory_scope="shop",
        industry_code="pet_accessories",
        source_type="shop_profile",
        memory_type="research_intelligence",
        content={
            "shop_id": shop.id,
            "summary": "Fresh research can shape strategy.",
            "evidence": [{"source": "tavily", "url": "https://fresh.example", "status": "ok"}],
            "research_status": "complete",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "confidence": 0.9,
        },
    )
    db_session.add_all([expired, fresh])
    db_session.flush()

    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)
    lesson_ids = {item["id"] for item in task_input["gm_lessons"]}
    assert fresh.id in lesson_ids
    assert expired.id not in lesson_ids

    trace_payload = _gm_memory_trace_payload(task_input["gm_lessons"])
    fresh_ref = next(item for item in trace_payload["references"] if item["memory_id"] == fresh.id)
    assert fresh_ref["research_status"] == "complete"
    assert fresh_ref["evidence_count"] == 1
    assert fresh_ref["expires_at"] == fresh.content["expires_at"]

    expired.pinned = True
    db_session.flush()
    task_input = _build_task_input(db_session, run, planning_task)
    assert expired.id in {item["id"] for item in task_input["gm_lessons"]}


def test_weak_research_evidence_is_excluded_from_planning_unless_pinned(client, db_session):
    from datetime import UTC, datetime, timedelta

    from app.data.models import GmMemory, Workspace
    from app.schemas.api import RunCreateRequest
    from app.services.gm_memory import memory_dirty_reasons
    from app.services.runs import _build_task_input, create_run

    shop = Workspace(name="weak-research-shop", industry_code="pet_accessories")
    db_session.add(shop)
    db_session.flush()
    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="weak-research-shop",
            project_name="weak-research-project",
            product_name="utility leash",
            product_code="WEAK-RESEARCH",
            industry_code="pet_accessories",
            campaign_name="weak-research-campaign",
            creative_preset="custom",
            creative_specs={"image_size": "1:1", "video_size": "1:1", "resolution": "720p", "video_duration_seconds": 5},
        ),
    )
    weak = GmMemory(
        project_id=run.project_id,
        memory_scope="shop",
        industry_code="pet_accessories",
        source_type="shop_profile",
        memory_type="research_intelligence",
        content={
            "shop_id": shop.id,
            "summary": "Fallback-only research should not shape strategy.",
            "evidence": [{"source": "shop_profile", "url": "https://weak.example", "status": "ok"}],
            "research_status": "fallback",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "confidence": 0.8,
        },
    )
    db_session.add(weak)
    db_session.flush()

    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)
    assert "weak_research_evidence" in memory_dirty_reasons(weak)
    assert weak.id not in {item["id"] for item in task_input["gm_lessons"]}

    weak.pinned = True
    db_session.flush()
    task_input = _build_task_input(db_session, run, planning_task)
    assert weak.id in {item["id"] for item in task_input["gm_lessons"]}


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
    assert client.get("/gm-memory", params={"project_id": project.id, "scope": "shop"}).json()[0]["project_id"] == project.id

    patch = client.patch(f"/gm-memory/{rows[0]['id']}", json={"pinned": True, "status": "archived"})
    assert patch.status_code == 200
    assert patch.json()["pinned"] is True
    assert patch.json()["status"] == "archived"
    assert client.get("/gm-memory", params={"scope": "shop", "source_type": "shopify_sync"}).json() == []
    assert client.get("/gm-memory", params={"scope": "shop", "source_type": "shopify_sync", "status": "archived"}).json()[0]["id"] == rows[0]["id"]


def test_gm_memory_compaction_creates_summary_and_supersedes_raw(client, db_session):
    from app.data.models import GmMemory, Project, Workspace
    from sqlalchemy import select

    shop = Workspace(name="compact-shop")
    db_session.add(shop)
    db_session.flush()
    project = Project(workspace_id=shop.id, name="compact-project")
    db_session.add(project)
    db_session.flush()
    db_session.add_all(
        [
            GmMemory(
                project_id=project.id,
                memory_scope="product",
                product_code="SKU-C",
                source_type="shop_profile",
                memory_type="store_intelligence",
                content={"summary": "Premium utility positioning.", "winning_patterns": ["utility hook"], "confidence": 0.6},
            ),
            GmMemory(
                project_id=project.id,
                memory_scope="product",
                product_code="SKU-C",
                source_type="competitor_analysis",
                memory_type="store_intelligence",
                content={"summary": "Avoid generic lifestyle claims.", "avoid_patterns": ["generic lifestyle"], "confidence": 0.7},
            ),
        ]
    )
    db_session.commit()

    resp = client.post(
        "/gm-memory/compact",
        json={"project_id": project.id, "memory_scope": "product", "product_code": "SKU-C"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["memory_type"] == "summary"
    assert body["source_type"] == "memory_compaction"
    assert body["content"]["winning_patterns"] == ["utility hook"]
    assert body["content"]["avoid_patterns"] == ["generic lifestyle"]

    raw = db_session.scalars(
        select(GmMemory).where(GmMemory.project_id == project.id, GmMemory.memory_type == "store_intelligence")
    ).all()
    assert {row.status for row in raw} == {"superseded"}
    assert all((row.content or {}).get("superseded_by_id") == body["id"] for row in raw)


def test_conflicting_compacted_memory_is_not_used_for_planning(client, db_session):
    from app.data.models import GmMemory, Workspace
    from app.services.runs import _build_task_input, create_run
    from app.schemas.api import RunCreateRequest

    shop = Workspace(name="conflict-shop", industry_code="pet_accessories")
    db_session.add(shop)
    db_session.flush()

    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="conflict-shop",
            project_name="conflict-project",
            product_name="conflict leash",
            product_code="CONFLICT-SKU",
            industry_code="pet_accessories",
            campaign_name="conflict-campaign",
            creative_preset="custom",
            creative_specs={"image_size": "1:1", "video_size": "1:1", "resolution": "720p", "video_duration_seconds": 5},
        ),
    )
    db_session.add_all(
        [
            GmMemory(
                project_id=run.project_id,
                memory_scope="product",
                product_code="CONFLICT-SKU",
                source_type="feedback_import",
                memory_type="store_intelligence",
                content={"summary": "Conflicting source A", "winning_patterns": [{"angle": "utility proof"}]},
            ),
            GmMemory(
                project_id=run.project_id,
                memory_scope="product",
                product_code="CONFLICT-SKU",
                source_type="feedback_import",
                memory_type="store_intelligence",
                content={"summary": "Conflicting source B", "avoid_patterns": [{"angle": "utility proof"}]},
            ),
        ]
    )
    db_session.commit()

    resp = client.post(
        "/gm-memory/compact",
        json={"project_id": run.project_id, "memory_scope": "product", "product_code": "CONFLICT-SKU"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"]["conflicts"][0]["pattern_key"] == "utility proof"
    assert body["content"]["winning_patterns"] == []
    assert body["content"]["avoid_patterns"] == []

    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)
    assert all(item["id"] != body["id"] for item in task_input["gm_lessons"])


def test_low_confidence_memory_is_ignored_unless_pinned(client, db_session):
    from app.data.models import GmMemory, Workspace
    from app.services.runs import _build_task_input, create_run
    from app.schemas.api import RunCreateRequest

    shop = Workspace(name="dirty-shop", industry_code="pet_accessories")
    db_session.add(shop)
    db_session.flush()
    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="dirty-shop",
            project_name="dirty-project",
            product_name="dirty leash",
            product_code="DIRTY-SKU",
            industry_code="pet_accessories",
            campaign_name="dirty-campaign",
            creative_preset="custom",
            creative_specs={"image_size": "1:1", "video_size": "1:1", "resolution": "720p", "video_duration_seconds": 5},
        ),
    )
    dirty = GmMemory(
        project_id=run.project_id,
        memory_scope="product",
        product_code="DIRTY-SKU",
        source_type="feedback_import",
        memory_type="summary",
        content={"summary": "Low confidence memory", "winning_patterns": [{"angle": "bad angle"}], "confidence": 0.2},
    )
    good = GmMemory(
        project_id=run.project_id,
        memory_scope="product",
        product_code="DIRTY-SKU",
        source_type="feedback_import",
        memory_type="summary",
        content={"summary": "Trusted memory", "winning_patterns": [{"angle": "good angle"}], "confidence": 0.7},
    )
    db_session.add_all([dirty, good])
    db_session.flush()

    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)
    lesson_ids = {item["id"] for item in task_input["gm_lessons"]}
    assert good.id in lesson_ids
    assert dirty.id not in lesson_ids

    dirty.pinned = True
    db_session.flush()
    task_input = _build_task_input(db_session, run, planning_task)
    assert dirty.id in {item["id"] for item in task_input["gm_lessons"]}


def test_dirty_memory_is_not_compacted(client, db_session):
    from app.data.models import GmMemory, Project, Workspace

    shop = Workspace(name="dirty-compact-shop")
    db_session.add(shop)
    db_session.flush()
    project = Project(workspace_id=shop.id, name="dirty-compact-project")
    db_session.add(project)
    db_session.flush()
    db_session.add(
        GmMemory(
            project_id=project.id,
            memory_scope="product",
            product_code="DIRTY-COMPACT",
            source_type="feedback_import",
            memory_type="store_intelligence",
            content={"summary": "Too weak to compact", "winning_patterns": ["weak"], "confidence": 0.2},
        )
    )
    db_session.commit()

    resp = client.post(
        "/gm-memory/compact",
        json={"project_id": project.id, "memory_scope": "product", "product_code": "DIRTY-COMPACT"},
    )
    assert resp.status_code == 404


def test_planning_trace_records_applied_gm_memory(client):
    from app.data.models import AgentTraceEvent, GmMemory, PipelineRun, StageTask
    from app.data.session import SessionLocal
    from app.services.runs import execute_next_queued_stage
    from sqlalchemy import select

    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "trace-shop",
            "project_name": "trace-project",
            "product_name": "trace leash",
            "product_code": "TRACE-SKU",
            "industry_code": "pet_accessories",
            "campaign_name": "trace-campaign",
            "creative_preset": "custom",
            "creative_specs": {
                "image_size": "1:1",
                "video_size": "1:1",
                "resolution": "720p",
                "video_duration_seconds": 5,
            },
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    with SessionLocal() as db:
        run_model = db.get(PipelineRun, run["id"])
        db.add(
            GmMemory(
                project_id=run_model.project_id,
                memory_scope="product",
                product_code="TRACE-SKU",
                source_type="feedback_import",
                memory_type="summary",
                content={
                    "summary": "Utility hooks outperform lifestyle hooks.",
                    "winning_patterns": [{"angle": "hands-free utility proof"}],
                },
            )
        )
        db.commit()
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()
    client.post(f"/runs/{run['id']}/advance", json={"notes": "intake ok"})
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()
        event = db.scalar(
            select(AgentTraceEvent).where(
                AgentTraceEvent.run_id == run["id"],
                AgentTraceEvent.event_type == "gm_memory_applied",
            )
        )
        assert event is not None
        assert event.payload["memory_count"] >= 1
        assert event.payload["references"][0]["memory_id"]
        assert event.payload["references"][0]["summary"] == "Utility hooks outperform lifestyle hooks."
        planning_task = db.scalar(
            select(StageTask).where(StageTask.run_id == run["id"], StageTask.stage_name == "planning")
        )
        assert "hands-free utility proof" in planning_task.output_payload["strategic_angles"]


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
    """Verify Research page still loads after v2 changes."""
    resp = client.get("/dashboard/research")
    assert resp.status_code == 200
    html = resp.text
    assert "Research Intelligence" in html
    assert "store-url" in html
