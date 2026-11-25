"""Local connector and agent-tool plugin manifests with permissions and audit."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import (
    GraphEntity,
    GraphEvidence,
    PluginAuditLog,
    PluginManifest,
    PluginPermission,
    SourceConnection,
    SyncRun,
    utcnow,
)
from personal_ai_life_os.parsers.generic_chat import (
    UnsupportedChatExportError,
    parse_generic_chat,
)
from personal_ai_life_os.parsers.memory_markdown import (
    parse_memory_markdown,
)
from personal_ai_life_os.services.deletion import (
    complete_source_deletion,
    request_source_deletion,
    scrub_source_derivatives,
)
from personal_ai_life_os.services.ingestion import IngestionFailure, ingest_file, response_item
from personal_ai_life_os.storage import ObjectStore

PERMISSION_CATALOG = {
    "connector.preview": "Preview a user-selected file without storing it.",
    "connector.import": "Import a user-selected file into a new source.",
    "connector.read_selected_path": "Read only the path explicitly selected by the user.",
    "connector.delete": "Request deletion of an imported source.",
    "agent.read_graph": "Read owner-scoped graph entities and evidence.",
    "agent.read_timeline": "Read owner-scoped timeline items.",
    "agent.read_files": "Read user-selected files with approval.",
    "agent.write_files": "Modify files with approval.",
    "agent.external_send": "Send content outside the app with approval.",
    "agent.payment": "Spend money or make transactions with approval.",
    "agent.delete_data": "Delete data with approval.",
    "agent.change_goal": "Change goals with approval.",
}

BUILTIN_PLUGINS: dict[str, dict[str, Any]] = {
    "generic-json-connector": {
        "version": "1.0.0",
        "kind": "connector",
        "entrypoint": "builtin:generic_json",
        "description": "Preview or import a user-selected JSON, JSONL, or Markdown file.",
        "permissions": [
            "connector.preview",
            "connector.import",
            "connector.delete",
            "connector.read_selected_path",
        ],
    },
    "graph-search-agent": {
        "version": "1.0.0",
        "kind": "agent_tool",
        "entrypoint": "builtin:graph_search",
        "description": "Search the owner's graph entities and evidence for a query.",
        "permissions": ["agent.read_graph"],
    },
}

MAX_PLUGIN_TEXT_BYTES = 5 * 1024 * 1024


class PluginError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _audit(
    session: Session,
    *,
    owner_id: str,
    plugin_id: str | None,
    action: str,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        PluginAuditLog(
            owner_id=owner_id,
            plugin_id=plugin_id,
            action=action,
            status=status,
            detail_json=detail or {},
        )
    )


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "version": entry["version"],
            "kind": entry["kind"],
            "entrypoint": entry["entrypoint"],
            "description": entry["description"],
            "permissions": entry["permissions"],
        }
        for name, entry in BUILTIN_PLUGINS.items()
    ]


def list_plugins(session: Session, *, owner_id: str) -> list[PluginManifest]:
    return list(
        session.scalars(
            select(PluginManifest)
            .where(PluginManifest.owner_id == owner_id)
            .order_by(PluginManifest.created_at.desc(), PluginManifest.id)
        )
    )


def plugin_payload(plugin: PluginManifest) -> dict[str, Any]:
    return {
        "id": plugin.id,
        "name": plugin.name,
        "version": plugin.version,
        "kind": plugin.kind,
        "description": plugin.description,
        "entrypoint": plugin.entrypoint,
        "status": plugin.status,
        "permissions": sorted(
            permission.permission for permission in plugin.permissions if permission.granted
        ),
        "created_at": plugin.created_at,
        "updated_at": plugin.updated_at,
    }


def install_plugin(
    session: Session,
    *,
    owner_id: str,
    name: str,
    permissions: list[str] | None = None,
    config: Settings,
) -> PluginManifest:
    entry = BUILTIN_PLUGINS.get(name)
    if entry is None:
        raise PluginError("plugin_unknown", "This plugin is not in the local catalog.", 404)
    existing = session.scalar(
        select(PluginManifest).where(
            PluginManifest.owner_id == owner_id,
            PluginManifest.name == name,
        )
    )
    if existing is not None:
        raise PluginError("plugin_already_installed", "This plugin is already installed.")
    if len(list_plugins(session, owner_id=owner_id)) >= config.plugin_max_installed:
        raise PluginError("plugin_limit_reached", "Uninstall a plugin before adding another.", 409)
    requested = list(dict.fromkeys(permissions if permissions is not None else entry["permissions"]))
    unknown = [permission for permission in requested if permission not in PERMISSION_CATALOG]
    if unknown:
        raise PluginError(
            "plugin_permission_unknown",
            "A plugin requested an undeclared permission.",
            422,
        )
    not_declared = [permission for permission in requested if permission not in entry["permissions"]]
    if not_declared:
        raise PluginError(
            "plugin_permission_undeclared",
            "A plugin requested a permission outside its manifest.",
            422,
        )
    plugin = PluginManifest(
        owner_id=owner_id,
        name=name,
        version=entry["version"],
        kind=entry["kind"],
        description=entry["description"],
        entrypoint=entry["entrypoint"],
        status="installed",
    )
    session.add(plugin)
    session.flush()
    for permission in requested:
        session.add(
            PluginPermission(
                owner_id=owner_id,
                plugin_id=plugin.id,
                permission=permission,
                granted=True,
            )
        )
    _audit(
        session,
        owner_id=owner_id,
        plugin_id=plugin.id,
        action="install",
        status="succeeded",
        detail={"name": name, "permissions": requested},
    )
    session.flush()
    return plugin


def _plugin_or_404(session: Session, *, owner_id: str, plugin_id: str) -> PluginManifest:
    plugin = session.scalar(
        select(PluginManifest).where(
            PluginManifest.id == plugin_id,
            PluginManifest.owner_id == owner_id,
        )
    )
    if plugin is None:
        raise PluginError("plugin_not_found", "The plugin was not found.", 404)
    return plugin


def set_plugin_status(
    session: Session, *, owner_id: str, plugin_id: str, status: str
) -> PluginManifest:
    if status not in ("enabled", "disabled"):
        raise PluginError("plugin_status_invalid", "Choose enabled or disabled.", 422)
    plugin = _plugin_or_404(session, owner_id=owner_id, plugin_id=plugin_id)
    plugin.status = status
    plugin.updated_at = utcnow()
    _audit(
        session,
        owner_id=owner_id,
        plugin_id=plugin.id,
        action=status,
        status="succeeded",
    )
    session.flush()
    return plugin


def uninstall_plugin(session: Session, *, owner_id: str, plugin_id: str) -> None:
    plugin = _plugin_or_404(session, owner_id=owner_id, plugin_id=plugin_id)
    name = plugin.name
    session.delete(plugin)
    session.flush()
    _audit(
        session,
        owner_id=owner_id,
        plugin_id=None,
        action="uninstall",
        status="succeeded",
        detail={"name": name, "plugin_id": plugin_id},
    )
    session.flush()


def _has_permission(plugin: PluginManifest, permission: str) -> bool:
    return any(
        entry.permission == permission and entry.granted for entry in plugin.permissions
    )


def _require_permission(plugin: PluginManifest, permission: str) -> None:
    if not _has_permission(plugin, permission):
        raise PluginError(
            "plugin_permission_denied",
            "This plugin did not declare the permission required for the action.",
            403,
        )


def _parse_connector(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    filename = str(payload.get("filename") or "").strip()
    content = payload.get("content")
    if not filename or not isinstance(content, str) or not content.strip():
        raise PluginError("plugin_invalid_payload", "Provide filename and content.", 422)
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_PLUGIN_TEXT_BYTES:
        raise PluginError("plugin_file_too_large", "Keep connector text under 5 MB.", 413)
    lowered = filename.lower()
    try:
        if lowered.endswith((".json", ".jsonl")):
            items = parse_generic_chat(encoded, filename)
        elif lowered.endswith((".md", ".markdown")):
            items = parse_memory_markdown(content, filename)
        else:
            raise PluginError(
                "plugin_unsupported_file",
                "The reference connector accepts JSON, JSONL, or Markdown.",
                422,
            )
    except (UnsupportedChatExportError, UnicodeDecodeError) as error:
        raise PluginError("plugin_parse_failed", str(error), 422) from error
    preview = [
        {
            "title": item.title,
            "kind": item.kind,
            "occurred_at": item.occurred_at.isoformat() if item.occurred_at else None,
            "source_locator": item.source_locator,
        }
        for item in items[:20]
    ]
    return preview, "chat_export" if lowered.endswith((".json", ".jsonl")) else "memory_markdown"


def _import_connector(
    session: Session,
    *,
    store: ObjectStore,
    owner_id: str,
    payload: dict[str, Any],
    user_timezone: str,
) -> dict[str, Any]:
    preview, kind = _parse_connector(payload)
    filename = str(payload.get("filename") or "plugin-import")
    content = str(payload.get("content") or "")
    source = SourceConnection(
        owner_id=owner_id,
        kind=kind,
        name=filename[:240],
        status="active",
        consent_version="source-consent-v1",
        selected_scope={},
    )
    session.add(source)
    session.flush()
    session.commit()
    run, items = ingest_file(
        session=session,
        store=store,
        source=source,
        owner_id=owner_id,
        filename=filename,
        content_type="application/json" if kind == "chat_export" else "text/markdown",
        payload=content.encode("utf-8"),
        user_timezone=user_timezone,
    )
    return {
        "source_id": source.id,
        "sync_run_id": run.id,
        "items_created": run.items_created,
        "items_duplicate": run.items_duplicate,
        "preview": preview,
        "items": [response_item(item) for item in items[:20]],
    }


def _delete_connector_source(
    session: Session,
    *,
    store: ObjectStore,
    owner_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    source_id = str(payload.get("source_id") or "").strip()
    source = session.scalar(
        select(SourceConnection).where(
            SourceConnection.id == source_id,
            SourceConnection.owner_id == owner_id,
        )
    )
    if source is None:
        raise PluginError("plugin_source_not_found", "The imported source was not found.", 404)
    tombstone = request_source_deletion(store, owner_id, source_id)
    source.status = "deleting"
    session.commit()
    items = scrub_source_derivatives(session, owner_id, source_id)
    keys = {item.object_key for item in items if item.object_key}
    keys.update(
        key
        for key in session.scalars(
            select(SyncRun.object_key).where(
                SyncRun.owner_id == owner_id,
                SyncRun.source_id == source_id,
                SyncRun.object_key.is_not(None),
            )
        )
        if key
    )
    for key in keys:
        if key:
            store.delete(key)
    store.delete_source_objects(owner_id, source_id)
    complete_source_deletion(store, owner_id, source_id, tombstone)
    session.delete(source)
    session.commit()
    return {"source_id": source_id, "deleted": True}


def _graph_search(
    session: Session, *, owner_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise PluginError("plugin_invalid_payload", "Enter a search query.", 422)
    limit = min(max(int(payload.get("limit") or 10), 1), 20)
    entities = list(
        session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.owner_id == owner_id,
                GraphEntity.status == "active",
                (GraphEntity.name.icontains(query)) | (GraphEntity.summary.icontains(query)),
            )
            .order_by(GraphEntity.confidence.desc(), GraphEntity.updated_at.desc())
            .limit(limit)
        )
    )
    results = []
    for entity in entities:
        evidence = list(
            session.scalars(
                select(GraphEvidence)
                .where(
                    GraphEvidence.owner_id == owner_id,
                    GraphEvidence.entity_id == entity.id,
                    GraphEvidence.availability == "active",
                )
                .order_by(GraphEvidence.confidence.desc())
                .limit(3)
            )
        )
        results.append(
            {
                "entity_id": entity.id,
                "entity_type": entity.entity_type,
                "name": entity.name,
                "summary": entity.summary,
                "confidence": entity.confidence,
                "evidence": [
                    {"quote": row.quote, "source_item_id": row.source_item_id}
                    for row in evidence
                ],
            }
        )
    return {"query": query, "results": results}


def invoke_plugin(
    session: Session,
    *,
    store: ObjectStore,
    owner_id: str,
    plugin_id: str,
    action: str,
    payload: dict[str, Any],
    user_timezone: str,
) -> dict[str, Any]:
    plugin = _plugin_or_404(session, owner_id=owner_id, plugin_id=plugin_id)
    if plugin.status != "enabled":
        _audit(
            session,
            owner_id=owner_id,
            plugin_id=plugin.id,
            action=action,
            status="denied",
            detail={"code": "plugin_disabled"},
        )
        session.commit()
        raise PluginError("plugin_disabled", "Enable this plugin before invoking it.", 409)
    try:
        if plugin.entrypoint == "builtin:generic_json":
            if action == "preview":
                _require_permission(plugin, "connector.preview")
                _require_permission(plugin, "connector.read_selected_path")
                preview, _kind = _parse_connector(payload)
                result = {"preview": preview, "total": len(preview)}
            elif action == "import":
                _require_permission(plugin, "connector.import")
                _require_permission(plugin, "connector.read_selected_path")
                result = _import_connector(
                    session,
                    store=store,
                    owner_id=owner_id,
                    payload=payload,
                    user_timezone=user_timezone,
                )
            elif action == "delete":
                _require_permission(plugin, "connector.delete")
                result = _delete_connector_source(
                    session, store=store, owner_id=owner_id, payload=payload
                )
            else:
                raise PluginError("plugin_action_unsupported", "Use preview, import, or delete.", 422)
        elif plugin.entrypoint == "builtin:graph_search":
            if action != "search":
                raise PluginError("plugin_action_unsupported", "Use search.", 422)
            _require_permission(plugin, "agent.read_graph")
            result = _graph_search(session, owner_id=owner_id, payload=payload)
        else:
            raise PluginError("plugin_entrypoint_unsupported", "This plugin cannot be invoked.", 422)
    except PluginError as error:
        _audit(
            session,
            owner_id=owner_id,
            plugin_id=plugin.id,
            action=action,
            status="denied" if error.status_code in (403, 409) else "failed",
            detail={"code": error.code, "message": error.message},
        )
        session.commit()
        raise
    except (IngestionFailure, ValueError, KeyError, TypeError) as error:
        _audit(
            session,
            owner_id=owner_id,
            plugin_id=plugin.id,
            action=action,
            status="failed",
            detail={"code": "plugin_invoke_failed", "error": type(error).__name__},
        )
        session.commit()
        raise PluginError("plugin_invoke_failed", "The plugin failed without affecting the main app.", 502) from error
    except Exception as error:
        session.rollback()
        _audit(
            session,
            owner_id=owner_id,
            plugin_id=plugin.id,
            action=action,
            status="failed",
            detail={"code": "plugin_invoke_failed", "error": type(error).__name__},
        )
        session.commit()
        raise PluginError("plugin_invoke_failed", "The plugin failed without affecting the main app.", 502) from error
    _audit(
        session,
        owner_id=owner_id,
        plugin_id=plugin.id,
        action=action,
        status="succeeded",
        detail={"kind": plugin.kind},
    )
    session.commit()
    return result


def list_audit(session: Session, *, owner_id: str, limit: int = 50) -> list[PluginAuditLog]:
    return list(
        session.scalars(
            select(PluginAuditLog)
            .where(PluginAuditLog.owner_id == owner_id)
            .order_by(PluginAuditLog.created_at.desc(), PluginAuditLog.id)
            .limit(limit)
        )
    )
