from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, Project, ResearchTask, Workspace


def utcnow() -> datetime:
    return datetime.now(UTC)


RESEARCH_MEMORY_TTL_DAYS = 60
RESEARCH_REFRESH_SOON_DAYS = 14
MIN_RESEARCH_SOURCE_QUALITY = 0.5
MIN_RESEARCH_AGGREGATE_QUALITY = 0.55
RESEARCH_CONFLICT_SIMILARITY_THRESHOLD = 0.72
RESEARCH_SOURCE_TYPES = [
    "shop_profile",
    "competitor_analysis",
    "industry_baseline",
    "audience_pain_points",
    "compliance_scan",
]


def _research_expires_at(generated_at: datetime) -> str:
    return (generated_at + timedelta(days=RESEARCH_MEMORY_TTL_DAYS)).isoformat()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def research_refresh_state(expires_at: str | None) -> str:
    parsed = _parse_iso_datetime(expires_at)
    if not parsed:
        return "unknown"
    now = utcnow()
    if parsed < now:
        return "expired"
    if parsed <= now + timedelta(days=RESEARCH_REFRESH_SOON_DAYS):
        return "refresh_soon"
    return "fresh"


def create_research_task(
    db: Session,
    *,
    project_id: str,
    shop_id: str | None,
    shop_name: str | None,
    store_url: str,
    industry_code: str,
    task_type: str,
    source: str = "manual",
    refresh_reason: str | None = None,
    payload: dict | None = None,
) -> ResearchTask:
    task = ResearchTask(
        project_id=project_id,
        shop_id=shop_id,
        shop_name=shop_name,
        store_url=store_url,
        industry_code=industry_code or "general",
        task_type=task_type or "full_intelligence",
        status="queued",
        source=source,
        refresh_reason=refresh_reason,
        payload=payload or {},
        memory_ids=[],
    )
    db.add(task)
    db.flush()
    return task


def mark_research_task_running(task: ResearchTask) -> None:
    task.status = "running"
    task.started_at = utcnow()


def mark_research_task_completed(task: ResearchTask, memory_ids: list[str]) -> None:
    task.status = "completed"
    task.memory_ids = memory_ids
    task.completed_at = utcnow()


def mark_research_task_failed(task: ResearchTask, error_message: str) -> None:
    task.status = "failed"
    task.error_message = error_message
    task.completed_at = utcnow()


def latest_research_task(
    db: Session,
    *,
    project_id: str,
    shop_id: str | None = None,
    store_url: str | None = None,
) -> ResearchTask | None:
    stmt = select(ResearchTask).where(ResearchTask.project_id == project_id)
    if shop_id:
        stmt = stmt.where(ResearchTask.shop_id == shop_id)
    if store_url:
        stmt = stmt.where(ResearchTask.store_url == store_url)
    return db.scalar(stmt.order_by(desc(ResearchTask.created_at)).limit(1))


def list_research_tasks(
    db: Session,
    *,
    project_id: str,
    shop_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    stmt = select(ResearchTask).where(ResearchTask.project_id == project_id)
    if shop_id:
        stmt = stmt.where(ResearchTask.shop_id == shop_id)
    rows = db.scalars(stmt.order_by(desc(ResearchTask.created_at)).limit(limit)).all()
    return [item for task in rows if (item := research_task_to_dict(task))]


def research_task_to_dict(task: ResearchTask | None) -> dict | None:
    if not task:
        return None
    return {
        "id": task.id,
        "project_id": task.project_id,
        "shop_id": task.shop_id,
        "shop_name": task.shop_name,
        "store_url": task.store_url,
        "industry_code": task.industry_code,
        "task_type": task.task_type,
        "status": task.status,
        "priority": task.priority,
        "source": task.source,
        "refresh_reason": task.refresh_reason,
        "memory_ids": task.memory_ids or [],
        "error_message": task.error_message,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }


def _evidence_for_store_url(store_url: str, *, source_type: str) -> list[dict]:
    return [
        {
            "source": source_type,
            "url": store_url,
            "summary": "Store URL used as the primary research source.",
            "fetched_at": utcnow().isoformat(),
        }
    ]


def _source_type_score(source: str) -> float:
    source = source.lower()
    if source == "firecrawl":
        return 0.72
    if source == "tavily":
        return 0.66
    if source in set(RESEARCH_SOURCE_TYPES):
        return 0.28
    return 0.36


def _freshness_score(fetched_at: str | None) -> float:
    parsed = _parse_iso_datetime(fetched_at)
    if not parsed:
        return 0.4
    age_days = max(0, (utcnow() - parsed).days)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.82
    if age_days <= 90:
        return 0.62
    return 0.35


def _provider_score(value) -> float:
    if not isinstance(value, int | float):
        return 0.5
    if value > 1:
        value = value / 100
    return max(0.0, min(1.0, float(value)))


def _evidence_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _score_evidence_item(item: dict) -> float:
    url = str(item.get("url") or "")
    summary = str(item.get("summary") or "")
    has_url = 1.0 if url.startswith(("http://", "https://")) else 0.0
    summary_score = min(1.0, len(summary) / 180) if summary else 0.0
    score = (
        0.32 * _source_type_score(str(item.get("source") or ""))
        + 0.16 * has_url
        + 0.22 * summary_score
        + 0.15 * _freshness_score(str(item.get("fetched_at") or ""))
        + 0.15 * _provider_score(item.get("score"))
    )
    if item.get("status", "ok") != "ok":
        score -= 0.25
    if not summary:
        score -= 0.1
    return round(max(0.0, min(1.0, score)), 2)


def _apply_evidence_quality(evidence: list[dict]) -> tuple[list[dict], dict]:
    domains = {_evidence_domain(str(item.get("url") or "")) for item in evidence}
    domains.discard("")
    sources = {str(item.get("source") or "") for item in evidence if item.get("status", "ok") == "ok"}
    corroboration = min(1.0, (len(domains) / 2) * 0.6 + (len(sources) / 2) * 0.4)
    scored: list[dict] = []
    for item in evidence:
        scored_item = dict(item)
        quality = _score_evidence_item(scored_item)
        if len(domains) >= 2 and scored_item.get("status", "ok") == "ok":
            quality = min(1.0, quality + 0.08)
        scored_item["quality_score"] = round(quality, 2)
        scored_item["quality_tier"] = (
            "high" if quality >= 0.75 else "medium" if quality > MIN_RESEARCH_SOURCE_QUALITY else "low"
        )
        scored.append(scored_item)
    ok_scores = [float(item["quality_score"]) for item in scored if item.get("status", "ok") == "ok"]
    aggregate = round(sum(ok_scores) / len(ok_scores), 2) if ok_scores else 0.0
    summary = {
        "aggregate_score": aggregate,
        "source_count": len(scored),
        "ok_source_count": len(ok_scores),
        "distinct_domain_count": len(domains),
        "distinct_source_count": len(sources),
        "corroboration_score": round(corroboration, 2),
        "quality_tier": "high" if aggregate >= 0.75 else "medium" if aggregate >= MIN_RESEARCH_AGGREGATE_QUALITY else "low",
    }
    return scored, summary


def _normalize_evidence(store_url: str, *, source_type: str, evidence: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or store_url)
        normalized.append({
            "source": str(item.get("source") or source_type),
            "url": url,
            "title": str(item.get("title") or ""),
            "summary": str(item.get("summary") or item.get("content") or "")[:500],
            "fetched_at": str(item.get("fetched_at") or utcnow().isoformat()),
            "status": str(item.get("status") or "ok"),
            "score": item.get("score"),
        })
    scored, _ = _apply_evidence_quality(normalized or _evidence_for_store_url(store_url, source_type=source_type))
    return scored


def _research_status(evidence: list[dict], search_errors: list[str] | None) -> str:
    errors = search_errors or []
    real_sources = [
        item
        for item in evidence
        if item.get("source") in {"tavily", "firecrawl"}
        and item.get("status") == "ok"
        and float(item.get("quality_score") or 0) >= MIN_RESEARCH_SOURCE_QUALITY
    ]
    _, quality = _apply_evidence_quality(evidence)
    if real_sources and quality["aggregate_score"] >= MIN_RESEARCH_AGGREGATE_QUALITY and not errors:
        return "complete"
    if real_sources:
        return "partial"
    if errors:
        return "degraded"
    return "fallback"


def _profile_summary(store_url: str, profile_data: dict) -> str:
    if isinstance(profile_data, dict):
        return str(profile_data.get("positioning") or profile_data.get("summary") or store_url)
    return store_url


def _profile_implications(profile_data: dict) -> list[str]:
    if not isinstance(profile_data, dict):
        return []
    implications: list[str] = []
    for item in profile_data.get("unique_selling_points") or []:
        implications.append(f"Emphasize differentiator: {item}")
    for item in profile_data.get("content_gaps") or []:
        implications.append(f"Test content gap: {item}")
    return implications[:8]


def _report_summary(store_url: str, report: str) -> str:
    text = " ".join(str(report or "").split())
    return text[:240] if text else f"Competitive research for {store_url}."


def _normalized_text(value) -> str:
    return " ".join(str(value or "").lower().split())


def _text_conflicts(previous, current, *, threshold: float = RESEARCH_CONFLICT_SIMILARITY_THRESHOLD) -> bool:
    previous_text = _normalized_text(previous)
    current_text = _normalized_text(current)
    if not previous_text or not current_text or previous_text == current_text:
        return False
    return SequenceMatcher(None, previous_text, current_text).ratio() < threshold


def _latest_prior_research_memory(
    db: Session,
    *,
    project_id: str,
    source_type: str,
    store_url: str,
    shop_id: str | None,
) -> GmMemory | None:
    rows = db.scalars(
        select(GmMemory)
        .where(
            GmMemory.project_id == project_id,
            GmMemory.source_type == source_type,
            GmMemory.memory_type == "research_intelligence",
            GmMemory.status == "active",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(20)
    ).all()
    for row in rows:
        content = row.content or {}
        if shop_id and content.get("shop_id") != shop_id:
            continue
        if content.get("store_url") != store_url:
            continue
        return row
    return None


def _research_conflict(
    *,
    field: str,
    previous_value,
    current_value,
    previous_memory_id: str,
    reason: str,
) -> dict | None:
    if not _text_conflicts(previous_value, current_value):
        return None
    return {
        "pattern_key": field,
        "field": field,
        "status": "unresolved",
        "conflict_type": "research_revision",
        "previous_memory_id": previous_memory_id,
        "previous_value": str(previous_value or "")[:240],
        "current_value": str(current_value or "")[:240],
        "reason": reason,
    }


def _detect_profile_conflicts(
    db: Session,
    *,
    project_id: str,
    store_url: str,
    shop_id: str | None,
    profile_data: dict,
) -> list[dict]:
    prior = _latest_prior_research_memory(
        db,
        project_id=project_id,
        source_type="shop_profile",
        store_url=store_url,
        shop_id=shop_id,
    )
    if not prior:
        return []
    previous_profile = (prior.content or {}).get("profile") or {}
    if not isinstance(previous_profile, dict) or not isinstance(profile_data, dict):
        return []
    checks = [
        ("profile.positioning", previous_profile.get("positioning"), profile_data.get("positioning")),
        ("profile.target_audience", previous_profile.get("target_audience"), profile_data.get("target_audience")),
    ]
    conflicts = [
        conflict
        for field, previous, current in checks
        if (conflict := _research_conflict(
            field=field,
            previous_value=previous,
            current_value=current,
            previous_memory_id=prior.id,
            reason="New store research materially differs from previous active store research.",
        ))
    ]
    return conflicts


def _detect_competitor_conflicts(
    db: Session,
    *,
    project_id: str,
    store_url: str,
    shop_id: str | None,
    analysis_markdown: str,
) -> list[dict]:
    prior = _latest_prior_research_memory(
        db,
        project_id=project_id,
        source_type="competitor_analysis",
        store_url=store_url,
        shop_id=shop_id,
    )
    if not prior:
        return []
    previous_summary = (prior.content or {}).get("summary") or _report_summary(store_url, (prior.content or {}).get("report", ""))
    current_summary = _report_summary(store_url, analysis_markdown)
    conflict = _research_conflict(
        field="competitor.summary",
        previous_value=previous_summary,
        current_value=current_summary,
        previous_memory_id=prior.id,
        reason="New competitor research materially differs from previous active competitor research.",
    )
    return [conflict] if conflict else []


def _detect_brief_conflicts(
    db: Session,
    *,
    project_id: str,
    source_type: str,
    store_url: str,
    shop_id: str | None,
    summary: str,
) -> list[dict]:
    prior = _latest_prior_research_memory(
        db,
        project_id=project_id,
        source_type=source_type,
        store_url=store_url,
        shop_id=shop_id,
    )
    if not prior:
        return []
    conflict = _research_conflict(
        field=f"{source_type}.summary",
        previous_value=(prior.content or {}).get("summary"),
        current_value=summary,
        previous_memory_id=prior.id,
        reason=f"New {source_type} research materially differs from previous active research.",
    )
    return [conflict] if conflict else []


def build_industry_baseline_brief(*, industry_code: str, store_url: str, profile_data: dict, competitor_report: str) -> dict:
    categories = profile_data.get("product_categories") if isinstance(profile_data, dict) else []
    categories = categories if isinstance(categories, list) else []
    positioning = profile_data.get("positioning") if isinstance(profile_data, dict) else ""
    summary = f"{industry_code or 'general'} baseline for {store_url}: {positioning or 'category context'}"
    category_text = ", ".join(str(item) for item in categories[:5]) or "unknown category"
    return {
        "summary": summary,
        "findings": {
            "industry_code": industry_code or "general",
            "category_context": category_text,
            "positioning_reference": positioning,
            "competitive_context": _report_summary(store_url, competitor_report),
        },
        "strategic_implications": [
            f"Benchmark creative angles against {category_text}.",
            "Separate store-specific claims from broader category assumptions.",
            "Refresh this baseline when category, pricing, or competitor set changes.",
        ],
    }


def build_audience_pain_points_brief(*, store_url: str, profile_data: dict, competitor_report: str) -> dict:
    target = profile_data.get("target_audience") if isinstance(profile_data, dict) else ""
    gaps = profile_data.get("content_gaps") if isinstance(profile_data, dict) else []
    gaps = gaps if isinstance(gaps, list) else []
    summary = f"Audience pain point research for {target or store_url}."
    pain_points = [str(item) for item in gaps[:5]] or [
        "Need stronger proof for the primary promise.",
        "Need clearer objection handling before conversion.",
    ]
    return {
        "summary": summary,
        "findings": {
            "target_audience": target,
            "pain_points": pain_points,
            "competitive_context": _report_summary(store_url, competitor_report),
        },
        "strategic_implications": [
            f"Turn audience objection into hook: {pain_points[0]}",
            "Use review/community evidence before treating pain points as proven.",
        ],
    }


def build_compliance_scan_brief(*, store_url: str, profile_data: dict, competitor_report: str) -> dict:
    usps = profile_data.get("unique_selling_points") if isinstance(profile_data, dict) else []
    usps = usps if isinstance(usps, list) else []
    sensitive_terms = ["guarantee", "cure", "prevent", "medical", "safe", "best", "only", "never"]
    text = " ".join([str(item) for item in usps] + [competitor_report]).lower()
    flagged_terms = sorted({term for term in sensitive_terms if term in text})
    summary = f"Compliance scan for {store_url}: {'review required' if flagged_terms else 'no obvious high-risk terms'}."
    return {
        "summary": summary,
        "findings": {
            "flagged_terms": flagged_terms,
            "claims_to_verify": [str(item) for item in usps[:8]],
            "scan_scope": "store profile claims and competitor research summary",
        },
        "strategic_implications": [
            "Keep claim-heavy hooks behind evidence review before generation.",
            "Use softer comparative language unless the claim is backed by product proof.",
        ],
    }


def _get_or_create_workspace_project(
    db: Session, workspace_name: str, project_name: str
) -> tuple[Workspace, Project]:
    workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if not workspace:
        workspace = Workspace(name=workspace_name)
        db.add(workspace)
        db.flush()
    project = db.scalar(
        select(Project).where(
            Project.workspace_id == workspace.id, Project.name == project_name
        )
    )
    if not project:
        project = Project(workspace_id=workspace.id, name=project_name)
        db.add(project)
        db.flush()
    return workspace, project


def save_shop_profile(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    profile_data: dict,
    evidence: list[dict] | None = None,
    source_queries: list[str] | None = None,
    search_errors: list[str] | None = None,
    shop_id: str | None = None,
    shop_name: str | None = None,
    research_focus: str = "full_intelligence",
) -> GmMemory:
    generated_at = utcnow()
    normalized_evidence = _normalize_evidence(store_url, source_type="shop_profile", evidence=evidence)
    _, evidence_quality = _apply_evidence_quality(normalized_evidence)
    status = _research_status(normalized_evidence, search_errors)
    conflicts = _detect_profile_conflicts(
        db,
        project_id=project_id,
        store_url=store_url,
        shop_id=shop_id,
        profile_data=profile_data,
    )
    entry = GmMemory(
        project_id=project_id,
        memory_scope="shop" if shop_id else "industry",
        industry_code=industry_code,
        source_type="shop_profile",
        memory_type="research_intelligence",
        score_hint=0.7 if status == "complete" else 0.6,
        content={
            "source": "shop_profile",
            "research_focus": research_focus,
            "scope": "shop" if shop_id else "industry",
            "shop_id": shop_id,
            "shop_name": shop_name,
            "store_url": store_url,
            "profile": profile_data,
            "summary": _profile_summary(store_url, profile_data),
            "findings": profile_data if isinstance(profile_data, dict) else {"raw_profile": profile_data},
            "strategic_implications": _profile_implications(profile_data),
            "evidence": normalized_evidence,
            "evidence_quality": evidence_quality,
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "source_queries": source_queries or [f"{store_url} brand positioning target audience product catalog"],
            "search_errors": search_errors or [],
            "research_status": status,
            "metric_window": {"start": generated_at.date().isoformat(), "end": generated_at.date().isoformat()},
            "confidence": 0.72 if status == "complete" else 0.6,
            "generated_at": generated_at.isoformat(),
            "expires_at": _research_expires_at(generated_at),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def save_competitor_analysis(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    analysis_markdown: str,
    evidence: list[dict] | None = None,
    source_queries: list[str] | None = None,
    search_errors: list[str] | None = None,
    shop_id: str | None = None,
    shop_name: str | None = None,
    research_focus: str = "full_intelligence",
) -> GmMemory:
    generated_at = utcnow()
    normalized_evidence = _normalize_evidence(store_url, source_type="competitor_analysis", evidence=evidence)
    _, evidence_quality = _apply_evidence_quality(normalized_evidence)
    status = _research_status(normalized_evidence, search_errors)
    conflicts = _detect_competitor_conflicts(
        db,
        project_id=project_id,
        store_url=store_url,
        shop_id=shop_id,
        analysis_markdown=analysis_markdown,
    )
    entry = GmMemory(
        project_id=project_id,
        memory_scope="shop" if shop_id else "industry",
        industry_code=industry_code,
        source_type="competitor_analysis",
        memory_type="research_intelligence",
        score_hint=0.68 if status == "complete" else 0.58,
        content={
            "source": "competitor_analysis",
            "research_focus": research_focus,
            "scope": "shop" if shop_id else "industry",
            "shop_id": shop_id,
            "shop_name": shop_name,
            "store_url": store_url,
            "report": analysis_markdown,
            "summary": _report_summary(store_url, analysis_markdown),
            "findings": {"report": analysis_markdown},
            "strategic_implications": [_report_summary(store_url, analysis_markdown)],
            "evidence": normalized_evidence,
            "evidence_quality": evidence_quality,
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "source_queries": source_queries or [f"competitors similar to {store_url} online store positioning creative patterns"],
            "search_errors": search_errors or [],
            "research_status": status,
            "metric_window": {"start": generated_at.date().isoformat(), "end": generated_at.date().isoformat()},
            "confidence": 0.68 if status == "complete" else 0.58,
            "generated_at": generated_at.isoformat(),
            "expires_at": _research_expires_at(generated_at),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def save_research_brief(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    source_type: str,
    brief: dict,
    evidence: list[dict] | None = None,
    source_queries: list[str] | None = None,
    search_errors: list[str] | None = None,
    shop_id: str | None = None,
    shop_name: str | None = None,
    research_focus: str = "full_intelligence",
) -> GmMemory:
    generated_at = utcnow()
    normalized_evidence = _normalize_evidence(store_url, source_type=source_type, evidence=evidence)
    _, evidence_quality = _apply_evidence_quality(normalized_evidence)
    status = _research_status(normalized_evidence, search_errors)
    summary = str(brief.get("summary") or f"{source_type} research for {store_url}.")
    conflicts = _detect_brief_conflicts(
        db,
        project_id=project_id,
        source_type=source_type,
        store_url=store_url,
        shop_id=shop_id,
        summary=summary,
    )
    entry = GmMemory(
        project_id=project_id,
        memory_scope="shop" if shop_id else "industry",
        industry_code=industry_code,
        source_type=source_type,
        memory_type="research_intelligence",
        score_hint=0.66 if status == "complete" else 0.56,
        content={
            "source": source_type,
            "research_focus": research_focus,
            "scope": "shop" if shop_id else "industry",
            "shop_id": shop_id,
            "shop_name": shop_name,
            "store_url": store_url,
            "summary": summary,
            "findings": brief.get("findings") or {},
            "strategic_implications": brief.get("strategic_implications") or [],
            "evidence": normalized_evidence,
            "evidence_quality": evidence_quality,
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "source_queries": source_queries or [f"{source_type} research for {store_url}"],
            "search_errors": search_errors or [],
            "research_status": status,
            "metric_window": {"start": generated_at.date().isoformat(), "end": generated_at.date().isoformat()},
            "confidence": 0.66 if status == "complete" else 0.56,
            "generated_at": generated_at.isoformat(),
            "expires_at": _research_expires_at(generated_at),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def list_shop_analyses(
    db: Session,
    project_id: str,
    limit: int = 20,
    shop_id: str | None = None,
) -> list[dict]:
    stmt = (
        select(GmMemory)
        .where(GmMemory.source_type.in_(RESEARCH_SOURCE_TYPES))
        .order_by(desc(GmMemory.created_at))
        .limit(limit * 3 if shop_id else limit)
    )
    if shop_id:
        stmt = stmt.where(GmMemory.memory_scope == "shop")
    else:
        stmt = stmt.where(GmMemory.project_id == project_id)
    rows = db.scalars(stmt).all()

    result: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if shop_id and (row.content or {}).get("shop_id") != shop_id:
            continue
        store_url = (row.content or {}).get("store_url", "")
        batch_key = f"{store_url}|{row.source_type}"
        if batch_key in seen:
            continue
        seen.add(batch_key)
        summary = ""
        if row.source_type == "shop_profile":
            profile = (row.content or {}).get("profile", {})
            summary = profile.get("positioning", store_url) if isinstance(profile, dict) else store_url
        elif row.source_type == "competitor_analysis":
            report = (row.content or {}).get("report", "")
            summary = (report[:80] + "...") if len(report) > 80 else report
        else:
            summary = str((row.content or {}).get("summary") or row.source_type)
        latest_task = latest_research_task(
            db,
            project_id=project_id,
            shop_id=(row.content or {}).get("shop_id"),
            store_url=store_url,
        )
        expires_at = (row.content or {}).get("expires_at")
        result.append({
            "id": row.id,
            "store_url": store_url,
            "industry_code": row.industry_code or "",
            "status": "completed",
            "source_type": row.source_type,
            "memory_type": row.memory_type,
            "research_focus": (row.content or {}).get("research_focus") or "full_intelligence",
            "research_status": (row.content or {}).get("research_status") or "unknown",
            "evidence_count": len((row.content or {}).get("evidence") or []),
            "evidence_quality": (row.content or {}).get("evidence_quality") or {},
            "conflict_count": len((row.content or {}).get("conflicts") or []),
            "expires_at": expires_at,
            "refresh_state": research_refresh_state(expires_at),
            "latest_task": research_task_to_dict(latest_task),
            "summary": summary,
            "created_at": row.created_at,
        })
        if len(result) >= limit:
            break
    return result


def get_shop_analysis_pair(
    db: Session,
    industry_code: str,
    store_url: str,
) -> dict:
    """Get the most recent shop_profile and competitor_analysis for a store."""
    profile = db.scalar(
        select(GmMemory)
        .where(
            GmMemory.industry_code == industry_code,
            GmMemory.source_type == "shop_profile",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(1)
    )
    competitor = db.scalar(
        select(GmMemory)
        .where(
            GmMemory.industry_code == industry_code,
            GmMemory.source_type == "competitor_analysis",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(1)
    )
    # Filter by store_url in content JSON (post-query)
    profile_content = profile.content if profile and (profile.content or {}).get("store_url") == store_url else None
    competitor_content = competitor.content if competitor and (competitor.content or {}).get("store_url") == store_url else None
    return {
        "profile_content": profile_content,
        "competitor_content": competitor_content,
    }
