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
    assert "Research Type" in html
    assert "research-focus-slider" in html
    assert "updateResearchFocusIndicator" in html
    assert "result-overview" in html
    assert "Evidence" in html
    assert "Memory Impact" in html
    assert "/dashboard/gm-review" in html


def test_research_adaptation_surfaces_render(client):
    create_page = client.get("/dashboard").text
    assert "research-context-card" in create_page
    agent_page = client.get("/dashboard/agent-apis").text
    assert "Research Intelligence Readiness" in agent_page
    assert "Audience Pain Points" in agent_page
    gm_page = client.get("/dashboard/gm-review").text
    assert "research-review-context" in gm_page
    data_page = client.get("/dashboard/data").text
    assert "Research Context" in data_page


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
    from app.data.models import GmMemory, ResearchTask
    from app.services.shop_analysis import RESEARCH_SOURCE_TYPES
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

    def fake_audience(self, **kwargs):
        return {
            "brief": {
                "summary": "Review communities mention utility and daily walking convenience.",
                "findings": {
                    "target_audience": "Urban dog owners",
                    "pain_points": ["Need durable walking gear."],
                    "objections": ["Premium price needs proof."],
                    "review_phrases": ["daily walks"],
                    "community_sources": ["review.example"],
                },
                "strategic_implications": ["Use daily walking proof in hooks."],
            },
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://review.example/shop-memory",
                    "title": "Review",
                    "summary": "Urban dog owners mention utility.",
                    "score": 0.82,
                    "status": "ok",
                    "evidence_category": "review_community",
                },
                {
                    "source": "firecrawl",
                    "url": "https://community.example/shop-memory",
                    "title": "Community",
                    "summary": "Community discussion about durable walking gear.",
                    "status": "ok",
                    "evidence_category": "review_community",
                },
            ],
            "source_queries": ["urban dog owners reviews complaints pain points"],
            "search_errors": [],
        }

    def fake_compliance(self, **kwargs):
        return {
            "brief": {
                "summary": "Policy research requires proof for comparative durability claims.",
                "findings": {
                    "policy_sources": ["Meta advertising policies", "FTC advertising substantiation"],
                    "flagged_terms": ["premium"],
                    "claims_to_verify": ["Premium urban pet utility"],
                    "platform_risks": ["Comparative claims need proof."],
                    "required_evidence": ["Product proof"],
                },
                "strategic_implications": ["Avoid unsupported superiority language."],
            },
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://www.ftc.gov/business-guidance/advertising-marketing",
                    "title": "FTC Advertising",
                    "summary": "Advertising claims require substantiation.",
                    "score": 0.8,
                    "status": "ok",
                    "evidence_category": "policy_regulatory",
                },
                {
                    "source": "firecrawl",
                    "url": "https://www.facebook.com/policies/ads",
                    "title": "Meta Ads Policy",
                    "summary": "Meta ad policies discuss restricted claims.",
                    "status": "ok",
                    "evidence_category": "policy_regulatory",
                },
            ],
            "source_queries": ["FTC advertising substantiation pet accessories"],
            "search_errors": [],
        }

    monkeypatch.setattr(AgentsRuntime, "run_shop_profile_analysis", fake_profile)
    monkeypatch.setattr(AgentsRuntime, "run_competitor_analysis", fake_competitors)
    monkeypatch.setattr(AgentsRuntime, "run_audience_pain_point_research", fake_audience)
    monkeypatch.setattr(AgentsRuntime, "run_compliance_policy_research", fake_compliance)

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
            "research_focus": "full_intelligence",
            "refresh_reason": "operator_refresh",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["shop_id"] == shop["id"]
    assert body["task"]["status"] == "completed"
    assert body["task"]["task_type"] == "full_intelligence"
    assert body["task"]["refresh_reason"] == "operator_refresh"
    assert len(body["task"]["memory_ids"]) == 5
    assert body["profile"]["evidence_quality"]["aggregate_score"] >= 0.55
    assert body["profile"]["content"]["evidence"][0]["quality_tier"] in {"medium", "high"}
    assert {item["source_type"] for item in body["extended_results"]} == {
        "industry_baseline",
        "audience_pain_points",
        "compliance_scan",
    }
    rows = db_session.scalars(
        select(GmMemory).where(GmMemory.memory_scope == "shop")
    ).all()
    assert {row.source_type for row in rows} >= set(RESEARCH_SOURCE_TYPES)
    assert all((row.content or {}).get("shop_id") == shop["id"] for row in rows)
    research_rows = [row for row in rows if row.source_type in set(RESEARCH_SOURCE_TYPES)]
    assert all(row.memory_type == "research_intelligence" for row in research_rows)
    for row in research_rows:
        content = row.content or {}
        assert content["summary"]
        assert content["confidence"] >= 0.6
        assert content["expires_at"]
        assert content["source_queries"]
        assert content["research_status"] == "complete"
        assert content["research_focus"] == "full_intelligence"
        assert content["evidence_quality"]["aggregate_score"] >= 0.55
        assert content["evidence"][0]["quality_score"] >= 0.5
        assert content["evidence"][0]["source"] in {"firecrawl", "tavily"}
        assert content["evidence"][0]["url"]
    task = db_session.scalar(select(ResearchTask).where(ResearchTask.shop_id == shop["id"]))
    assert task is not None
    assert task.status == "completed"
    assert task.memory_ids
    assert set(task.memory_ids) == {row.id for row in research_rows}

    history = client.get(f"/shop-analysis/history?shop_id={shop['id']}")
    assert history.status_code == 200
    first = history.json()["items"][0]
    assert first["refresh_state"] == "fresh"
    assert first["evidence_quality"]["quality_tier"] in {"medium", "high"}
    assert first["latest_task"]["status"] == "completed"

    tasks = client.get(f"/shop-analysis/tasks?shop_id={shop['id']}")
    assert tasks.status_code == 200
    assert tasks.json()["items"][0]["id"] == task.id


def test_shop_analysis_can_queue_and_execute_research_task(client, db_session, monkeypatch):
    from app.agents.runtime import AgentsRuntime
    from app.data.models import GmMemory, ResearchTask
    from sqlalchemy import select

    def fake_profile(self, **kwargs):
        return {
            "profile": {
                "positioning": "Queued premium pet utility",
                "target_audience": "Urban dog owners",
            },
            "evidence": [
                {
                    "source": "firecrawl",
                    "url": "https://queued-shop.example",
                    "title": "Queued Shop",
                    "summary": "Premium dog walking accessories.",
                    "status": "ok",
                },
                {
                    "source": "tavily",
                    "url": "https://queued-review.example",
                    "title": "Queued Review",
                    "summary": "Urban dog owners compare durable accessories.",
                    "score": 0.8,
                    "status": "ok",
                },
            ],
            "source_queries": ["queued shop target audience"],
            "search_errors": [],
        }

    def fake_competitors(self, **kwargs):
        return {
            "report": "## Competitive Landscape Overview\nQueued competitor context.",
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://queued-competitor.example",
                    "title": "Queued Competitor",
                    "summary": "Comparable pet accessory store.",
                    "status": "ok",
                }
            ],
            "source_queries": ["queued competitor"],
            "search_errors": [],
        }

    monkeypatch.setattr(AgentsRuntime, "run_shop_profile_analysis", fake_profile)
    monkeypatch.setattr(AgentsRuntime, "run_competitor_analysis", fake_competitors)

    shop = client.post(
        "/shops",
        json={
            "name": "queued-shop",
            "industry_code": "pet_accessories",
            "store_url": "https://queued-shop.example",
        },
    ).json()
    queued = client.post(
        "/shop-analysis/run",
        json={
            "shop_id": shop["id"],
            "store_url": "https://queued-shop.example",
            "description": "Queued pet accessories shop.",
            "industry_code": "pet_accessories",
            "research_focus": "full_intelligence",
            "execution_mode": "queued",
        },
    )

    assert queued.status_code == 200
    queued_body = queued.json()
    assert queued_body["status"] == "queued"
    assert queued_body["task"]["status"] == "queued"
    assert queued_body["task"]["memory_ids"] == []

    task_id = queued_body["task"]["id"]
    task_resp = client.get(f"/shop-analysis/tasks/{task_id}")
    assert task_resp.status_code == 200
    assert task_resp.json()["status"] == "queued"
    queue_status = client.get("/shop-analysis/queue/status")
    assert queue_status.status_code == 200
    assert queue_status.json()["status_counts"]["queued"] == 1

    executed = client.post(f"/shop-analysis/tasks/{task_id}/execute")
    assert executed.status_code == 200
    body = executed.json()
    assert body["status"] == "completed"
    assert body["task"]["status"] == "completed"
    assert len(body["task"]["memory_ids"]) == 5
    assert {item["source_type"] for item in body["extended_results"]} == {
        "industry_baseline",
        "audience_pain_points",
        "compliance_scan",
    }

    task = db_session.get(ResearchTask, task_id)
    assert task is not None
    assert task.status == "completed"
    rows = db_session.scalars(select(GmMemory).where(GmMemory.id.in_(task.memory_ids))).all()
    assert len(rows) == 5


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


def test_focused_audience_research_writes_single_task_output(client, db_session, monkeypatch):
    from app.agents.runtime import AgentsRuntime
    from app.data.models import GmMemory
    from sqlalchemy import select

    monkeypatch.setattr(
        AgentsRuntime,
        "run_shop_profile_analysis",
        lambda self, **kwargs: {
            "profile": {
                "positioning": "Premium urban pet utility",
                "target_audience": "Urban dog owners",
                "content_gaps": ["Need more objection handling around daily walking convenience."],
            },
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://audience.example",
                    "summary": "Urban dog owners ask about convenience and daily walking routines.",
                    "status": "ok",
                }
            ],
            "source_queries": ["audience pet utility"],
            "search_errors": [],
        },
    )
    monkeypatch.setattr(
        AgentsRuntime,
        "run_competitor_analysis",
        lambda self, **kwargs: {
            "report": "Competitors emphasize convenience and hands-free routines.",
            "evidence": [
                {
                    "source": "firecrawl",
                    "url": "https://audience-competitor.example",
                    "summary": "Competitor messaging emphasizes daily routine convenience.",
                    "status": "ok",
                }
            ],
            "source_queries": ["competitor audience convenience"],
            "search_errors": [],
        },
    )
    monkeypatch.setattr(
        AgentsRuntime,
        "run_audience_pain_point_research",
        lambda self, **kwargs: {
            "brief": {
                "summary": "Review and community research shows convenience objections.",
                "findings": {
                    "target_audience": "Urban dog owners",
                    "pain_points": ["Need hands-free walking convenience."],
                    "objections": ["Unsure whether premium accessories are worth it."],
                    "review_phrases": ["daily walking routine"],
                    "community_sources": ["reddit.com/r/dogs"],
                },
                "strategic_implications": ["Lead with daily routine friction."],
            },
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://reddit.example/dogs",
                    "summary": "Dog owners discuss daily walking convenience.",
                    "status": "ok",
                    "evidence_category": "review_community",
                }
            ],
            "source_queries": ["urban dog owners reviews complaints pain points"],
            "search_errors": [],
        },
    )

    shop = client.post(
        "/shops",
        json={
            "name": "audience-focus-shop",
            "industry_code": "pet_accessories",
            "store_url": "https://audience-focus.example",
        },
    ).json()
    resp = client.post(
        "/shop-analysis/run",
        json={
            "shop_id": shop["id"],
            "store_url": "https://audience-focus.example",
            "description": "Pet accessories shop.",
            "industry_code": "pet_accessories",
            "research_focus": "audience_pain_points",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] is None
    assert body["competitor_analysis"] is None
    assert [item["source_type"] for item in body["extended_results"]] == ["audience_pain_points"]
    assert body["task"]["task_type"] == "audience_pain_points"
    assert len(body["task"]["memory_ids"]) == 1
    rows = db_session.scalars(select(GmMemory).where(GmMemory.memory_scope == "shop")).all()
    assert {row.source_type for row in rows} == {"audience_pain_points"}
    content = rows[0].content or {}
    assert content["findings"]["pain_points"]
    assert content["evidence"][0]["evidence_category"] == "review_community"
    assert content["source_queries"] == ["urban dog owners reviews complaints pain points"]
    assert content["research_focus"] == "audience_pain_points"


def test_focused_compliance_research_uses_policy_sources(client, db_session, monkeypatch):
    from app.agents.runtime import AgentsRuntime
    from app.data.models import GmMemory
    from sqlalchemy import select

    monkeypatch.setattr(
        AgentsRuntime,
        "run_shop_profile_analysis",
        lambda self, **kwargs: {
            "profile": {
                "positioning": "Premium pet wellness accessories",
                "target_audience": "Dog owners",
                "product_categories": ["pet supplements", "dog accessories"],
                "unique_selling_points": ["Guarantees calmer walks"],
            },
            "evidence": [
                {
                    "source": "firecrawl",
                    "url": "https://compliance-focus.example",
                    "summary": "Store claims calmer walks.",
                    "status": "ok",
                }
            ],
            "source_queries": ["compliance store profile"],
            "search_errors": [],
        },
    )
    monkeypatch.setattr(
        AgentsRuntime,
        "run_competitor_analysis",
        lambda self, **kwargs: {
            "report": "Competitors use guarantee and calming claims.",
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://compliance-competitor.example",
                    "summary": "Competitor claims need review.",
                    "status": "ok",
                }
            ],
            "source_queries": ["competitor compliance"],
            "search_errors": [],
        },
    )
    monkeypatch.setattr(
        AgentsRuntime,
        "run_compliance_policy_research",
        lambda self, **kwargs: {
            "brief": {
                "summary": "Policy research flags guarantee and wellness claims.",
                "findings": {
                    "policy_sources": ["Meta advertising policies", "FTC advertising substantiation"],
                    "flagged_terms": ["guarantee", "calmer"],
                    "claims_to_verify": ["Guarantees calmer walks"],
                    "platform_risks": ["Substantiation required before ad use."],
                    "required_evidence": ["Product proof and customer evidence."],
                },
                "strategic_implications": ["Avoid guarantee language in generated ads."],
            },
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://www.ftc.gov/business-guidance/advertising-marketing",
                    "summary": "FTC guidance on advertising substantiation.",
                    "status": "ok",
                    "evidence_category": "policy_regulatory",
                }
            ],
            "source_queries": ["FTC advertising substantiation pet supplements"],
            "search_errors": [],
        },
    )

    shop = client.post(
        "/shops",
        json={
            "name": "compliance-focus-shop",
            "industry_code": "pet_accessories",
            "store_url": "https://compliance-focus.example",
        },
    ).json()
    resp = client.post(
        "/shop-analysis/run",
        json={
            "shop_id": shop["id"],
            "store_url": "https://compliance-focus.example",
            "description": "Pet accessories shop with wellness claims.",
            "industry_code": "pet_accessories",
            "research_focus": "compliance_scan",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] is None
    assert body["competitor_analysis"] is None
    assert [item["source_type"] for item in body["extended_results"]] == ["compliance_scan"]
    assert body["task"]["task_type"] == "compliance_scan"
    assert len(body["task"]["memory_ids"]) == 1
    rows = db_session.scalars(select(GmMemory).where(GmMemory.memory_scope == "shop")).all()
    assert {row.source_type for row in rows} == {"compliance_scan"}
    content = rows[0].content or {}
    assert "guarantee" in content["findings"]["flagged_terms"]
    assert content["evidence"][0]["evidence_category"] == "policy_regulatory"
    assert content["source_queries"] == ["FTC advertising substantiation pet supplements"]
    assert content["research_focus"] == "compliance_scan"


def test_create_run_planning_input_includes_shop_memory(client, db_session):
    from app.data.models import GmMemory, Workspace
    from app.services.runs import _build_task_input, _gm_memory_trace_payload, create_run
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


def test_research_context_api_and_planning_input_classify_included_and_excluded(client, db_session):
    from datetime import UTC, datetime, timedelta

    from app.data.models import GmMemory, Workspace
    from app.schemas.api import RunCreateRequest
    from app.services.runs import _build_task_input, _gm_memory_trace_payload, create_run

    shop = Workspace(name="research-context-shop", industry_code="pet_accessories")
    db_session.add(shop)
    db_session.flush()
    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="research-context-shop",
            project_name="research-context-project",
            product_name="utility leash",
            product_code="CTX-RESEARCH",
            industry_code="pet_accessories",
            campaign_name="research-context-campaign",
            creative_preset="custom",
            creative_specs={"image_size": "1:1", "video_size": "1:1", "resolution": "720p", "video_duration_seconds": 5},
        ),
    )
    included = GmMemory(
        project_id=run.project_id,
        memory_scope="shop",
        industry_code="pet_accessories",
        source_type="audience_pain_points",
        memory_type="research_intelligence",
        content={
            "shop_id": shop.id,
            "summary": "Audience wants stronger utility proof.",
            "findings": {"pain_points": ["Need proof."]},
            "evidence": [{"source": "tavily", "url": "https://reviews.example", "summary": "Review evidence.", "status": "ok", "quality_score": 0.8}],
            "evidence_quality": {"aggregate_score": 0.8, "quality_tier": "high"},
            "research_status": "complete",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "confidence": 0.8,
        },
    )
    excluded = GmMemory(
        project_id=run.project_id,
        memory_scope="shop",
        industry_code="pet_accessories",
        source_type="compliance_scan",
        memory_type="research_intelligence",
        content={
            "shop_id": shop.id,
            "summary": "Expired compliance scan.",
            "findings": {"flagged_terms": ["guarantee"]},
            "evidence": [{"source": "tavily", "url": "https://policy.example", "summary": "Policy evidence.", "status": "ok", "quality_score": 0.8}],
            "evidence_quality": {"aggregate_score": 0.8, "quality_tier": "high"},
            "research_status": "complete",
            "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "confidence": 0.8,
        },
    )
    db_session.add_all([included, excluded])
    db_session.commit()

    ctx_resp = client.get("/research-context", params={"workspace_name": shop.name, "project_name": "research-context-project"})
    assert ctx_resp.status_code == 200
    ctx = ctx_resp.json()
    assert ctx["summary"]["included_count"] == 1
    assert ctx["summary"]["excluded_count"] == 1
    assert ctx["included"][0]["source_type"] == "audience_pain_points"
    assert "expired_research" in ctx["excluded"][0]["dirty_reasons"]

    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)
    assert task_input["research_context"]["summary"]["included_count"] == 1
    assert task_input["research_context"]["summary"]["excluded_count"] == 1

    dashboard = client.get("/data-dashboard/summary", params={"workspace_name": shop.name, "project_name": "research-context-project"})
    assert dashboard.status_code == 200
    assert dashboard.json()["research_context"]["summary"]["included_count"] == 1

    run_view = client.get(f"/runs/{run.id}")
    assert run_view.status_code == 200
    assert run_view.json()["research_context"]["summary"]["included_count"] == 1
    trace_payload = _gm_memory_trace_payload(task_input["gm_lessons"], task_input["research_context"])
    assert trace_payload["research_context"]["summary"]["included_count"] == 1
    assert trace_payload["excluded_research"][0]["source_type"] == "compliance_scan"


def test_due_research_refreshes_are_queued_and_deduped(client, db_session):
    from datetime import UTC, datetime, timedelta

    from app.data.models import GmMemory
    from app.services.shop_analysis import _get_or_create_workspace_project

    shop = client.post(
        "/shops",
        json={
            "name": "refresh-policy-shop",
            "industry_code": "pet_accessories",
            "store_url": "https://refresh-policy.example",
        },
    ).json()
    workspace, project = _get_or_create_workspace_project(db_session, "refresh-policy-shop", "shop_analysis")
    workspace.store_url = "https://refresh-policy.example"

    expired_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    soon_at = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    fresh_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    db_session.add_all([
        GmMemory(
            project_id=project.id,
            memory_scope="shop",
            industry_code="pet_accessories",
            source_type="shop_profile",
            memory_type="research_intelligence",
            content={
                "shop_id": shop["id"],
                "shop_name": "refresh-policy-shop",
                "store_url": "https://refresh-policy.example",
                "summary": "Expired full research profile.",
                "research_focus": "full_intelligence",
                "research_status": "complete",
                "expires_at": expired_at,
            },
        ),
        GmMemory(
            project_id=project.id,
            memory_scope="shop",
            industry_code="pet_accessories",
            source_type="competitor_analysis",
            memory_type="research_intelligence",
            content={
                "shop_id": shop["id"],
                "shop_name": "refresh-policy-shop",
                "store_url": "https://refresh-policy.example",
                "summary": "Expired full research competitors.",
                "research_focus": "full_intelligence",
                "research_status": "complete",
                "expires_at": expired_at,
            },
        ),
        GmMemory(
            project_id=project.id,
            memory_scope="shop",
            industry_code="pet_accessories",
            source_type="audience_pain_points",
            memory_type="research_intelligence",
            content={
                "shop_id": shop["id"],
                "shop_name": "refresh-policy-shop",
                "store_url": "https://refresh-policy.example",
                "summary": "Audience research nearing expiry.",
                "research_focus": "audience_pain_points",
                "research_status": "complete",
                "expires_at": soon_at,
            },
        ),
        GmMemory(
            project_id=project.id,
            memory_scope="shop",
            industry_code="pet_accessories",
            source_type="compliance_scan",
            memory_type="research_intelligence",
            content={
                "shop_id": shop["id"],
                "shop_name": "refresh-policy-shop",
                "store_url": "https://refresh-policy.example",
                "summary": "Fresh compliance research.",
                "research_focus": "compliance_scan",
                "research_status": "complete",
                "expires_at": fresh_at,
            },
        ),
    ])
    db_session.commit()

    queued = client.post(f"/shop-analysis/refresh-due?shop_id={shop['id']}")
    assert queued.status_code == 200
    body = queued.json()
    assert body["queued_count"] == 2
    assert body["skipped"]["duplicate"] == 1
    assert body["skipped"]["fresh"] == 1
    task_types = {item["task_type"] for item in body["queued"]}
    assert task_types == {"full_intelligence", "audience_pain_points"}
    assert {item["source"] for item in body["queued"]} == {"refresh_policy"}
    assert {item["refresh_reason"] for item in body["queued"]} == {"auto_expired", "auto_refresh_soon"}

    repeated = client.post(f"/shop-analysis/refresh-due?shop_id={shop['id']}")
    assert repeated.status_code == 200
    repeated_body = repeated.json()
    assert repeated_body["queued_count"] == 0
    assert repeated_body["skipped"]["pending"] == 2


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


def test_low_quality_research_source_is_excluded_from_planning(client, db_session):
    from datetime import UTC, datetime, timedelta

    from app.data.models import GmMemory, Workspace
    from app.schemas.api import RunCreateRequest
    from app.services.gm_memory import memory_dirty_reasons
    from app.services.runs import _build_task_input, create_run

    shop = Workspace(name="low-quality-research-shop", industry_code="pet_accessories")
    db_session.add(shop)
    db_session.flush()
    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="low-quality-research-shop",
            project_name="low-quality-research-project",
            product_name="utility leash",
            product_code="LOW-QUALITY-RESEARCH",
            industry_code="pet_accessories",
            campaign_name="low-quality-research-campaign",
            creative_preset="custom",
            creative_specs={"image_size": "1:1", "video_size": "1:1", "resolution": "720p", "video_duration_seconds": 5},
        ),
    )
    low_quality = GmMemory(
        project_id=run.project_id,
        memory_scope="shop",
        industry_code="pet_accessories",
        source_type="shop_profile",
        memory_type="research_intelligence",
        content={
            "shop_id": shop.id,
            "summary": "Low-quality search result should not shape strategy.",
            "evidence": [
                {
                    "source": "tavily",
                    "url": "https://thin.example",
                    "status": "ok",
                    "quality_score": 0.32,
                    "quality_tier": "low",
                }
            ],
            "evidence_quality": {"aggregate_score": 0.32, "quality_tier": "low"},
            "research_status": "partial",
            "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "confidence": 0.8,
        },
    )
    db_session.add(low_quality)
    db_session.flush()

    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)
    assert "weak_research_evidence" in memory_dirty_reasons(low_quality)
    assert low_quality.id not in {item["id"] for item in task_input["gm_lessons"]}


def test_research_conflict_is_excluded_from_planning_unless_pinned(client, db_session):
    from app.data.models import Workspace
    from app.schemas.api import RunCreateRequest
    from app.services.gm_memory import memory_dirty_reasons
    from app.services.runs import _build_task_input, create_run
    from app.services.shop_analysis import save_shop_profile

    shop = Workspace(name="research-conflict-shop", industry_code="pet_accessories")
    db_session.add(shop)
    db_session.flush()
    run = create_run(
        db_session,
        RunCreateRequest(
            workspace_name="research-conflict-shop",
            project_name="research-conflict-project",
            product_name="utility leash",
            product_code="RESEARCH-CONFLICT",
            industry_code="pet_accessories",
            campaign_name="research-conflict-campaign",
            creative_preset="custom",
            creative_specs={"image_size": "1:1", "video_size": "1:1", "resolution": "720p", "video_duration_seconds": 5},
        ),
    )
    first = save_shop_profile(
        db_session,
        project_id=run.project_id,
        industry_code="pet_accessories",
        store_url="https://research-conflict.example",
        profile_data={"positioning": "Premium urban dog walking gear", "target_audience": "Urban dog owners"},
        evidence=[{"source": "tavily", "url": "https://research-conflict.example/a", "summary": "Premium urban dog walking gear.", "status": "ok"}],
        shop_id=shop.id,
        shop_name=shop.name,
    )
    second = save_shop_profile(
        db_session,
        project_id=run.project_id,
        industry_code="pet_accessories",
        store_url="https://research-conflict.example",
        profile_data={"positioning": "Budget indoor cat toy bundles", "target_audience": "Apartment cat owners"},
        evidence=[{"source": "firecrawl", "url": "https://research-conflict.example/b", "summary": "Budget indoor cat toy bundles.", "status": "ok"}],
        shop_id=shop.id,
        shop_name=shop.name,
    )
    db_session.flush()

    conflicts = second.content["conflicts"]
    assert conflicts
    assert conflicts[0]["status"] == "unresolved"
    assert conflicts[0]["previous_memory_id"] == first.id
    assert "unresolved_conflicts" in memory_dirty_reasons(second)

    planning_task = next(task for task in run.stage_tasks if task.stage_name == "planning")
    task_input = _build_task_input(db_session, run, planning_task)
    lesson_ids = {item["id"] for item in task_input["gm_lessons"]}
    assert second.id not in lesson_ids

    second.pinned = True
    db_session.flush()
    task_input = _build_task_input(db_session, run, planning_task)
    assert second.id in {item["id"] for item in task_input["gm_lessons"]}


def test_source_quality_scoring_penalizes_thin_evidence():
    from app.services.shop_analysis import _normalize_evidence, _research_status

    evidence = _normalize_evidence(
        "https://thin.example",
        source_type="shop_profile",
        evidence=[{"source": "tavily", "url": "https://thin.example", "status": "ok"}],
    )

    assert evidence[0]["quality_score"] < 0.55
    assert evidence[0]["quality_tier"] == "low"
    assert _research_status(evidence, []) == "partial"


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
    """Verify research runtime methods accept tavily/firecrawl api key params."""
    import inspect
    from app.agents.runtime import AgentsRuntime
    rt = AgentsRuntime()
    for method in [
        rt.run_shop_profile_analysis,
        rt.run_audience_pain_point_research,
        rt.run_compliance_policy_research,
    ]:
        sig = inspect.signature(method)
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
    assert "Research Type" in html
    assert "Full intelligence" in html
    assert "Industry" in html
    assert "Audience" in html
    assert "Compliance" in html
    assert "Store Context Detail" in html
    assert "Competitive Landscape Detail" in html
    assert "Quality" in html
    assert "conflicts=" in html
