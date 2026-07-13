from __future__ import annotations

import os

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import IntegrationSync, Project, ShopChannelAccount, Workspace
from app.integrations.sync_service import supported_integration_platforms
from app.services.agent_api_configs import list_integration_configs


CHANNEL_ACCOUNT_REQUIREMENTS = {
    "shopify": ["store_domain", "access_token"],
    "meta": ["access_token", "ad_account_id"],
    "tiktok": ["access_token", "advertiser_id"],
    "notion": ["api_key", "database_id"],
}


def _account_fallback_credential(row: ShopChannelAccount, key: str) -> str:
    if key in {"ad_account_id", "advertiser_id"}:
        return row.account_id or row.account_key or ""
    if key == "store_domain":
        return row.account_id or row.account_url or row.account_key or ""
    if key == "database_id":
        return row.account_id or ""
    return ""


def _account_missing_credentials(row: ShopChannelAccount) -> list[str]:
    required = CHANNEL_ACCOUNT_REQUIREMENTS.get(row.platform, [])
    env_vars = row.credential_env_vars if isinstance(row.credential_env_vars, dict) else {}
    missing = []
    for key in required:
        env_name = str(env_vars.get(key) or "").strip()
        if not (env_name and os.getenv(env_name)) and not _account_fallback_credential(row, key):
            missing.append(key)
    return missing


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
    accounts_by_platform: dict[str, list[ShopChannelAccount]] = {}
    if workspace:
        account_rows = db.scalars(
            select(ShopChannelAccount).where(
                ShopChannelAccount.workspace_id == workspace.id,
                ShopChannelAccount.status != "archived",
            )
        ).all()
        for row in account_rows:
            accounts_by_platform.setdefault(row.platform, []).append(row)

    syncable = set(supported_integration_platforms())
    items = []
    for platform in sorted(set(by_platform) | set(accounts_by_platform)):
        requirements = by_platform.get(platform, [])
        missing = [item["config_key"] for item in requirements if item["is_required"] and not item["is_set"]]
        accounts = []
        for account in accounts_by_platform.get(platform, []):
            account_missing = _account_missing_credentials(account)
            latest_account_sync = None
            if project and platform in syncable:
                sync_row = db.scalar(
                    select(IntegrationSync)
                    .where(
                        IntegrationSync.project_id == project.id,
                        IntegrationSync.platform == platform,
                        IntegrationSync.channel_account_id == account.id,
                    )
                    .order_by(desc(IntegrationSync.created_at))
                    .limit(1)
                )
                if sync_row:
                    latest_account_sync = {
                        "id": sync_row.id,
                        "sync_type": sync_row.sync_type,
                        "status": sync_row.status,
                        "items_synced": sync_row.items_synced,
                        "error_log": sync_row.error_log,
                        "created_at": sync_row.created_at.isoformat() if sync_row.created_at else None,
                    }
            accounts.append(
                {
                    "id": account.id,
                    "label": account.label or account.account_key,
                    "account_key": account.account_key,
                    "account_id": account.account_id,
                    "status": account.status,
                    "is_primary": account.is_primary,
                    "ready": not account_missing,
                    "missing": account_missing,
                    "latest_sync": latest_account_sync,
                }
            )
        if accounts:
            missing = [] if any(item["ready"] for item in accounts) else sorted({key for item in accounts for key in item["missing"]})
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
                "accounts": accounts,
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
