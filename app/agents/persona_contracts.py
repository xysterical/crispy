from __future__ import annotations

import hashlib
import json
import re


SECTION_ALIASES: dict[str, str] = {
    "mission": "mission",
    "operating standard": "mission",
    "responsibilities": "responsibilities",
    "must output": "must_output",
    "required outputs": "must_output",
    "cannot do": "cannot_do",
    "inputs": "inputs",
    "review questions": "review_questions",
    "reviewer checklist": "review_questions",
    "handoff in": "handoff_in",
    "handoff out": "handoff_out",
    "verification": "verification",
    "decision rules": "responsibilities",
}

SECTION_LABELS: dict[str, str] = {
    "mission": "Mission",
    "responsibilities": "Responsibilities",
    "must_output": "Must Output",
    "cannot_do": "Cannot Do",
    "inputs": "Inputs",
    "review_questions": "Review Questions",
    "handoff_in": "Handoff In",
    "handoff_out": "Handoff Out",
    "verification": "Verification",
}

LIST_FIELDS = {
    "responsibilities",
    "must_output",
    "cannot_do",
    "inputs",
    "review_questions",
    "handoff_in",
    "handoff_out",
    "verification",
}


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _parse_block_lines(lines: list[str], *, list_mode: bool) -> str | list[str]:
    cleaned = [line.rstrip() for line in lines]
    if list_mode:
        items: list[str] = []
        for line in cleaned:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(("- ", "* ")):
                items.append(stripped[2:].strip())
            else:
                items.append(stripped)
        return items
    return "\n".join(line.strip() for line in cleaned if line.strip()).strip()


def parse_persona_contract(content: str) -> dict:
    contract = {
        "title": "",
        "mission": "",
        "responsibilities": [],
        "must_output": [],
        "cannot_do": [],
        "inputs": [],
        "review_questions": [],
        "handoff_in": [],
        "handoff_out": [],
        "verification": [],
        "additional_guidance": "",
    }
    current_heading: str | None = None
    current_lines: list[str] = []
    additional_blocks: list[str] = []
    preamble_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_heading, current_lines
        if current_heading is None:
            current_lines = []
            return
        normalized = _normalize_heading(current_heading)
        field_name = SECTION_ALIASES.get(normalized)
        if field_name:
            contract[field_name] = _parse_block_lines(current_lines, list_mode=field_name in LIST_FIELDS)
        else:
            block_text = "\n".join([f"## {current_heading}", *current_lines]).strip()
            if block_text:
                additional_blocks.append(block_text)
        current_heading = None
        current_lines = []

    for raw_line in content.splitlines():
        if raw_line.startswith("# "):
            if not contract["title"]:
                contract["title"] = raw_line[2:].strip()
                continue
        if raw_line.startswith("## "):
            flush_current()
            current_heading = raw_line[3:].strip()
            continue
        if current_heading is None:
            if raw_line.strip():
                preamble_lines.append(raw_line.rstrip())
            continue
        current_lines.append(raw_line)

    flush_current()
    if preamble_lines:
        additional_blocks.insert(0, "\n".join(line for line in preamble_lines if line).strip())
    contract["additional_guidance"] = "\n\n".join(block for block in additional_blocks if block).strip()
    return contract


def compile_persona_snapshot(*, agent_name: str, version: int, source_path: str, content: str) -> dict:
    contract = parse_persona_contract(content)
    section_names = [
        SECTION_LABELS[field_name]
        for field_name in SECTION_LABELS
        if contract.get(field_name)
    ]
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "agent_name": agent_name,
        "title": contract["title"] or agent_name,
        "version": version,
        "source_path": source_path,
        "section_names": section_names,
        "sha256": digest,
        "contract": contract,
    }


def build_compiled_persona(*, persona_snapshots: dict, lead_agent: str, collaborators: list[str]) -> dict:
    lead_snapshot = persona_snapshots[lead_agent]
    lead = compile_persona_snapshot(
        agent_name=lead_agent,
        version=int(lead_snapshot.get("version") or 1),
        source_path=str(lead_snapshot.get("source_path") or ""),
        content=str(lead_snapshot.get("content") or ""),
    )
    collaborator_entries = []
    for agent_name in collaborators:
        snapshot = persona_snapshots.get(agent_name)
        if not snapshot:
            continue
        collaborator_entries.append(
            compile_persona_snapshot(
                agent_name=agent_name,
                version=int(snapshot.get("version") or 1),
                source_path=str(snapshot.get("source_path") or ""),
                content=str(snapshot.get("content") or ""),
            )
        )
    digest_payload = {
        "lead": lead["sha256"],
        "collaborators": [item["sha256"] for item in collaborator_entries],
    }
    return {
        "lead_agent": lead,
        "collaborators": collaborator_entries,
        "sha256": hashlib.sha256(
            json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def render_persona_prompt(compiled_persona: dict | None) -> str:
    if not compiled_persona:
        return ""

    def render_agent(snapshot: dict) -> list[str]:
        contract = dict(snapshot.get("contract") or {})
        lines = [f"{snapshot.get('title') or snapshot.get('agent_name')} ({snapshot.get('agent_name')})"]
        mission = str(contract.get("mission") or "").strip()
        if mission:
            lines.append(f"Mission: {mission}")
        for field_name in (
            "responsibilities",
            "must_output",
            "cannot_do",
            "inputs",
            "review_questions",
            "handoff_in",
            "handoff_out",
            "verification",
        ):
            rows = contract.get(field_name) or []
            if not rows:
                continue
            lines.append(f"{SECTION_LABELS[field_name]}:")
            lines.extend(f"- {item}" for item in rows)
        additional_guidance = str(contract.get("additional_guidance") or "").strip()
        if additional_guidance:
            lines.append("Additional Guidance:")
            lines.append(additional_guidance)
        return lines

    lead = compiled_persona.get("lead_agent") or {}
    lines = ["Persona Contract", *render_agent(lead)]
    collaborators = compiled_persona.get("collaborators") or []
    if collaborators:
        lines.append("")
        lines.append("Collaborator Context")
        for item in collaborators:
            lines.extend(render_agent(item))
            lines.append("")
        while lines and not lines[-1]:
            lines.pop()
    return "\n".join(lines).strip()
