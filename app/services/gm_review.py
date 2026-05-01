from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.runtime import AgentsRuntime
from app.data.models import (
    AgentTraceEvent,
    GmPolicyVersion,
    GmReflection,
    PerformanceSnapshot,
    PipelineRun,
    Project,
    RunVariant,
    ScoreCard as ScoreCardModel,
    VariantScore,
    Workspace,
)
from app.services.agent_api_configs import resolve_agent_config, resolve_agent_runtime

runtime = AgentsRuntime()


def utcnow() -> datetime:
    return datetime.now(UTC)


def _get_workspace_project(db: Session, workspace_name: str, project_name: str) -> tuple[Workspace, Project]:
    workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if not workspace:
        raise ValueError("Workspace not found")
    project = db.scalar(
        select(Project).where(Project.workspace_id == workspace.id, Project.name == project_name)
    )
    if not project:
        raise ValueError("Project not found")
    return workspace, project


def _time_window(*, days: int, date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    if date_from:
        start = datetime.combine(date_from, time.min, tzinfo=UTC)
    else:
        base_end = datetime.combine(date_to, time.max, tzinfo=UTC) if date_to else utcnow()
        start = base_end - timedelta(days=max(days, 1))

    if date_to:
        end = datetime.combine(date_to, time.max, tzinfo=UTC)
    else:
        end = utcnow()

    if end < start:
        start, end = end, start
    return start, end


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


def _serialize_policy(row: GmPolicyVersion) -> dict:
    return {
        "id": row.id,
        "version": row.version,
        "status": row.status,
        "target_scope": row.target_scope,
        "shop_id": row.shop_id,
        "product_code": row.product_code,
        "industry_code": row.industry_code,
        "pipeline_mode": row.pipeline_mode,
        "confidence_score": row.confidence_score,
        "evidence_count": row.evidence_count,
        "replay_status": row.replay_status,
        "replay_score": row.replay_score,
        "replay_summary": row.replay_summary,
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "created_at": row.created_at.isoformat(),
    }


def _serialize_reflection(row: GmReflection) -> dict:
    return {
        "id": row.id,
        "reflection_type": row.reflection_type,
        "target_scope": row.target_scope,
        "product_code": row.product_code,
        "industry_code": row.industry_code,
        "pipeline_mode": row.pipeline_mode,
        "summary": row.summary,
        "evidence_count": row.evidence_count,
        "confidence_score": row.confidence_score,
        "created_at": row.created_at.isoformat(),
    }


def _narrative_from_summary(db: Session, summary: dict, *, latest_run: PipelineRun | None) -> tuple[str, str]:
    resolved = resolve_agent_config(
        db,
        agent_name="gm_orchestrator",
        run_provider=(latest_run.model_provider if latest_run else "openai"),
        run_model=(latest_run.model_name if latest_run else "gpt-4.1"),
    )
    if not resolved.get("api_key_available"):
        return "", "unavailable"
    runtime_config = resolve_agent_runtime(resolved)
    prompt = (
        "You are the GM orchestrator writing a concise operating review for an ecommerce operator. "
        "Use only the provided summary facts. Do not invent metrics or recommendations beyond the facts. "
        "Write 3-6 sentences in a direct management tone.\n"
        f"summary_json={summary}"
    )
    try:
        narrative, _, _ = runtime._chat_complete(
            resolved["provider_name"],
            resolved["model_name"],
            prompt,
            runtime_config,
        )
    except Exception:
        return "", "unavailable"
    return narrative.strip(), "available"


def _policy_matches(
    row: GmPolicyVersion,
    *,
    workspace_id: str,
    industry_codes: set[str],
    pipeline_mode: str | None,
    product_code: str | None,
) -> bool:
    if row.pipeline_mode and pipeline_mode and row.pipeline_mode != pipeline_mode:
        return False
    if product_code:
        if row.product_code == product_code:
            return True
        if row.shop_id and row.shop_id == workspace_id:
            return True
        if row.industry_code and row.industry_code in industry_codes:
            return True
        return False
    return True


def build_gm_review_summary(
    db: Session,
    *,
    workspace_name: str,
    project_name: str,
    days: int = 7,
    date_from: date | None = None,
    date_to: date | None = None,
    pipeline_mode: str | None = None,
    product_code: str | None = None,
    include_narrative: bool = True,
) -> dict:
    workspace, project = _get_workspace_project(db, workspace_name, project_name)
    start_at, end_at = _time_window(days=days, date_from=date_from, date_to=date_to)

    run_query = select(PipelineRun).where(
        PipelineRun.project_id == project.id,
        PipelineRun.created_at >= start_at,
        PipelineRun.created_at <= end_at,
    )
    if pipeline_mode:
        run_query = run_query.where(PipelineRun.pipeline_mode == pipeline_mode)
    if product_code:
        run_query = run_query.where(PipelineRun.product_code == product_code)
    runs = db.scalars(run_query.order_by(desc(PipelineRun.created_at))).all()
    run_ids = [row.id for row in runs]
    run_id_set = set(run_ids)
    industry_codes = {row.industry_code for row in runs if row.industry_code}

    variants = (
        db.scalars(select(RunVariant).where(RunVariant.run_id.in_(run_ids)).order_by(desc(RunVariant.created_at))).all()
        if run_ids
        else []
    )
    variant_id_set = {row.id for row in variants}
    score_rows = (
        db.scalars(select(VariantScore).where(VariantScore.run_variant_id.in_(variant_id_set))).all()
        if variant_id_set
        else []
    )

    scorecards = (
        db.scalars(select(ScoreCardModel).where(ScoreCardModel.run_id.in_(run_ids)).order_by(desc(ScoreCardModel.created_at))).all()
        if run_ids
        else []
    )
    latest_scorecards: dict[str, ScoreCardModel] = {}
    for row in scorecards:
        latest_scorecards.setdefault(row.run_id, row)

    reflection_query = select(GmReflection).where(
        GmReflection.project_id == project.id,
        GmReflection.created_at >= start_at,
        GmReflection.created_at <= end_at,
    )
    if pipeline_mode:
        reflection_query = reflection_query.where(
            (GmReflection.pipeline_mode == pipeline_mode) | GmReflection.pipeline_mode.is_(None)
        )
    if product_code:
        if industry_codes:
            reflection_query = reflection_query.where(
                (GmReflection.product_code == product_code)
                | (
                    GmReflection.product_code.is_(None)
                    & (
                        (GmReflection.shop_id == workspace.id)
                        | GmReflection.industry_code.in_(industry_codes)
                    )
                )
            )
        else:
            reflection_query = reflection_query.where(GmReflection.product_code == product_code)
    reflections = db.scalars(reflection_query.order_by(desc(GmReflection.created_at)).limit(60)).all()

    policy_rows = db.scalars(
        select(GmPolicyVersion)
        .where(GmPolicyVersion.project_id == project.id)
        .order_by(desc(GmPolicyVersion.activated_at), desc(GmPolicyVersion.created_at))
    ).all()
    policies = [
        row for row in policy_rows
        if _policy_matches(
            row,
            workspace_id=workspace.id,
            industry_codes=industry_codes,
            pipeline_mode=pipeline_mode,
            product_code=product_code,
        )
    ]
    active_policies = [_serialize_policy(row) for row in policies if row.status == "active"][:5]
    candidate_policies = [_serialize_policy(row) for row in policies if row.status == "candidate"][:6]

    snapshots_query = select(PerformanceSnapshot).where(
        PerformanceSnapshot.project_id == project.id,
        PerformanceSnapshot.created_at >= start_at,
        PerformanceSnapshot.created_at <= end_at,
    )
    if run_ids:
        snapshots_query = snapshots_query.where(PerformanceSnapshot.run_id.in_(run_ids))
    elif product_code:
        snapshots_query = snapshots_query.where(PerformanceSnapshot.run_id.is_(None))
    snapshots = db.scalars(snapshots_query.order_by(desc(PerformanceSnapshot.created_at)).limit(200)).all()

    trace_events = (
        db.scalars(
            select(AgentTraceEvent)
            .where(AgentTraceEvent.run_id.in_(run_ids))
            .order_by(desc(AgentTraceEvent.created_at))
            .limit(200)
        ).all()
        if run_ids
        else []
    )

    pipeline_mode_counts = Counter(row.pipeline_mode for row in runs if row.pipeline_mode)
    winner_count = sum(1 for row in variants if row.is_winner)
    shortlisted_count = sum(1 for row in variants if row.shortlisted)
    regen_request_count = sum(1 for row in variants if row.regenerate_requested)
    manual_review_pressure_count = sum(
        1
        for row in variants
        if row.review_status in {"manual_review", "wait_for_asset", "request_regeneration", "rejected"}
        or row.status in {"needs_regeneration", "rejected"}
    )
    average_scorecard = round(
        sum(card.total_score for card in latest_scorecards.values()) / len(latest_scorecards),
        2,
    ) if latest_scorecards else None

    winning_angles = Counter()
    avoid_patterns = Counter()
    hard_constraints = Counter()
    regen_reasons = Counter()
    for row in reflections:
        payload = row.payload or {}
        winning_angles.update(str(item) for item in (payload.get("winning_angles") or []) if str(item).strip())
        avoid_patterns.update(str(item) for item in (payload.get("avoid_angles") or []) if str(item).strip())
        hard_constraints.update(str(item) for item in (payload.get("hard_constraints") or []) if str(item).strip())
        regen_reasons.update(str(item) for item in (payload.get("regeneration_rules") or []) if str(item).strip())

    replay_status_counts = Counter(item["replay_status"] for item in active_policies + candidate_policies if item.get("replay_status"))
    recent_policy_events = []
    for row in policies[:10]:
        event_type = "active_policy" if row.status == "active" else "candidate_policy"
        if row.status == "candidate" and row.replay_status != "passed":
            event_type = "blocked_candidate"
        recent_policy_events.append({
            "policy_id": row.id,
            "event_type": event_type,
            "summary": row.replay_summary or f"Policy v{row.version} {row.status}.",
            "created_at": (row.activated_at or row.created_at).isoformat(),
        })

    snapshot_totals = {
        "snapshot_count": len(snapshots),
        "total_spend": round(sum(float((row.metrics or {}).get("spend", 0)) for row in snapshots), 2),
        "total_revenue": round(sum(float((row.metrics or {}).get("revenue", 0)) for row in snapshots), 2),
        "total_clicks": sum(int((row.metrics or {}).get("clicks", 0)) for row in snapshots),
        "total_impressions": sum(int((row.metrics or {}).get("impressions", 0)) for row in snapshots),
    }
    snapshot_totals["overall_roas"] = round(
        snapshot_totals["total_revenue"] / snapshot_totals["total_spend"], 4
    ) if snapshot_totals["total_spend"] > 0 else 0
    snapshot_totals["overall_ctr"] = round(
        snapshot_totals["total_clicks"] / snapshot_totals["total_impressions"] * 100, 4
    ) if snapshot_totals["total_impressions"] > 0 else 0

    leaderboard_map: dict[str, dict] = defaultdict(lambda: {"weighted_sum": 0.0, "count": 0})
    trend_map: dict[str, list[float]] = defaultdict(list)
    for row in snapshots:
        item = leaderboard_map[row.creative_key]
        item["weighted_sum"] += float(row.weighted_score or 0)
        item["count"] += 1
        trend_map[row.created_at.date().isoformat()].append(float(row.weighted_score or 0))
    leaderboard = [
        {
            "creative_key": key,
            "weighted_score": round(item["weighted_sum"] / max(1, item["count"]), 2),
            "count": item["count"],
        }
        for key, item in leaderboard_map.items()
    ]
    leaderboard.sort(key=lambda item: item["weighted_score"], reverse=True)
    score_trend = [
        {"date": day, "avg_weighted_score": round(sum(values) / len(values), 2)}
        for day, values in sorted(trend_map.items())
    ]

    insufficient_data_flags: list[str] = []
    if not runs:
        insufficient_data_flags.append("no_runs_in_window")
    if not reflections:
        insufficient_data_flags.append("no_reflections_in_window")
    if not snapshots:
        insufficient_data_flags.append("no_performance_snapshots")
    if not latest_scorecards:
        insufficient_data_flags.append("no_scorecards")
    if not trace_events:
        insufficient_data_flags.append("no_trace_events")

    evidence_refs = _dedupe_strings(
        [f"run:{row.id}" for row in runs[:5]]
        + [f"reflection:{row.id}" for row in reflections[:8]]
        + [f"policy:{row.id}" for row in policies[:6]]
    )

    action_list: list[dict] = []
    if winning_angles:
        top_angle = winning_angles.most_common(1)[0][0]
        action_list.append({
            "title": f"继续放大角度：{top_angle}",
            "rationale": f"近期 reflections 多次把 `{top_angle}` 标记为 winning angle，适合在下一轮 planning 中继续优先测试。",
            "evidence_refs": evidence_refs[:3],
        })
    if avoid_patterns:
        top_avoid = avoid_patterns.most_common(1)[0][0]
        action_list.append({
            "title": f"暂停弱角度：{top_avoid}",
            "rationale": f"`{top_avoid}` 在最近复盘中反复进入 avoid patterns，建议减少预算和生成配额。",
            "evidence_refs": evidence_refs[:3],
        })
    if hard_constraints:
        top_constraint = hard_constraints.most_common(1)[0][0]
        action_list.append({
            "title": f"强化人工复核：{top_constraint}",
            "rationale": f"`{top_constraint}` 是最近最常见的 hard constraint，说明 QA 和 reviewer 需要优先盯这个问题。",
            "evidence_refs": evidence_refs[2:6],
        })
    blocked_candidates = [item for item in candidate_policies if item.get("replay_status") != "passed"]
    if blocked_candidates:
        action_list.append({
            "title": "复查被 Gate 拦下的 candidate policy",
            "rationale": f"当前有 {len(blocked_candidates)} 个 candidate policy 未通过 replay gate，适合人工判断是证据不足还是策略质量问题。",
            "evidence_refs": [f"policy:{item['id']}" for item in blocked_candidates[:3]],
        })
    if manual_review_pressure_count > 0:
        action_list.append({
            "title": "降低手工审核压力",
            "rationale": f"当前窗口有 {manual_review_pressure_count} 个变体处于人工关注状态，建议优先清理最常见的 regen/QA 原因。",
            "evidence_refs": evidence_refs[:4],
        })
    if not action_list:
        action_list.append({
            "title": "继续观察当前 GM 学习循环",
            "rationale": "当前窗口内可用信号不足，建议先积累更多运行和反馈数据，再判断是否需要调策略。",
            "evidence_refs": evidence_refs[:3],
        })

    headline = (
        f"{max(days, 1)}d GM review: {len(runs)} runs, "
        f"{len(active_policies)} active policies, {winner_count} winners."
    )
    executive_summary = {
        "headline": headline,
        "narrative": "",
        "narrative_status": "disabled" if not include_narrative else "pending",
    }

    summary = {
        "scope": {
            "workspace_name": workspace_name,
            "project_name": project_name,
            "days": days,
            "date_from": start_at.date().isoformat(),
            "date_to": end_at.date().isoformat(),
            "pipeline_mode": pipeline_mode,
            "product_code": product_code,
        },
        "executive_summary": executive_summary,
        "operating_snapshot": {
            "run_count": len(runs),
            "pipeline_mode_counts": dict(pipeline_mode_counts),
            "winner_count": winner_count,
            "shortlisted_count": shortlisted_count,
            "regen_request_count": regen_request_count,
            "manual_review_pressure_count": manual_review_pressure_count,
            "manual_review_pressure_rate": round(manual_review_pressure_count / max(1, len(variants)), 4),
            "average_scorecard": average_scorecard,
        },
        "learning_snapshot": {
            "top_winning_angles": [item for item, _ in winning_angles.most_common(5)],
            "top_avoid_patterns": [item for item, _ in avoid_patterns.most_common(5)],
            "top_hard_constraints": [item for item, _ in hard_constraints.most_common(6)],
            "top_regen_reasons": [item for item, _ in regen_reasons.most_common(6)],
            "recent_reflections": [_serialize_reflection(row) for row in reflections[:8]],
        },
        "policy_board": {
            "active_policies": active_policies,
            "candidate_policies": candidate_policies,
            "replay_status_counts": dict(replay_status_counts),
            "recent_policy_events": recent_policy_events[:8],
        },
        "business_signals": {
            "leaderboard": leaderboard[:5],
            "score_trend": score_trend[-14:],
            "performance_summary": snapshot_totals,
            "trace_event_count": len(trace_events),
            "insufficient_data_flags": insufficient_data_flags,
        },
        "action_list": action_list[:5],
        "evidence_refs": evidence_refs[:16],
    }

    if include_narrative:
        latest_run = runs[0] if runs else None
        narrative, status = _narrative_from_summary(db, summary, latest_run=latest_run)
        summary["executive_summary"]["narrative"] = narrative
        summary["executive_summary"]["narrative_status"] = status
    return summary


def render_gm_review_markdown(summary: dict) -> str:
    scope = summary["scope"]
    executive = summary["executive_summary"]
    operating = summary["operating_snapshot"]
    learning = summary["learning_snapshot"]
    policy_board = summary["policy_board"]
    business = summary["business_signals"]
    lines = [
        f"# GM Review Console",
        "",
        f"- Workspace: `{scope['workspace_name']}`",
        f"- Project: `{scope['project_name']}`",
        f"- Window: `{scope['date_from']}` -> `{scope['date_to']}`",
        f"- Pipeline mode: `{scope['pipeline_mode'] or 'all'}`",
        f"- Product: `{scope['product_code'] or 'all'}`",
        "",
        "## Executive Summary",
        "",
        executive["headline"],
        "",
    ]
    if executive.get("narrative"):
        lines.extend([executive["narrative"], ""])

    lines.extend([
        "## Operating Snapshot",
        "",
        f"- Runs: {operating['run_count']}",
        f"- Winners: {operating['winner_count']}",
        f"- Shortlisted: {operating['shortlisted_count']}",
        f"- Regen requests: {operating['regen_request_count']}",
        f"- Manual review pressure: {operating['manual_review_pressure_count']} ({operating['manual_review_pressure_rate']:.2%})",
        f"- Average scorecard: {operating['average_scorecard'] if operating['average_scorecard'] is not None else 'n/a'}",
        "",
        "## Learning Snapshot",
        "",
        f"- Top winning angles: {', '.join(learning['top_winning_angles']) or 'n/a'}",
        f"- Top avoid patterns: {', '.join(learning['top_avoid_patterns']) or 'n/a'}",
        f"- Top hard constraints: {', '.join(learning['top_hard_constraints']) or 'n/a'}",
        f"- Top regen reasons: {', '.join(learning['top_regen_reasons']) or 'n/a'}",
        "",
        "## Policy Board",
        "",
        f"- Active policies: {len(policy_board['active_policies'])}",
        f"- Candidate policies: {len(policy_board['candidate_policies'])}",
        f"- Replay status counts: {policy_board['replay_status_counts'] or {}}",
        "",
        "## Business Signals",
        "",
        f"- Performance summary: {business['performance_summary']}",
        f"- Insufficient data flags: {', '.join(business['insufficient_data_flags']) or 'none'}",
        "",
        "## GM Action List",
        "",
    ])
    for item in summary["action_list"]:
        lines.append(f"- {item['title']}: {item['rationale']}")
    lines.extend(["", "## Evidence Refs", ""])
    for item in summary["evidence_refs"]:
        lines.append(f"- {item}")
    return "\n".join(lines).strip() + "\n"
