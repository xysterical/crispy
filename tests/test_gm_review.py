from __future__ import annotations

from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def _advance_run(client, run_id: str) -> None:
    resp = client.post(f"/runs/{run_id}/advance", json={"notes": "approved from test"})
    assert resp.status_code == 200


def _create_run(client, *, product_code: str = "GM-REVIEW-001", variant_count: int = 2) -> dict:
    resp = client.post(
        "/runs",
        json={
            "workspace_name": "gm-review-ws",
            "project_name": "gm-review-project",
            "product_name": "smart leash",
            "product_code": product_code,
            "industry_code": "pet_care",
            "campaign_name": f"campaign-{product_code}",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "copy_image_only",
            "variant_count": variant_count,
        },
    )
    assert resp.status_code == 200
    return resp.json()


def _seed_gm_review_data(client, *, product_code: str = "GM-REVIEW-001") -> dict:
    run = _create_run(client, product_code=product_code)
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()

    feedback_resp = client.post(
        "/feedback/import",
        json={
            "workspace_name": "gm-review-ws",
            "project_name": "gm-review-project",
            "file_name": f"{product_code}.csv",
            "rows": [
                {
                    "project_name": "gm-review-project",
                    "creative_key": "V1",
                    "variant_id": "V1",
                    "run_id": run["id"],
                    "impressions": 1500,
                    "clicks": 55,
                    "spend": 45,
                    "conversions": 9,
                    "revenue": 210,
                },
                {
                    "project_name": "gm-review-project",
                    "creative_key": "V2",
                    "variant_id": "V2",
                    "run_id": run["id"],
                    "impressions": 1400,
                    "clicks": 15,
                    "spend": 45,
                    "conversions": 2,
                    "revenue": 60,
                },
            ],
        },
    )
    assert feedback_resp.status_code == 200

    policies = client.get(
        "/gm-policies",
        params={"scope": "product", "product_code": product_code},
    )
    assert policies.status_code == 200
    candidate_id = policies.json()[0]["id"]

    promote_resp = client.post(
        f"/gm-policies/{candidate_id}/promote",
        json={"changed_by": "test-suite", "notes": "activate baseline"},
    )
    assert promote_resp.status_code == 200

    review_resp = client.post(
        f"/runs/{run['id']}/variants/V2/review",
        json={
            "action": "request_regeneration",
            "comment": "product visibility weak in this angle",
            "tags": ["visual_qa_failed", "product_visibility_low"],
        },
    )
    assert review_resp.status_code == 200
    return run


def test_gm_review_summary_returns_full_payload(client):
    _seed_gm_review_data(client)

    resp = client.get(
        "/gm-review/summary",
        params={
            "workspace_name": "gm-review-ws",
            "project_name": "gm-review-project",
            "days": 7,
            "include_narrative": "false",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"]["workspace_name"] == "gm-review-ws"
    assert body["executive_summary"]["headline"]
    assert body["executive_summary"]["narrative_status"] == "disabled"
    assert body["operating_snapshot"]["run_count"] >= 1
    assert "copy_image_only" in body["operating_snapshot"]["pipeline_mode_counts"]
    assert body["learning_snapshot"]["recent_reflections"]
    assert body["policy_board"]["active_policies"]
    assert body["policy_board"]["candidate_policies"]
    assert "insufficient_data_flags" in body["business_signals"]
    assert body["action_list"]
    assert body["evidence_refs"]


def test_gm_review_markdown_export_matches_summary(client):
    _seed_gm_review_data(client, product_code="GM-REVIEW-MD")

    summary_resp = client.get(
        "/gm-review/summary",
        params={
            "workspace_name": "gm-review-ws",
            "project_name": "gm-review-project",
            "product_code": "GM-REVIEW-MD",
            "include_narrative": "false",
        },
    )
    assert summary_resp.status_code == 200
    summary = summary_resp.json()

    report_resp = client.get(
        "/gm-review/report.md",
        params={
            "workspace_name": "gm-review-ws",
            "project_name": "gm-review-project",
            "product_code": "GM-REVIEW-MD",
            "include_narrative": "false",
        },
    )
    assert report_resp.status_code == 200
    assert report_resp.headers["content-type"].startswith("text/markdown")
    report = report_resp.text
    assert summary["executive_summary"]["headline"] in report
    assert "Operating Snapshot" in report
    assert "Policy Board" in report
    assert "GM Action List" in report


def test_gm_review_summary_handles_narrative_failure(client, monkeypatch):
    from app.agents.runtime import AgentsRuntime

    _seed_gm_review_data(client, product_code="GM-REVIEW-NARR")

    def fail_chat(self, provider, model, prompt, runtime_config, **kwargs):
        raise RuntimeError("narrative unavailable")

    monkeypatch.setattr(AgentsRuntime, "_chat_complete", fail_chat)

    resp = client.get(
        "/gm-review/summary",
        params={
            "workspace_name": "gm-review-ws",
            "project_name": "gm-review-project",
            "product_code": "GM-REVIEW-NARR",
            "include_narrative": "true",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["executive_summary"]["narrative_status"] == "unavailable"
    assert body["operating_snapshot"]["run_count"] >= 1
    assert body["learning_snapshot"]["recent_reflections"]


def test_gm_review_summary_404_for_unknown_scope(client):
    resp = client.get(
        "/gm-review/summary",
        params={"workspace_name": "missing", "project_name": "missing"},
    )
    assert resp.status_code == 404


def test_gm_review_page_and_dashboard_link_load(client):
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "/dashboard/gm-review" in dashboard.text

    resp = client.get("/dashboard/gm-review")
    assert resp.status_code == 200
    html = resp.text
    assert "GM Review Console" in html
    assert "Generate Review" in html
    assert "Export Markdown" in html
