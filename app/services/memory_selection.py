from __future__ import annotations

from typing import Any


MEMORY_SELECTION_MODES = {"auto", "manual", "none"}


def normalize_memory_selection(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    mode = str(raw.get("mode") or "auto").strip().lower()
    if mode not in MEMORY_SELECTION_MODES:
        mode = "auto"
    return {
        "mode": mode,
        "include_ids": _string_list(raw.get("include_ids")),
        "exclude_ids": _string_list(raw.get("exclude_ids")),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    results: list[str] = []
    for item in value:
        item_id = str(item or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        results.append(item_id)
    return results
