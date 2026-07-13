from __future__ import annotations

import os

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import IntegrationSync, Project, Workspace
from app.integrations.sync_service import supported_integration_platforms
from app.services.agent_api_configs import list_integration_configs


def integration_health(
    db: Session,
    *,
    workspace_name: str | None = None,
    project_name: str | None = None,
) -> dict:
    configs = list_integration_configs(db)
    by_platform: dict[str, list[dict]] = {}
    for row in configs:
        by_platform.setdefault(row["platform"], []).append(row)

    workspace = None
    project = None
    if workspace_name:
        workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if workspace and project_name:
        project = db.scalar(select(Project).where(Project.workspace_id == workspace.id, Project.name == project_name))

    syncable = set(supported_integration_platforms())
    items = []
    for platform in sorted(by_platform):
        requirements = by_platform[platform]
        missing = [item["config_key"] for item in requirements if item["is_required"] and not item["is_set"]]
        latest_sync = None
        if project and platform in syncable:
            row = db.scalar(
                select(IntegrationSync)
                .where(IntegrationSync.project_id == project.id, IntegrationSync.platform == platform)
                .order_by(desc(IntegrationSync.created_at))
                .limit(1)
            )
            if row:
                latest_sync = {
                    "id": row.id,
                    "sync_type": row.sync_type,
                    "status": row.status,
                    "items_synced": row.items_synced,
                    "error_log": row.error_log,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
        items.append(
            {
                "platform": platform,
                "ready": not missing,
                "sync_supported": platform in syncable,
                "required": [
                    {
                        "config_key": item["config_key"],
                        "label": item["label"],
                        "env_var": item["env_var"],
                        "is_set": item["is_set"],
                    }
                    for item in requirements
                    if item["is_required"]
                ],
                "missing": missing,
                "latest_sync": latest_sync,
            }
        )
    return {
        "workspace_name": workspace_name,
        "project_name": project_name,
        "platforms": items,
        "env_prefix": "CRISPY_API_KEY_",
        "available_env_vars": sorted(name for name in os.environ if name.startswith("CRISPY_API_KEY_")),
    }


def credential_ready_map(db: Session) -> dict:
    health = integration_health(db)
    return {
        item["platform"]: {
            **{req["config_key"]: req["is_set"] for req in item["required"]},
            "ready": item["ready"],
            "sync_supported": item["sync_supported"],
            "missing": item["missing"],
        }
        for item in health["platforms"]
    }
