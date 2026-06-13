from __future__ import annotations

from types import SimpleNamespace

from app.data.models import TaskStatus
from app.orchestrator.worker import PipelineWorker


def test_full_auto_visual_qa_regen_limit_is_scoped_per_task(monkeypatch):
    worker = PipelineWorker()
    worker._full_auto_regen_cycles = 2  # Simulates a different run exhausting the old process-level counter.
    calls: list[dict] = []

    def fake_regenerate_variant_assets(db, *, run_id: str, variant_id: str, reason: str):
        calls.append({"run_id": run_id, "variant_id": variant_id, "reason": reason})

    monkeypatch.setattr("app.orchestrator.worker.regenerate_variant_assets", fake_regenerate_variant_assets)

    task = SimpleNamespace(
        output_payload={
            "variant_summaries": [
                {"variant_id": "v1", "recommended_action": "request_regeneration"},
            ]
        },
        metadata_json={},
        status=TaskStatus.WAITING_REVIEW.value,
        retry_at=None,
        priority=2,
    )
    run = SimpleNamespace(id="run-b")

    should_auto_approve = worker._full_auto_visual_qa_regen(db=None, run=run, task=task)

    assert should_auto_approve is False
    assert task.status == TaskStatus.QUEUED.value
    assert task.metadata_json["full_auto_visual_qa_regen_cycles"] == 1
    assert calls == [
        {
            "run_id": "run-b",
            "variant_id": "v1",
            "reason": "full_auto_visual_qa_cycle_1",
        }
    ]
