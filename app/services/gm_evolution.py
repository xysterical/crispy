from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import (
    FeedbackImport,
    GmMemory,
    GmPolicyPromotion,
    GmPolicyVersion,
    GmReflection,
    PipelineRun,
    RunVariant,
    VariantReview,
    VariantScore,
)
from app.schemas.contracts import FeedbackRow


def utcnow() -> datetime:
    return datetime.now(UTC)


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _top_items(counter: Counter[str], limit: int = 5) -> list[str]:
    return [item for item, _ in counter.most_common(limit) if item]


def _serialize_content(payload: dict) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _weighted_score(row: FeedbackRow) -> float:
    ctr = (row.clicks / row.impressions) if row.impressions > 0 else 0.0
    cpc = (row.spend / row.clicks) if row.clicks > 0 else 0.0
    cpa = (row.spend / row.conversions) if row.conversions > 0 else 0.0
    roas = (row.revenue / row.spend) if row.spend > 0 else 0.0
    ctr_score = min(100.0, ctr * 1000.0)
    cpc_score = max(0.0, 100.0 / (1.0 + max(0.0, cpc)))
    cpa_score = max(0.0, 100.0 / (1.0 + max(0.0, cpa)))
    roas_score = min(100.0, roas * 30.0)
    return round(ctr_score * 0.35 + cpc_score * 0.15 + cpa_score * 0.30 + roas_score * 0.20, 2)


def _variant_lookup(db: Session, run_id: str | None, variant_id: str | None) -> RunVariant | None:
    if not run_id or not variant_id:
        return None
    return db.scalar(select(RunVariant).where(RunVariant.run_id == run_id, RunVariant.variant_id == variant_id))


def _variant_pattern_payload(db: Session, run_id: str | None, variant_id: str | None) -> dict:
    variant = _variant_lookup(db, run_id, variant_id)
    if not variant:
        return {}
    reviews = db.scalars(
        select(VariantReview).where(VariantReview.run_variant_id == variant.id).order_by(desc(VariantReview.created_at))
    ).all()
    review_tags = sorted({tag for review in reviews for tag in (review.tags or [])})
    scores = db.scalars(select(VariantScore).where(VariantScore.run_variant_id == variant.id)).all()
    evaluation = next((score for score in scores if score.score_type == "evaluation"), None)
    visual_quality = next((score for score in scores if score.score_type == "visual_quality"), None)
    return {
        "variant_id": variant.variant_id,
        "angle": variant.angle,
        "hook": variant.hook,
        "message": variant.message,
        "review_tags": review_tags,
        "evaluation_reasons": (evaluation.reasons if evaluation else []) or [],
        "visual_qa_issues": (visual_quality.reasons if visual_quality else []) or [],
        "recommended_action": (evaluation.recommended_action if evaluation else None) or (visual_quality.recommended_action if visual_quality else None),
    }


def _shop_thesis(db: Session, *, project_id: str, industry_code: str | None, shop_id: str | None) -> dict:
    rows = db.scalars(
        select(GmMemory)
        .where(
            GmMemory.project_id == project_id,
            GmMemory.source_type.in_(["shop_profile", "competitor_analysis"]),
        )
        .order_by(desc(GmMemory.created_at))
        .limit(20)
    ).all()
    positioning = ""
    competitor_note = ""
    for row in rows:
        content = row.content or {}
        if shop_id and content.get("shop_id") not in {None, "", shop_id}:
            continue
        if industry_code and row.industry_code not in {None, "", industry_code}:
            continue
        if row.source_type == "shop_profile" and not positioning:
            profile = content.get("profile") or {}
            positioning = str(profile.get("positioning") or content.get("store_url") or "").strip()
        if row.source_type == "competitor_analysis" and not competitor_note:
            report = str(content.get("report") or "").strip()
            competitor_note = report[:280]
        if positioning and competitor_note:
            break
    return {
        "positioning": positioning,
        "competitor_note": competitor_note,
    }


def _policy_version_filters(
    *,
    project_id: str,
    target_scope: str,
    shop_id: str | None,
    product_code: str | None,
    industry_code: str | None,
    pipeline_mode: str | None,
) -> list:
    filters = [
        GmPolicyVersion.project_id == project_id,
        GmPolicyVersion.target_scope == target_scope,
    ]
    if shop_id:
        filters.append(GmPolicyVersion.shop_id == shop_id)
    else:
        filters.append(GmPolicyVersion.shop_id.is_(None))
    if product_code:
        filters.append(GmPolicyVersion.product_code == product_code)
    else:
        filters.append(GmPolicyVersion.product_code.is_(None))
    if industry_code:
        filters.append(GmPolicyVersion.industry_code == industry_code)
    else:
        filters.append(GmPolicyVersion.industry_code.is_(None))
    if pipeline_mode:
        filters.append(GmPolicyVersion.pipeline_mode == pipeline_mode)
    else:
        filters.append(GmPolicyVersion.pipeline_mode.is_(None))
    return filters


def _next_policy_version(
    db: Session,
    *,
    project_id: str,
    target_scope: str,
    shop_id: str | None,
    product_code: str | None,
    industry_code: str | None,
    pipeline_mode: str | None,
) -> int:
    latest = db.scalar(
        select(GmPolicyVersion.version)
        .where(
            *_policy_version_filters(
                project_id=project_id,
                target_scope=target_scope,
                shop_id=shop_id,
                product_code=product_code,
                industry_code=industry_code,
                pipeline_mode=pipeline_mode,
            )
        )
        .order_by(desc(GmPolicyVersion.version))
        .limit(1)
    )
    return int(latest or 0) + 1


def _upsert_reflection(
    db: Session,
    *,
    existing: GmReflection | None,
    project_id: str,
    run_id: str | None,
    feedback_import_id: str | None,
    reflection_type: str,
    target_scope: str,
    shop_id: str | None,
    product_code: str | None,
    industry_code: str | None,
    pipeline_mode: str | None,
    confidence_score: float | None,
    evidence_count: int,
    summary: str,
    payload: dict,
) -> GmReflection:
    row = existing or GmReflection(
        project_id=project_id,
        run_id=run_id,
        feedback_import_id=feedback_import_id,
        reflection_type=reflection_type,
        target_scope=target_scope,
    )
    row.shop_id = shop_id
    row.product_code = product_code
    row.industry_code = industry_code
    row.pipeline_mode = pipeline_mode
    row.confidence_score = confidence_score
    row.evidence_count = evidence_count
    row.summary = summary
    row.payload = payload
    db.add(row)
    db.flush()
    return row


def build_candidate_policy(
    db: Session,
    *,
    project_id: str,
    target_scope: str,
    shop_id: str | None,
    product_code: str | None,
    industry_code: str | None,
    pipeline_mode: str | None,
) -> GmPolicyVersion | None:
    reflections = db.scalars(
        select(GmReflection)
        .where(
            GmReflection.project_id == project_id,
            GmReflection.target_scope == target_scope,
            GmReflection.shop_id == shop_id if shop_id else GmReflection.shop_id.is_(None),
            GmReflection.product_code == product_code if product_code else GmReflection.product_code.is_(None),
            GmReflection.industry_code == industry_code if industry_code else GmReflection.industry_code.is_(None),
            GmReflection.pipeline_mode == pipeline_mode if pipeline_mode else GmReflection.pipeline_mode.is_(None),
        )
        .order_by(desc(GmReflection.created_at))
        .limit(24)
    ).all()
    if not reflections:
        return None
    evidence_total = sum(max(1, int(row.evidence_count or 0)) for row in reflections)

    winning_angles: Counter[str] = Counter()
    avoid_angles: Counter[str] = Counter()
    hard_constraints: Counter[str] = Counter()
    selection_biases: Counter[str] = Counter()
    regeneration_rules: Counter[str] = Counter()
    evidence_digest: list[str] = []

    for row in reflections:
        payload = row.payload or {}
        winning_angles.update(str(item) for item in (payload.get("winning_angles") or []) if str(item).strip())
        avoid_angles.update(str(item) for item in (payload.get("avoid_angles") or []) if str(item).strip())
        hard_constraints.update(str(item) for item in (payload.get("hard_constraints") or []) if str(item).strip())
        selection_biases.update(str(item) for item in (payload.get("selection_biases") or []) if str(item).strip())
        regeneration_rules.update(str(item) for item in (payload.get("regeneration_rules") or []) if str(item).strip())
        if row.summary:
            evidence_digest.append(row.summary)

    thesis = _shop_thesis(db, project_id=project_id, industry_code=industry_code, shop_id=shop_id)
    content = {
        "summary": _dedupe_strings(
            [
                f"Prioritize {', '.join(_top_items(winning_angles, 3))}." if winning_angles else "",
                f"Avoid {', '.join(_top_items(avoid_angles, 3))}." if avoid_angles else "",
                f"Guard against {', '.join(_top_items(hard_constraints, 3))}." if hard_constraints else "",
            ]
        ),
        "shop_thesis": thesis,
        "angle_priorities": _top_items(winning_angles, 5),
        "avoid_patterns": _top_items(avoid_angles, 5),
        "hard_constraints": _top_items(hard_constraints, 6),
        "selection_biases": _top_items(selection_biases, 5),
        "regeneration_rules": _top_items(regeneration_rules, 5),
        "evidence_digest": _dedupe_strings(evidence_digest[:8]),
    }
    if not any(content[key] for key in ["angle_priorities", "avoid_patterns", "hard_constraints", "selection_biases", "regeneration_rules", "evidence_digest"]):
        return None

    latest = db.scalar(
        select(GmPolicyVersion)
        .where(
            *_policy_version_filters(
                project_id=project_id,
                target_scope=target_scope,
                shop_id=shop_id,
                product_code=product_code,
                industry_code=industry_code,
                pipeline_mode=pipeline_mode,
            )
        )
        .order_by(desc(GmPolicyVersion.version))
        .limit(1)
    )
    serialized = _serialize_content(content)
    if latest and _serialize_content(latest.content or {}) == serialized:
        latest.evidence_count = evidence_total
        latest.confidence_score = round(min(0.95, 0.45 + 0.02 * evidence_total), 2)
        latest.source_reflection_ids = [row.id for row in reflections[:12]]
        db.add(latest)
        db.flush()
        return evaluate_gm_policy(db, latest.id)

    policy = GmPolicyVersion(
        project_id=project_id,
        version=_next_policy_version(
            db,
            project_id=project_id,
            target_scope=target_scope,
            shop_id=shop_id,
            product_code=product_code,
            industry_code=industry_code,
            pipeline_mode=pipeline_mode,
        ),
        status="candidate",
        target_scope=target_scope,
        shop_id=shop_id,
        product_code=product_code,
        industry_code=industry_code,
        pipeline_mode=pipeline_mode,
        confidence_score=round(min(0.95, 0.45 + 0.02 * evidence_total), 2),
        evidence_count=evidence_total,
        source_reflection_ids=[row.id for row in reflections[:12]],
        content=content,
    )
    db.add(policy)
    db.flush()
    return evaluate_gm_policy(db, policy.id)


def evaluate_gm_policy(db: Session, policy_id: str) -> GmPolicyVersion:
    policy = db.get(GmPolicyVersion, policy_id)
    if not policy:
        raise ValueError("gm policy not found")
    reflections = db.scalars(
        select(GmReflection)
        .where(GmReflection.id.in_(policy.source_reflection_ids or []))
        .order_by(desc(GmReflection.created_at))
    ).all()
    if not reflections:
        reflections = db.scalars(
            select(GmReflection)
            .where(
                GmReflection.project_id == policy.project_id,
                GmReflection.target_scope == policy.target_scope,
                GmReflection.shop_id == policy.shop_id if policy.shop_id else GmReflection.shop_id.is_(None),
                GmReflection.product_code == policy.product_code if policy.product_code else GmReflection.product_code.is_(None),
                GmReflection.industry_code == policy.industry_code if policy.industry_code else GmReflection.industry_code.is_(None),
                GmReflection.pipeline_mode == policy.pipeline_mode if policy.pipeline_mode else GmReflection.pipeline_mode.is_(None),
            )
            .order_by(desc(GmReflection.created_at))
            .limit(24)
        ).all()

    content = policy.content or {}
    policy_angles = set(str(item) for item in (content.get("angle_priorities") or []) if str(item).strip())
    avoid_patterns = set(str(item) for item in (content.get("avoid_patterns") or []) if str(item).strip())
    hard_constraints = set(str(item) for item in (content.get("hard_constraints") or []) if str(item).strip())
    selection_biases = set(str(item) for item in (content.get("selection_biases") or []) if str(item).strip())
    regeneration_rules = set(str(item) for item in (content.get("regeneration_rules") or []) if str(item).strip())

    checks: list[dict] = []
    support = 0
    total = 0
    for row in reflections:
        payload = row.payload or {}
        winning = set(str(item) for item in (payload.get("winning_angles") or []) if str(item).strip())
        avoid = set(str(item) for item in (payload.get("avoid_angles") or []) if str(item).strip())
        constraints = set(str(item) for item in (payload.get("hard_constraints") or []) if str(item).strip())
        selection = set(str(item) for item in (payload.get("selection_biases") or []) if str(item).strip())
        regen = set(str(item) for item in (payload.get("regeneration_rules") or []) if str(item).strip())

        if winning:
            total += 1
            hit = bool(policy_angles.intersection(winning))
            support += 1 if hit else 0
            checks.append({"reflection_id": row.id, "check": "winning_angles", "passed": hit, "matched": sorted(policy_angles.intersection(winning))})
        if avoid:
            total += 1
            hit = bool(avoid_patterns.intersection(avoid))
            support += 1 if hit else 0
            checks.append({"reflection_id": row.id, "check": "avoid_patterns", "passed": hit, "matched": sorted(avoid_patterns.intersection(avoid))})
        if constraints:
            total += 1
            hit = bool(hard_constraints.intersection(constraints))
            support += 1 if hit else 0
            checks.append({"reflection_id": row.id, "check": "hard_constraints", "passed": hit, "matched": sorted(hard_constraints.intersection(constraints))})
        if selection and selection_biases:
            total += 1
            hit = bool(selection_biases.intersection(selection))
            support += 1 if hit else 0
            checks.append({"reflection_id": row.id, "check": "selection_biases", "passed": hit, "matched": sorted(selection_biases.intersection(selection))})
        if regen and regeneration_rules:
            total += 1
            hit = bool(regeneration_rules.intersection(regen))
            support += 1 if hit else 0
            checks.append({"reflection_id": row.id, "check": "regeneration_rules", "passed": hit, "matched": sorted(regeneration_rules.intersection(regen))})

    replay_score = round((support / total), 2) if total else 0.0
    if policy.evidence_count >= 2 and total >= 2 and replay_score >= 0.6:
        replay_status = "passed"
    elif total == 0 or policy.evidence_count < 2:
        replay_status = "needs_review"
    else:
        replay_status = "failed"

    policy.replay_status = replay_status
    policy.replay_score = replay_score
    policy.replay_summary = (
        f"Replay {replay_status}: {support}/{total} checks aligned with historical reflections "
        f"across {len(reflections)} evidence rows."
    )
    policy.replay_details = {
        "support_checks": support,
        "total_checks": total,
        "reflection_count": len(reflections),
        "checks": checks[:24],
    }
    policy.last_evaluated_at = utcnow()
    db.add(policy)
    db.flush()
    return policy


def compile_run_outcome_reflection(db: Session, run_id: str) -> tuple[GmReflection | None, GmPolicyVersion | None]:
    run = db.get(PipelineRun, run_id)
    if not run:
        return None, None
    variants = db.scalars(select(RunVariant).where(RunVariant.run_id == run_id).order_by(desc(RunVariant.current_score))).all()
    if not variants:
        return None, None

    winner = next((row for row in variants if row.is_winner), variants[0])
    low_rows = [row for row in variants if row.regenerate_requested or (row.current_score is not None and row.current_score < 60)]
    review_tags = sorted(
        {
            tag
            for row in variants
            for review in db.scalars(select(VariantReview).where(VariantReview.run_variant_id == row.id)).all()
            for tag in (review.tags or [])
        }
    )
    winning_reasons = []
    if winner:
        winner_eval = db.scalar(
            select(VariantScore).where(VariantScore.run_variant_id == winner.id, VariantScore.score_type == "evaluation").limit(1)
        )
        winning_reasons = [str(item) for item in ((winner_eval.reasons if winner_eval else []) or [])[:4]]
    payload = {
        "winner_variant_id": winner.variant_id if winner else None,
        "winning_angles": [winner.angle] if winner and winner.angle else [],
        "avoid_angles": [row.angle for row in low_rows if row.angle],
        "hard_constraints": review_tags[:6],
        "selection_biases": winning_reasons,
        "regeneration_rules": _dedupe_strings(
            [
                reason
                for row in low_rows
                for score in db.scalars(select(VariantScore).where(VariantScore.run_variant_id == row.id)).all()
                for reason in ((score.reasons or [])[:3] if score.score_type in {"evaluation", "visual_quality"} else [])
            ]
        )[:6],
        "variant_snapshot": [
            {
                "variant_id": row.variant_id,
                "angle": row.angle,
                "score": row.current_score,
                "status": row.status,
                "review_status": row.review_status,
            }
            for row in variants[:6]
        ],
    }
    summary = (
        f"Run {run_id} winner {winner.variant_id if winner else '-'} favored angle "
        f"{winner.angle if winner and winner.angle else 'n/a'}; avoid {', '.join(payload['avoid_angles'][:2]) or 'no recurring weak angle yet'}."
    )
    existing = db.scalar(
        select(GmReflection).where(GmReflection.run_id == run_id, GmReflection.reflection_type == "run_outcome").limit(1)
    )
    reflection = _upsert_reflection(
        db,
        existing=existing,
        project_id=run.project_id,
        run_id=run.id,
        feedback_import_id=None,
        reflection_type="run_outcome",
        target_scope="product" if run.product_code else "industry",
        shop_id=run.workspace_id,
        product_code=run.product_code or None,
        industry_code=run.industry_code or None,
        pipeline_mode=run.pipeline_mode or None,
        confidence_score=round(min(0.9, 0.5 + 0.04 * len(variants)), 2),
        evidence_count=len(variants),
        summary=summary,
        payload=payload,
    )
    policy = build_candidate_policy(
        db,
        project_id=run.project_id,
        target_scope=reflection.target_scope,
        shop_id=run.workspace_id,
        product_code=run.product_code or None,
        industry_code=run.industry_code or None,
        pipeline_mode=run.pipeline_mode or None,
    )
    return reflection, policy


def compile_operator_review_reflection(
    db: Session,
    *,
    run_id: str,
    variant_id: str,
    action: str,
    tags: list[str] | None,
    comment: str | None,
) -> tuple[GmReflection | None, GmPolicyVersion | None]:
    run = db.get(PipelineRun, run_id)
    variant = _variant_lookup(db, run_id, variant_id)
    if not run or not variant:
        return None, None
    tag_list = _dedupe_strings([str(tag) for tag in (tags or [])])
    payload = {
        "winning_angles": [variant.angle] if action in {"approve_variant", "set_winner"} and variant.angle else [],
        "avoid_angles": [variant.angle] if action in {"reject_variant", "request_regeneration"} and variant.angle else [],
        "hard_constraints": tag_list,
        "selection_biases": [str(comment).strip()] if action in {"approve_variant", "set_winner"} and comment else [],
        "regeneration_rules": tag_list if action == "request_regeneration" else [],
        "variant_pattern": _variant_pattern_payload(db, run_id, variant_id),
        "action": action,
        "comment": comment or "",
    }
    summary = (
        f"Operator review on {variant_id}: action={action}; "
        f"tags={', '.join(tag_list[:4]) or 'none'}; angle={variant.angle or 'n/a'}."
    )
    reflection = _upsert_reflection(
        db,
        existing=None,
        project_id=run.project_id,
        run_id=run.id,
        feedback_import_id=None,
        reflection_type="operator_review",
        target_scope="product" if run.product_code else "industry",
        shop_id=run.workspace_id,
        product_code=run.product_code or None,
        industry_code=run.industry_code or None,
        pipeline_mode=run.pipeline_mode or None,
        confidence_score=0.75 if tag_list or action in {"approve_variant", "set_winner"} else 0.55,
        evidence_count=max(1, len(tag_list)),
        summary=summary,
        payload=payload,
    )
    policy = build_candidate_policy(
        db,
        project_id=run.project_id,
        target_scope=reflection.target_scope,
        shop_id=run.workspace_id,
        product_code=run.product_code or None,
        industry_code=run.industry_code or None,
        pipeline_mode=run.pipeline_mode or None,
    )
    return reflection, policy


def compile_feedback_import_reflections(
    db: Session,
    *,
    import_record: FeedbackImport,
    rows: list[FeedbackRow],
) -> list[GmReflection]:
    grouped: dict[tuple[str, str | None, str | None, str | None], list[tuple[FeedbackRow, float, dict, str | None]]] = defaultdict(list)
    for row in rows:
        run = db.get(PipelineRun, row.run_id) if row.run_id else None
        resolved_variant_id = row.variant_id or row.creative_key
        weighted = _weighted_score(row)
        pattern = _variant_pattern_payload(db, row.run_id, resolved_variant_id)
        product_code = (run.product_code if run else None) or row.product_code or None
        industry_code = (run.industry_code if run else None) or row.industry_code or None
        pipeline_mode = run.pipeline_mode if run else None
        if product_code:
            grouped[("product", product_code, industry_code, pipeline_mode)].append((row, weighted, pattern, run.workspace_id if run else None))
        if industry_code:
            grouped[("industry", None, industry_code, pipeline_mode)].append((row, weighted, pattern, run.workspace_id if run else None))

    reflections: list[GmReflection] = []
    for (target_scope, product_code, industry_code, pipeline_mode), items in grouped.items():
        ranked = sorted(items, key=lambda item: item[1], reverse=True)
        top = ranked[:3]
        bottom = ranked[-3:]
        shop_ids = [item[3] for item in ranked if item[3]]
        shop_id = shop_ids[0] if target_scope == "product" and shop_ids else None
        payload = {
            "winning_angles": [item[2].get("angle") for item in top if item[2].get("angle")],
            "avoid_angles": [item[2].get("angle") for item in bottom if item[2].get("angle")],
            "hard_constraints": _dedupe_strings(
                [
                    tag
                    for item in bottom
                    for tag in (item[2].get("review_tags") or [])
                ]
            )[:6],
            "selection_biases": _dedupe_strings(
                [
                    reason
                    for item in top
                    for reason in (item[2].get("evaluation_reasons") or [])
                ]
            )[:6],
            "regeneration_rules": _dedupe_strings(
                [
                    reason
                    for item in bottom
                    for reason in (item[2].get("visual_qa_issues") or [])
                ]
            )[:6],
            "top_variants": [
                {
                    "variant_id": item[0].variant_id or item[0].creative_key,
                    "weighted_score": item[1],
                    "pattern": item[2],
                }
                for item in top
            ],
            "underperformers": [
                {
                    "variant_id": item[0].variant_id or item[0].creative_key,
                    "weighted_score": item[1],
                    "pattern": item[2],
                }
                for item in bottom
            ],
        }
        scope_value = product_code or industry_code or "unknown"
        summary = (
            f"Feedback import {import_record.id} for {target_scope}={scope_value}: "
            f"top={', '.join(payload['winning_angles'][:2]) or 'n/a'}, "
            f"avoid={', '.join(payload['avoid_angles'][:2]) or 'n/a'}."
        )
        existing = db.scalar(
            select(GmReflection)
            .where(
                GmReflection.feedback_import_id == import_record.id,
                GmReflection.target_scope == target_scope,
                GmReflection.product_code == product_code if product_code else GmReflection.product_code.is_(None),
                GmReflection.industry_code == industry_code if industry_code else GmReflection.industry_code.is_(None),
                GmReflection.pipeline_mode == pipeline_mode if pipeline_mode else GmReflection.pipeline_mode.is_(None),
            )
            .limit(1)
        )
        reflection = _upsert_reflection(
            db,
            existing=existing,
            project_id=import_record.project_id,
            run_id=None,
            feedback_import_id=import_record.id,
            reflection_type="feedback_import",
            target_scope=target_scope,
            shop_id=shop_id,
            product_code=product_code,
            industry_code=industry_code,
            pipeline_mode=pipeline_mode,
            confidence_score=round(min(0.95, 0.55 + 0.04 * len(items)), 2),
            evidence_count=len(items),
            summary=summary,
            payload=payload,
        )
        reflections.append(reflection)
        build_candidate_policy(
            db,
            project_id=import_record.project_id,
            target_scope=target_scope,
            shop_id=shop_id,
            product_code=product_code,
            industry_code=industry_code,
            pipeline_mode=pipeline_mode,
        )
    return reflections


def promote_gm_policy(
    db: Session,
    *,
    policy_id: str,
    changed_by: str = "dashboard",
    notes: str | None = None,
) -> GmPolicyVersion:
    policy = db.get(GmPolicyVersion, policy_id)
    if not policy:
        raise ValueError("gm policy not found")
    policy = evaluate_gm_policy(db, policy_id)
    if policy.replay_status != "passed":
        raise ValueError("gm policy replay gate must pass before promotion")
    active_rows = db.scalars(
        select(GmPolicyVersion).where(
            *_policy_version_filters(
                project_id=policy.project_id,
                target_scope=policy.target_scope,
                shop_id=policy.shop_id,
                product_code=policy.product_code,
                industry_code=policy.industry_code,
                pipeline_mode=policy.pipeline_mode,
            ),
            GmPolicyVersion.status == "active",
        )
    ).all()
    for row in active_rows:
        row.status = "superseded"
        db.add(row)
    policy.status = "active"
    policy.activated_at = utcnow()
    if notes:
        policy.notes = notes
    db.add(policy)
    db.add(
        GmPolicyPromotion(
            project_id=policy.project_id,
            gm_policy_version_id=policy.id,
            action="promote",
            changed_by=changed_by,
            notes=notes,
        )
    )
    db.flush()
    return policy


def resolve_active_gm_policy(db: Session, run: PipelineRun, *, stage_name: str) -> dict:
    rows = db.scalars(
        select(GmPolicyVersion)
        .where(
            GmPolicyVersion.project_id == run.project_id,
            GmPolicyVersion.status == "active",
        )
        .order_by(desc(GmPolicyVersion.activated_at), desc(GmPolicyVersion.created_at))
    ).all()
    applicable: list[tuple[int, GmPolicyVersion]] = []
    for row in rows:
        if row.product_code and row.product_code != run.product_code:
            continue
        if row.industry_code and row.industry_code != run.industry_code:
            continue
        if row.shop_id and row.shop_id != run.workspace_id:
            continue
        if row.pipeline_mode and row.pipeline_mode != run.pipeline_mode:
            continue
        specificity = 0
        if row.shop_id:
            specificity += 4
        if row.product_code:
            specificity += 8
        if row.industry_code:
            specificity += 2
        if row.pipeline_mode:
            specificity += 2
        applicable.append((specificity, row))
    applicable.sort(key=lambda item: (item[0], item[1].activated_at or item[1].created_at), reverse=True)

    merged = {
        "policy_version_ids": [row.id for _, row in applicable[:3]],
        "applied_scopes": [row.target_scope for _, row in applicable[:3]],
        "stage_name": stage_name,
        "shop_thesis": {},
        "angle_priorities": [],
        "avoid_patterns": [],
        "hard_constraints": [],
        "selection_biases": [],
        "regeneration_rules": [],
        "evidence_digest": [],
    }
    for _, row in applicable[:3]:
        content = row.content or {}
        if not merged["shop_thesis"] and content.get("shop_thesis"):
            merged["shop_thesis"] = content.get("shop_thesis") or {}
        for key in ["angle_priorities", "avoid_patterns", "hard_constraints", "selection_biases", "regeneration_rules", "evidence_digest"]:
            merged[key].extend([str(item) for item in (content.get(key) or []) if str(item).strip()])
    for key in ["angle_priorities", "avoid_patterns", "hard_constraints", "selection_biases", "regeneration_rules", "evidence_digest"]:
        merged[key] = _dedupe_strings(merged[key])

    if stage_name == "planning":
        merged["stage_guidance"] = {
            "shop_thesis": merged["shop_thesis"],
            "angle_priorities": merged["angle_priorities"][:5],
            "hard_constraints": merged["hard_constraints"][:6],
            "evidence_digest": merged["evidence_digest"][:4],
        }
    elif stage_name == "divergence":
        merged["stage_guidance"] = {
            "angle_priorities": merged["angle_priorities"][:5],
            "avoid_patterns": merged["avoid_patterns"][:5],
            "selection_biases": merged["selection_biases"][:4],
        }
    elif stage_name == "visual_quality_assessment":
        merged["stage_guidance"] = {
            "hard_constraints": merged["hard_constraints"][:8],
            "regeneration_rules": merged["regeneration_rules"][:6],
            "avoid_patterns": merged["avoid_patterns"][:4],
        }
    elif stage_name == "evaluation_selection":
        merged["stage_guidance"] = {
            "selection_biases": merged["selection_biases"][:6],
            "avoid_patterns": merged["avoid_patterns"][:5],
            "regeneration_rules": merged["regeneration_rules"][:6],
        }
    else:
        merged["stage_guidance"] = {
            "angle_priorities": merged["angle_priorities"][:5],
            "hard_constraints": merged["hard_constraints"][:6],
        }
    return merged
