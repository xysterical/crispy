from __future__ import annotations

import io

from sqlalchemy import inspect, select

from app.data.session import SessionLocal, apply_runtime_migrations
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def _patch_valid_generated_images(monkeypatch):
    def fake_materialize_generated_image(_selected):
        from PIL import Image

        image = Image.new("RGB", (200, 200))
        for x in range(200):
            for y in range(200):
                image.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, ((x + y) * 2) % 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "b64_json"

    monkeypatch.setattr("app.services.runs.runtime._materialize_generated_image", fake_materialize_generated_image)


def _create_run(client) -> dict:
    resp = client.post(
        "/runs",
        json={
            "workspace_name": "mem-ws",
            "project_name": "mem-project",
            "product_name": "smart pet leash",
            "product_code": "MEM-001",
            "industry_code": "pet_care",
            "campaign_name": "meta-memory",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "copy_image_only",
            "business_context": {
                "target_audience": "dog owners",
                "key_value_props": ["night visibility", "anti-tangle"],
                "primary_cta": "Shop Now",
            },
        },
    )
    assert resp.status_code == 200
    return resp.json()


def test_execution_memory_runtime_migration_creates_table_and_indexes(client):
    from app.data.session import engine

    apply_runtime_migrations(engine)
    inspector = inspect(engine)
    assert "execution_memory_entry" in inspector.get_table_names()
    indexes = {item["name"] for item in inspector.get_indexes("execution_memory_entry")}
    assert "ix_execution_memory_run_created" in indexes
    assert "ix_execution_memory_variant_created" in indexes
    assert "ix_execution_memory_scope_status_run" in indexes
    assert "ix_execution_memory_stage_task_created" in indexes


def test_rejected_stage_rerun_includes_execution_memory_in_task_input(client):
    run = _create_run(client)
    run_id = run["id"]

    for stage in ["intake", "planning", "divergence"]:
        _run_worker_once()
        current = client.get(f"/runs/{run_id}").json()
        assert current["current_stage"] == stage
        if stage != "divergence":
            ok = client.post(f"/runs/{run_id}/advance", json={"notes": f"approve {stage}"})
            assert ok.status_code == 200

    rejected = client.post(f"/runs/{run_id}/reject", json={"notes": "need stronger variant separation"})
    assert rejected.status_code == 200

    _run_worker_once()

    with SessionLocal() as db:
        from app.data.models import StageTask

        task = db.scalar(select(StageTask).where(StageTask.run_id == run_id, StageTask.stage_name == "divergence"))
        assert task is not None
        assert task.attempt >= 2
        execution_memory = task.input_payload.get("execution_memory") or {}
        assert execution_memory["run"]["active_regen_goals"]
        assert execution_memory["run"]["last_human_decisions"]


def test_execution_memory_endpoint_and_variant_summary(client, monkeypatch):
    _patch_valid_generated_images(monkeypatch)

    run = _create_run(client)
    run_id = run["id"]

    for stage in ["intake", "planning", "divergence", "copy_image_generation", "visual_quality_assessment", "evaluation_selection"]:
        _run_worker_once()
        if stage != "evaluation_selection":
            ok = client.post(f"/runs/{run_id}/advance", json={"notes": f"approve {stage}"})
            assert ok.status_code == 200

    variants_resp = client.get(f"/runs/{run_id}/variants")
    assert variants_resp.status_code == 200
    variants_payload = variants_resp.json()
    first = variants_payload["items"][0]
    assert "execution_summary" in first
    assert set(first["execution_summary"]).issuperset(
        {"last_decision", "active_blockers", "active_regen_goal", "canonical_brief", "recent_memory"}
    )

    memory_resp = client.get(f"/runs/{run_id}/execution-memory")
    assert memory_resp.status_code == 200
    memory_payload = memory_resp.json()
    assert "run_ledger" in memory_payload
    assert "stage_handoffs" in memory_payload
    assert "variant_ledgers" in memory_payload
    assert "recent_reviews" in memory_payload
    assert "active_regeneration_goals" in memory_payload


def test_variant_regeneration_exposes_execution_memory_summary(client, monkeypatch):
    _patch_valid_generated_images(monkeypatch)

    run = _create_run(client)
    run_id = run["id"]

    for stage in ["intake", "planning", "divergence", "copy_image_generation", "visual_quality_assessment", "evaluation_selection"]:
        _run_worker_once()
        if stage != "evaluation_selection":
            ok = client.post(f"/runs/{run_id}/advance", json={"notes": f"approve {stage}"})
            assert ok.status_code == 200

    variants_payload = client.get(f"/runs/{run_id}/variants").json()
    target = variants_payload["items"][0]["variant_id"]

    regen = client.post(
        f"/runs/{run_id}/variants/{target}/regenerate",
        json={"reason": "fix product visibility and sharpen hook", "target_stage": "copy_image_generation"},
    )
    assert regen.status_code == 200
    regen_payload = regen.json()
    assert regen_payload["execution_summary"]["active_regen_goal"]
    assert regen_payload["execution_summary"]["recent_memory"]


def test_image_retry_does_not_write_execution_memory(client, monkeypatch):
    _patch_valid_generated_images(monkeypatch)

    run = _create_run(client)
    run_id = run["id"]

    for stage in ["intake", "planning", "divergence", "copy_image_generation"]:
        _run_worker_once()
        if stage != "copy_image_generation":
            ok = client.post(f"/runs/{run_id}/advance", json={"notes": f"approve {stage}"})
            assert ok.status_code == 200

    variants_payload = client.get(f"/runs/{run_id}/variants").json()
    target = variants_payload["items"][0]["variant_id"]

    with SessionLocal() as db:
        from app.data.models import ExecutionMemoryEntry

        before = db.scalars(select(ExecutionMemoryEntry).where(ExecutionMemoryEntry.run_id == run_id)).all()
        before_count = len(before)

    retry = client.post(
        f"/runs/{run_id}/variants/{target}/assets/image/retry",
        json={"reason": "retry failed provider image"},
    )
    assert retry.status_code == 200

    with SessionLocal() as db:
        from app.data.models import ExecutionMemoryEntry

        after = db.scalars(select(ExecutionMemoryEntry).where(ExecutionMemoryEntry.run_id == run_id)).all()
        assert len(after) == before_count
