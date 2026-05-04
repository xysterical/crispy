from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import (
    ExecutionMemoryEntry,
    ExecutionMemoryScope,
    ExecutionMemorySource,
    ExecutionMemoryStatus,
    PipelineRun,
    RunVariant,
    StageTask,
    VariantReviewAction,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def append_execution_memory(
    db: Session,
    *,
    run_id: str,
    memory_scope: str,
    memory_key: str,
    source: str,
    summary: str,
    payload: dict | None = None,
    stage_task_id: str | None = None,
    run_variant_id: str | None = None,
    stage_name: str | None = None,
    status: str = ExecutionMemoryStatus.ACTIVE.value,
) -> ExecutionMemoryEntry:
    entry = ExecutionMemoryEntry(
        run_id=run_id,
        stage_task_id=stage_task_id,
        run_variant_id=run_variant_id,
        stage_name=stage_name,
        memory_scope=memory_scope,
        memory_key=memory_key,
        status=status,
        source=source,
        summary=str(summary or "").strip(),
        payload=dict(payload or {}),
    )
    db.add(entry)
    db.flush()
    return entry


def append_execution_memory_payload(payload: dict, *, bucket: str, memory: dict) -> dict:
    next_payload = dict(payload or {})
    existing = dict(next_payload.get("execution_memory") or {})
    existing[bucket] = memory
    next_payload["execution_memory"] = existing
    return next_payload


def _variant_for(run_id: str, variant_id: str, db: Session) -> RunVariant | None:
    return db.scalar(select(RunVariant).where(RunVariant.run_id == run_id, RunVariant.variant_id == variant_id))


def _entry_view(row: ExecutionMemoryEntry) -> dict:
    return {
        "id": row.id,
        "memory_scope": row.memory_scope,
        "memory_key": row.memory_key,
        "status": row.status,
        "source": row.source,
        "stage_name": row.stage_name,
        "summary": row.summary,
        "payload": row.payload or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def _active_entries(
    db: Session,
    *,
    run_id: str,
    memory_key: str | None = None,
    memory_scope: str | None = None,
    stage_name: str | None = None,
    run_variant_id: str | None = None,
    source: str | None = None,
) -> list[ExecutionMemoryEntry]:
    query = select(ExecutionMemoryEntry).where(
        ExecutionMemoryEntry.run_id == run_id,
        ExecutionMemoryEntry.status == ExecutionMemoryStatus.ACTIVE.value,
    )
    if memory_key:
        query = query.where(ExecutionMemoryEntry.memory_key == memory_key)
    if memory_scope:
        query = query.where(ExecutionMemoryEntry.memory_scope == memory_scope)
    if stage_name:
        query = query.where(ExecutionMemoryEntry.stage_name == stage_name)
    if run_variant_id:
        query = query.where(ExecutionMemoryEntry.run_variant_id == run_variant_id)
    if source:
        query = query.where(ExecutionMemoryEntry.source == source)
    return db.scalars(query.order_by(desc(ExecutionMemoryEntry.created_at))).all()


def resolve_execution_memory_entries(
    db: Session,
    *,
    run_id: str,
    memory_key: str | None = None,
    memory_scope: str | None = None,
    stage_name: str | None = None,
    run_variant_id: str | None = None,
    statuses: tuple[str, ...] = (ExecutionMemoryStatus.ACTIVE.value,),
) -> list[ExecutionMemoryEntry]:
    query = select(ExecutionMemoryEntry).where(
        ExecutionMemoryEntry.run_id == run_id,
        ExecutionMemoryEntry.status.in_(statuses),
    )
    if memory_key:
        query = query.where(ExecutionMemoryEntry.memory_key == memory_key)
    if memory_scope:
        query = query.where(ExecutionMemoryEntry.memory_scope == memory_scope)
    if stage_name:
        query = query.where(ExecutionMemoryEntry.stage_name == stage_name)
    if run_variant_id:
        query = query.where(ExecutionMemoryEntry.run_variant_id == run_variant_id)
    return db.scalars(query.order_by(desc(ExecutionMemoryEntry.created_at))).all()


def resolve_execution_memory(
    db: Session,
    *,
    run_id: str,
    stage_name: str | None = None,
    variant_id: str | None = None,
) -> dict:
    variant = _variant_for(run_id, variant_id, db) if variant_id else None
    variant_row_id = variant.id if variant else None

    locked_facts = [
        _entry_view(row)
        for row in _active_entries(
            db,
            run_id=run_id,
            memory_key="locked_fact",
            memory_scope=ExecutionMemoryScope.RUN.value,
        )
    ]
    active_constraints = [
        _entry_view(row)
        for row in resolve_execution_memory_entries(
            db,
            run_id=run_id,
            statuses=(ExecutionMemoryStatus.ACTIVE.value,),
        )
        if row.memory_key in {"hard_constraint", "approved_strategy", "priority_angle", "forbidden_claim"}
        and row.memory_scope in {ExecutionMemoryScope.RUN.value, ExecutionMemoryScope.STAGE_HANDOFF.value}
    ]
    blocker_rows = []
    blocker_rows.extend(
        _active_entries(
            db,
            run_id=run_id,
            memory_key="quality_blocker",
            run_variant_id=variant_row_id,
        )
    )
    if stage_name:
        blocker_rows.extend(
            _active_entries(
                db,
                run_id=run_id,
                memory_key="stage_rejection",
                memory_scope=ExecutionMemoryScope.REVIEW.value,
                stage_name=stage_name,
            )
        )
    last_human_decisions = [
        _entry_view(row)
        for row in _recent_human_decisions(
            db,
            run_id=run_id,
            stage_name=stage_name,
            run_variant_id=variant_row_id,
            limit=5,
        )
    ]
    active_regen_goals = [
        _entry_view(row)
        for row in _active_entries(
            db,
            run_id=run_id,
            memory_key="regen_goal",
            memory_scope=ExecutionMemoryScope.REGENERATION.value,
            stage_name=stage_name,
            run_variant_id=variant_row_id,
        )
    ]

    return {
        "locked_facts": locked_facts,
        "active_constraints": active_constraints,
        "active_blockers": [_entry_view(row) for row in blocker_rows],
        "last_human_decisions": last_human_decisions,
        "active_regen_goals": active_regen_goals,
    }


def _recent_human_decisions(
    db: Session,
    *,
    run_id: str,
    stage_name: str | None = None,
    run_variant_id: str | None = None,
    limit: int = 5,
) -> list[ExecutionMemoryEntry]:
    query = select(ExecutionMemoryEntry).where(
        ExecutionMemoryEntry.run_id == run_id,
        ExecutionMemoryEntry.source == ExecutionMemorySource.HUMAN_REVIEW.value,
    )
    if stage_name:
        query = query.where(ExecutionMemoryEntry.stage_name == stage_name)
    if run_variant_id:
        query = query.where(ExecutionMemoryEntry.run_variant_id == run_variant_id)
    return db.scalars(query.order_by(desc(ExecutionMemoryEntry.created_at)).limit(limit)).all()


def resolve_entries_for_variant(db: Session, *, run_id: str, variant_id: str, memory_key: str) -> list[ExecutionMemoryEntry]:
    variant = _variant_for(run_id, variant_id, db)
    if not variant:
        return []
    return resolve_execution_memory_entries(
        db,
        run_id=run_id,
        run_variant_id=variant.id,
        memory_key=memory_key,
    )


def mark_execution_memory_status(
    db: Session,
    *,
    rows: list[ExecutionMemoryEntry],
    status: str,
) -> None:
    now = utcnow()
    for row in rows:
        row.status = status
        row.resolved_at = now if status == ExecutionMemoryStatus.RESOLVED.value else row.resolved_at


def write_stage_completion_memory(db: Session, *, run: PipelineRun, task: StageTask) -> None:
    payload = task.output_payload or {}
    if task.stage_name == "intake":
        product_name = payload.get("product_name") or run.product_code
        category_tags = payload.get("category_tags") or []
        if product_name:
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.RUN.value,
                memory_key="locked_fact",
                source=ExecutionMemorySource.SYSTEM_STAGE.value,
                summary=f"Product locked: {product_name}",
                payload={"product_name": product_name},
            )
        if category_tags:
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.RUN.value,
                memory_key="locked_fact",
                source=ExecutionMemorySource.SYSTEM_STAGE.value,
                summary=f"Category tags: {', '.join(category_tags[:4])}",
                payload={"category_tags": category_tags},
            )
        visual_identity = payload.get("visual_identity") or {}
        for item in (visual_identity.get("must_preserve_details") or [])[:4]:
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.RUN.value,
                memory_key="hard_constraint",
                source=ExecutionMemorySource.SYSTEM_STAGE.value,
                summary=str(item),
                payload={"constraint": item},
            )
        for item in (visual_identity.get("missing_fact_warnings") or [])[:4]:
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.RUN.value,
                memory_key="open_risk",
                source=ExecutionMemorySource.SYSTEM_STAGE.value,
                summary=str(item),
                payload={"risk": item},
            )
        return

    if task.stage_name == "divergence":
        for item in payload.get("variants", []):
            variant = _variant_for(run.id, item.get("variant_id", ""), db)
            if not variant:
                continue
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                run_variant_id=variant.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.VARIANT.value,
                memory_key="canonical_brief",
                source=ExecutionMemorySource.SYSTEM_STAGE.value,
                summary=f"{variant.variant_id}: {item.get('angle', '')}",
                payload={
                    "variant_id": variant.variant_id,
                    "angle": item.get("angle", ""),
                    "hook": item.get("hook", ""),
                    "message": item.get("message", ""),
                    "rationale": item.get("rationale", ""),
                },
            )
        return

    if task.stage_name == "visual_quality_assessment":
        for summary in payload.get("variant_summaries", []):
            variant = _variant_for(run.id, summary.get("variant_id", ""), db)
            if not variant:
                continue
            issues = [str(item) for item in (summary.get("issues") or []) if str(item).strip()]
            if issues:
                append_execution_memory(
                    db,
                    run_id=run.id,
                    stage_task_id=task.id,
                    run_variant_id=variant.id,
                    stage_name=task.stage_name,
                    memory_scope=ExecutionMemoryScope.VARIANT.value,
                    memory_key="quality_blocker",
                    source=ExecutionMemorySource.VISUAL_QA.value,
                    summary=issues[0],
                    payload={
                        "variant_id": variant.variant_id,
                        "issues": issues,
                        "recommended_action": summary.get("recommended_action"),
                    },
                )
            if summary.get("recommended_action"):
                append_execution_memory(
                    db,
                    run_id=run.id,
                    stage_task_id=task.id,
                    run_variant_id=variant.id,
                    stage_name=task.stage_name,
                    memory_scope=ExecutionMemoryScope.VARIANT.value,
                    memory_key="recommended_next_action",
                    source=ExecutionMemorySource.VISUAL_QA.value,
                    summary=str(summary.get("recommended_action")),
                    payload=summary,
                )
        return

    if task.stage_name == "evaluation_selection":
        ranked = ((payload.get("evaluation_result") or {}).get("ranked_variants") or [])
        for item in ranked:
            variant = _variant_for(run.id, item.get("variant_id", ""), db)
            if not variant:
                continue
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                run_variant_id=variant.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.VARIANT.value,
                memory_key="selection_signal",
                source=ExecutionMemorySource.EVALUATION.value,
                summary=f"Score {item.get('total_score')} with action {item.get('recommended_action')}",
                payload=item,
            )
            if item.get("recommended_action"):
                append_execution_memory(
                    db,
                    run_id=run.id,
                    stage_task_id=task.id,
                    run_variant_id=variant.id,
                    stage_name=task.stage_name,
                    memory_scope=ExecutionMemoryScope.VARIANT.value,
                    memory_key="recommended_next_action",
                    source=ExecutionMemorySource.EVALUATION.value,
                    summary=str(item.get("recommended_action")),
                    payload=item,
                )


def write_stage_approval_memory(db: Session, *, run: PipelineRun, task: StageTask, notes: str) -> None:
    append_execution_memory(
        db,
        run_id=run.id,
        stage_task_id=task.id,
        stage_name=task.stage_name,
        memory_scope=ExecutionMemoryScope.REVIEW.value,
        memory_key="stage_approval",
        source=ExecutionMemorySource.HUMAN_REVIEW.value,
        summary=notes or f"Approved {task.stage_name}",
        payload={"notes": notes, "stage_name": task.stage_name},
    )
    if task.stage_name == "planning":
        output = task.output_payload or {}
        commercial_strategy = output.get("commercial_strategy") or {}
        positioning = commercial_strategy.get("positioning") or output.get("positioning") or ""
        audience = (commercial_strategy.get("audience") or output.get("audience_priorities") or [])
        if positioning or audience:
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.STAGE_HANDOFF.value,
                memory_key="approved_strategy",
                source=ExecutionMemorySource.HUMAN_REVIEW.value,
                summary=f"Approved planning strategy for {audience[0] if audience else 'target audience'}",
                payload={"positioning": positioning, "audience": audience},
            )
        for angle in (commercial_strategy.get("angle_portfolio") or output.get("strategic_angles") or [])[:4]:
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.STAGE_HANDOFF.value,
                memory_key="priority_angle",
                source=ExecutionMemorySource.HUMAN_REVIEW.value,
                summary=str(angle),
                payload={"angle": angle},
            )
        for constraint in (commercial_strategy.get("claim_boundaries") or output.get("constraints") or [])[:5]:
            append_execution_memory(
                db,
                run_id=run.id,
                stage_task_id=task.id,
                stage_name=task.stage_name,
                memory_scope=ExecutionMemoryScope.RUN.value,
                memory_key="forbidden_claim",
                source=ExecutionMemorySource.HUMAN_REVIEW.value,
                summary=str(constraint),
                payload={"constraint": constraint},
            )


def write_stage_rejection_memory(db: Session, *, run: PipelineRun, task: StageTask, notes: str) -> None:
    append_execution_memory(
        db,
        run_id=run.id,
        stage_task_id=task.id,
        stage_name=task.stage_name,
        memory_scope=ExecutionMemoryScope.REVIEW.value,
        memory_key="stage_rejection",
        source=ExecutionMemorySource.HUMAN_REVIEW.value,
        summary=notes or f"Rejected {task.stage_name}",
        payload={"notes": notes, "stage_name": task.stage_name},
    )
    append_execution_memory(
        db,
        run_id=run.id,
        stage_task_id=task.id,
        stage_name=task.stage_name,
        memory_scope=ExecutionMemoryScope.REGENERATION.value,
        memory_key="regen_goal",
        source=ExecutionMemorySource.HUMAN_REVIEW.value,
        summary=notes or f"Fix issues in {task.stage_name}",
        payload={"notes": notes, "stage_name": task.stage_name},
    )


def write_variant_review_memory(
    db: Session,
    *,
    run_id: str,
    variant: RunVariant,
    action: str,
    comment: str,
    tags: list[str],
    metadata: dict,
) -> None:
    append_execution_memory(
        db,
        run_id=run_id,
        run_variant_id=variant.id,
        stage_name=metadata.get("target_stage") or "variant_review",
        memory_scope=ExecutionMemoryScope.VARIANT.value,
        memory_key="variant_decision",
        source=ExecutionMemorySource.HUMAN_REVIEW.value,
        summary=comment or action,
        payload={"action": action, "comment": comment, "tags": tags, "metadata": metadata, "variant_id": variant.variant_id},
    )
    append_execution_memory(
        db,
        run_id=run_id,
        run_variant_id=variant.id,
        stage_name=metadata.get("target_stage") or "variant_review",
        memory_scope=ExecutionMemoryScope.REVIEW.value,
        memory_key="review_decision",
        source=ExecutionMemorySource.HUMAN_REVIEW.value,
        summary=comment or action,
        payload={"action": action, "comment": comment, "tags": tags, "metadata": metadata, "variant_id": variant.variant_id},
    )
    for tag in tags:
        append_execution_memory(
            db,
            run_id=run_id,
            run_variant_id=variant.id,
            stage_name=metadata.get("target_stage") or "variant_review",
            memory_scope=ExecutionMemoryScope.REVIEW.value,
            memory_key="operator_tag",
            source=ExecutionMemorySource.HUMAN_REVIEW.value,
            summary=str(tag),
            payload={"tag": tag, "action": action, "variant_id": variant.variant_id},
        )

    if action in {VariantReviewAction.REJECT.value, VariantReviewAction.REQUEST_REGENERATION.value}:
        blocker_summary = comment or tags[0] if tags else action
        append_execution_memory(
            db,
            run_id=run_id,
            run_variant_id=variant.id,
            stage_name=metadata.get("target_stage") or "variant_review",
            memory_scope=ExecutionMemoryScope.VARIANT.value,
            memory_key="quality_blocker",
            source=ExecutionMemorySource.HUMAN_REVIEW.value,
            summary=str(blocker_summary),
            payload={"action": action, "comment": comment, "tags": tags, "variant_id": variant.variant_id},
        )
        append_execution_memory(
            db,
            run_id=run_id,
            run_variant_id=variant.id,
            stage_name=metadata.get("target_stage"),
            memory_scope=ExecutionMemoryScope.REGENERATION.value,
            memory_key="regen_goal",
            source=ExecutionMemorySource.HUMAN_REVIEW.value,
            summary=comment or f"Regenerate {variant.variant_id}",
            payload={"action": action, "comment": comment, "tags": tags, "variant_id": variant.variant_id, "target_stage": metadata.get("target_stage")},
        )
        return

    if action in {
        VariantReviewAction.APPROVE.value,
        VariantReviewAction.SHORTLIST.value,
        VariantReviewAction.SET_WINNER.value,
    }:
        rows = resolve_execution_memory_entries(
            db,
            run_id=run_id,
            run_variant_id=variant.id,
            statuses=(ExecutionMemoryStatus.ACTIVE.value,),
        )
        to_resolve = [row for row in rows if row.memory_key in {"quality_blocker", "regen_goal"}]
        mark_execution_memory_status(db, rows=to_resolve, status=ExecutionMemoryStatus.RESOLVED.value)


def write_regeneration_memory(
    db: Session,
    *,
    run_id: str,
    variant: RunVariant,
    stage_name: str,
    reason: str,
    scope: str,
    status: str,
) -> None:
    append_execution_memory(
        db,
        run_id=run_id,
        run_variant_id=variant.id,
        stage_name=stage_name,
        memory_scope=ExecutionMemoryScope.REGENERATION.value,
        memory_key="regen_request" if status == "requested" else "regen_result",
        source=ExecutionMemorySource.REGENERATION.value,
        summary=reason if status == "requested" else f"Regenerated {variant.variant_id} at {stage_name}",
        payload={"variant_id": variant.variant_id, "target_stage": stage_name, "reason": reason, "scope": scope, "status": status},
    )


def build_variant_execution_summary(db: Session, run_id: str, variant_id: str) -> dict:
    variant = _variant_for(run_id, variant_id, db)
    if not variant:
        return {
            "last_decision": None,
            "active_blockers": [],
            "active_regen_goal": None,
            "canonical_brief": None,
            "recent_memory": [],
        }
    rows = resolve_execution_memory_entries(
        db,
        run_id=run_id,
        run_variant_id=variant.id,
        statuses=(
            ExecutionMemoryStatus.ACTIVE.value,
            ExecutionMemoryStatus.RESOLVED.value,
            ExecutionMemoryStatus.SUPERSEDED.value,
        ),
    )
    last_decision = next((row for row in rows if row.memory_key in {"variant_decision", "review_decision"}), None)
    active_blockers = [row for row in rows if row.status == ExecutionMemoryStatus.ACTIVE.value and row.memory_key == "quality_blocker"]
    active_regen_goal = next(
        (
            row
            for row in rows
            if row.status == ExecutionMemoryStatus.ACTIVE.value and row.memory_key == "regen_goal"
        ),
        None,
    )
    canonical_brief = next((row for row in rows if row.memory_key == "canonical_brief"), None)
    recent_memory = [_entry_view(row) for row in rows[:5]]
    return {
        "last_decision": _entry_view(last_decision) if last_decision else None,
        "active_blockers": [_entry_view(row) for row in active_blockers],
        "active_regen_goal": _entry_view(active_regen_goal) if active_regen_goal else None,
        "canonical_brief": _entry_view(canonical_brief) if canonical_brief else None,
        "recent_memory": recent_memory,
    }


def build_run_execution_ledger(db: Session, run_id: str) -> dict:
    run_rows = resolve_execution_memory_entries(
        db,
        run_id=run_id,
        statuses=(
            ExecutionMemoryStatus.ACTIVE.value,
            ExecutionMemoryStatus.RESOLVED.value,
            ExecutionMemoryStatus.SUPERSEDED.value,
        ),
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in run_rows:
        grouped[row.memory_scope].append(_entry_view(row))

    variant_rows = db.scalars(select(RunVariant).where(RunVariant.run_id == run_id).order_by(RunVariant.variant_id.asc())).all()
    return {
        "run_ledger": {
            "locked_facts": [item for item in grouped[ExecutionMemoryScope.RUN.value] if item["memory_key"] == "locked_fact"],
            "active_constraints": [
                item
                for item in grouped[ExecutionMemoryScope.RUN.value] + grouped[ExecutionMemoryScope.STAGE_HANDOFF.value]
                if item["memory_key"] in {"hard_constraint", "approved_strategy", "priority_angle", "forbidden_claim"}
            ],
            "open_risks": [item for item in grouped[ExecutionMemoryScope.RUN.value] if item["memory_key"] == "open_risk"],
        },
        "stage_handoffs": grouped[ExecutionMemoryScope.STAGE_HANDOFF.value],
        "variant_ledgers": [
            {"variant_id": row.variant_id, "execution_summary": build_variant_execution_summary(db, run_id, row.variant_id)}
            for row in variant_rows
        ],
        "recent_reviews": grouped[ExecutionMemoryScope.REVIEW.value][:10],
        "active_regeneration_goals": [
            item
            for item in grouped[ExecutionMemoryScope.REGENERATION.value]
            if item["memory_key"] == "regen_goal" and item["status"] == ExecutionMemoryStatus.ACTIVE.value
        ],
    }
