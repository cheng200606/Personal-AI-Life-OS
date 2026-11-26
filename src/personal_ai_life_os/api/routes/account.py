"""Portable data archive and retryable account deletion."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep, DeletionUserDep, SessionDep
from personal_ai_life_os.models import (
    AgentAction,
    BackgroundJob,
    Collection,
    EntityAlias,
    EntityMergeLog,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    InsightDismissal,
    ModelConsent,
    ModelRun,
    PluginAuditLog,
    PluginManifest,
    QaThread,
    Reminder,
    Review,
    ReviewVersion,
    SavedSearch,
    SourceConnection,
    SourceItem,
    SyncRun,
    Tag,
)
from personal_ai_life_os.services.jobs import cancel_all_jobs_for_owner
from personal_ai_life_os.storage import ObjectStore

router = APIRouter(prefix="/account", tags=["account"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


@router.get("/archive")
def download_archive(
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    sources = list(session.scalars(select(SourceConnection).where(SourceConnection.owner_id == user.id)))
    runs = list(session.scalars(select(SyncRun).where(SyncRun.owner_id == user.id)))
    items = list(
        session.scalars(
            select(SourceItem).where(
                SourceItem.owner_id == user.id,
                SourceItem.deleted_at.is_(None),
            )
        )
    )
    reviews = list(session.scalars(select(Review).where(Review.owner_id == user.id)))
    review_versions = list(
        session.scalars(
            select(ReviewVersion)
            .join(Review, Review.id == ReviewVersion.review_id)
            .where(Review.owner_id == user.id)
            .order_by(ReviewVersion.created_at, ReviewVersion.id)
        )
    )
    model_consents = list(
        session.scalars(select(ModelConsent).where(ModelConsent.owner_id == user.id))
    )
    reminders = list(session.scalars(select(Reminder).where(Reminder.owner_id == user.id)))
    model_runs = list(session.scalars(select(ModelRun).where(ModelRun.owner_id == user.id)))
    jobs = list(
        session.scalars(
            select(BackgroundJob)
            .where(BackgroundJob.owner_id == user.id)
            .order_by(BackgroundJob.created_at, BackgroundJob.id)
        )
    )
    graph_entities = list(
        session.scalars(select(GraphEntity).where(GraphEntity.owner_id == user.id))
    )
    graph_relations = list(
        session.scalars(select(GraphRelation).where(GraphRelation.owner_id == user.id))
    )
    graph_evidence = list(
        session.scalars(select(GraphEvidence).where(GraphEvidence.owner_id == user.id))
    )
    entity_aliases = list(
        session.scalars(select(EntityAlias).where(EntityAlias.owner_id == user.id))
    )
    entity_merges = list(
        session.scalars(select(EntityMergeLog).where(EntityMergeLog.owner_id == user.id))
    )
    qa_threads = list(
        session.scalars(
            select(QaThread)
            .where(QaThread.owner_id == user.id)
            .order_by(QaThread.created_at, QaThread.id)
        )
    )
    insight_dismissals = list(
        session.scalars(
            select(InsightDismissal).where(InsightDismissal.owner_id == user.id)
        )
    )
    agent_actions = list(
        session.scalars(
            select(AgentAction)
            .where(AgentAction.owner_id == user.id)
            .order_by(AgentAction.created_at, AgentAction.id)
        )
    )
    plugin_manifests = list(
        session.scalars(
            select(PluginManifest).where(PluginManifest.owner_id == user.id)
        )
    )
    plugin_audit = list(
        session.scalars(
            select(PluginAuditLog).where(PluginAuditLog.owner_id == user.id)
        )
    )
    tags = list(session.scalars(select(Tag).where(Tag.owner_id == user.id).order_by(Tag.name_key, Tag.id)))
    collections = list(
        session.scalars(
            select(Collection).where(Collection.owner_id == user.id).order_by(Collection.name_key, Collection.id)
        )
    )
    saved_searches = list(
        session.scalars(
            select(SavedSearch)
            .where(SavedSearch.owner_id == user.id)
            .order_by(SavedSearch.created_at, SavedSearch.id)
        )
    )
    archive = BytesIO()
    missing_objects: list[str] = []
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.writestr(
            "account.json",
            _json_bytes({"email": user.email, "timezone": user.timezone, "created_at": _iso(user.created_at)}),
        )
        bundle.writestr(
            "sources.json",
            _json_bytes(
                [
                    {
                        "id": source.id,
                        "kind": source.kind,
                        "name": source.name,
                        "status": source.status,
                        "consent_version": source.consent_version,
                        "selected_scope": source.selected_scope,
                        "created_at": _iso(source.created_at),
                        "last_sync_at": _iso(source.last_sync_at),
                    }
                    for source in sources
                ]
            ),
        )
        bundle.writestr(
            "sync-runs.json",
            _json_bytes(
                [
                    {
                        "id": run.id,
                        "source_id": run.source_id,
                        "status": run.status,
                        "parser_version": run.parser_version,
                        "file_sha256": run.file_sha256,
                        "items_seen": run.items_seen,
                        "items_created": run.items_created,
                        "items_updated": run.items_updated,
                        "items_duplicate": run.items_duplicate,
                        "items_removed": run.items_removed,
                        "items_skipped": run.items_skipped,
                        "items_failed": run.items_failed,
                        "error_code": run.error_code,
                        "created_at": _iso(run.created_at),
                        "completed_at": _iso(run.completed_at),
                    }
                    for run in runs
                ]
            ),
        )
        bundle.writestr(
            "timeline.json",
            _json_bytes(
                [
                    {
                        "id": item.id,
                        "source_id": item.source_id,
                        "kind": item.kind,
                        "title": item.title,
                        "content_text": item.content_text,
                        "occurred_at": _iso(item.occurred_at),
                        "source_timezone": item.source_timezone,
                        "source_sha256": item.source_sha256,
                        "parser_version": item.parser_version,
                        "source_locator": item.source_locator,
                        "metadata": item.metadata_json,
                    }
                    for item in items
                ]
            ),
        )
        bundle.writestr(
            "tags.json",
            _json_bytes(
                [
                    {"id": tag.id, "name": tag.name, "color": tag.color, "created_at": _iso(tag.created_at), "updated_at": _iso(tag.updated_at)}
                    for tag in tags
                ]
            ),
        )
        bundle.writestr(
            "collections.json",
            _json_bytes(
                [
                    {"id": collection.id, "name": collection.name, "description": collection.description, "created_at": _iso(collection.created_at), "updated_at": _iso(collection.updated_at)}
                    for collection in collections
                ]
            ),
        )
        bundle.writestr(
            "item-organization.json",
            _json_bytes(
                [
                    {
                        "item_id": item.id,
                        "tag_ids": sorted(tag.id for tag in item.tags),
                        "collection_ids": sorted(collection.id for collection in item.collections),
                    }
                    for item in items
                ]
            ),
        )
        bundle.writestr(
            "saved-searches.json",
            _json_bytes(
                [
                    {
                        "id": entry.id,
                        "name": entry.name,
                        "query": entry.query,
                        "filters": entry.filters_json,
                        "created_at": _iso(entry.created_at),
                        "updated_at": _iso(entry.updated_at),
                    }
                    for entry in saved_searches
                ]
            ),
        )
        bundle.writestr(
            "reviews.json",
            _json_bytes(
                [
                    {
                        "id": review.id,
                        "period_start": _iso(review.period_start),
                        "period_end": _iso(review.period_end),
                        "status": review.status,
                        "draft": review.draft_json,
                        "final_text": review.final_text,
                        "source_ids": [item.id for item in review.source_items if item.deleted_at is None],
                    }
                    for review in reviews
                ]
            ),
        )
        bundle.writestr(
            "review-versions.json",
            _json_bytes(
                [
                    {
                        "id": version.id,
                        "review_id": version.review_id,
                        "version_number": version.version_number,
                        "status": version.status,
                        "draft": version.draft_json,
                        "final_text": version.final_text,
                        "reason": version.reason,
                        "created_at": _iso(version.created_at),
                    }
                    for version in review_versions
                ]
            ),
        )
        bundle.writestr(
            "model-consents.json",
            _json_bytes(
                [
                    {
                        "provider_id": consent.provider_id,
                        "disclosure_version": consent.disclosure_version,
                        "granted_at": _iso(consent.granted_at),
                        "revoked_at": _iso(consent.revoked_at),
                    }
                    for consent in model_consents
                ]
            ),
        )
        bundle.writestr(
            "reminders.json",
            _json_bytes(
                [
                    {
                        "id": reminder.id,
                        "title": reminder.title,
                        "notes": reminder.notes,
                        "due_at": _iso(reminder.due_at),
                        "status": reminder.status,
                        "source_ids": [item.id for item in reminder.source_items if item.deleted_at is None],
                    }
                    for reminder in reminders
                ]
            ),
        )
        bundle.writestr(
            "model-usage.json",
            _json_bytes(
                [
                    {
                        "provider": run.provider,
                        "model": run.model,
                        "purpose": run.purpose,
                        "status": run.status,
                        "prompt_version": run.prompt_version,
                        "latency_ms": run.latency_ms,
                        "input_tokens": run.input_tokens,
                        "output_tokens": run.output_tokens,
                        "cost_usd": str(run.cost_usd) if run.cost_usd is not None else None,
                        "created_at": _iso(run.created_at),
                    }
                    for run in model_runs
                ]
            ),
        )
        bundle.writestr(
            "background-jobs.json",
            _json_bytes(
                [
                    {
                        "id": job.id,
                        "kind": job.kind,
                        "status": job.status,
                        "error_code": job.error_code,
                        "result": job.result_json,
                        "created_at": _iso(job.created_at),
                        "completed_at": _iso(job.completed_at),
                    }
                    for job in jobs
                ]
            ),
        )
        bundle.writestr(
            "graph-entities.json",
            _json_bytes(
                [
                    {
                        "id": entity.id,
                        "entity_type": entity.entity_type,
                        "name": entity.name,
                        "normalized_name": entity.normalized_name,
                        "summary": entity.summary,
                        "confidence": entity.confidence,
                        "status": entity.status,
                        "merged_into_id": entity.merged_into_id,
                        "created_by": entity.created_by,
                        "created_at": _iso(entity.created_at),
                        "updated_at": _iso(entity.updated_at),
                    }
                    for entity in graph_entities
                ]
            ),
        )
        bundle.writestr(
            "graph-relations.json",
            _json_bytes(
                [
                    {
                        "id": relation.id,
                        "from_entity_id": relation.from_entity_id,
                        "to_entity_id": relation.to_entity_id,
                        "relation_type": relation.relation_type,
                        "confidence": relation.confidence,
                        "status": relation.status,
                        "valid_from": _iso(relation.valid_from),
                        "valid_to": _iso(relation.valid_to),
                        "created_by": relation.created_by,
                        "created_at": _iso(relation.created_at),
                    }
                    for relation in graph_relations
                ]
            ),
        )
        bundle.writestr(
            "graph-evidence.json",
            _json_bytes(
                [
                    {
                        "id": evidence.id,
                        "entity_id": evidence.entity_id,
                        "relation_id": evidence.relation_id,
                        "source_id": evidence.source_id,
                        "source_item_id": evidence.source_item_id,
                        "quote": evidence.quote,
                        "locator": evidence.locator,
                        "confidence": evidence.confidence,
                        "availability": evidence.availability,
                        "created_at": _iso(evidence.created_at),
                    }
                    for evidence in graph_evidence
                ]
            ),
        )
        bundle.writestr(
            "entity-aliases.json",
            _json_bytes(
                [
                    {
                        "id": alias.id,
                        "entity_id": alias.entity_id,
                        "alias": alias.alias,
                        "normalized_alias": alias.normalized_alias,
                        "created_at": _iso(alias.created_at),
                    }
                    for alias in entity_aliases
                ]
            ),
        )
        bundle.writestr(
            "entity-merges.json",
            _json_bytes(
                [
                    {
                        "id": merge.id,
                        "source_entity_id": merge.source_entity_id,
                        "target_entity_id": merge.target_entity_id,
                        "status": merge.status,
                        "snapshot": merge.snapshot,
                        "created_at": _iso(merge.created_at),
                        "undone_at": _iso(merge.undone_at),
                    }
                    for merge in entity_merges
                ]
            ),
        )
        bundle.writestr(
            "qa-threads.json",
            _json_bytes(
                [
                    {
                        "id": thread.id,
                        "title": thread.title,
                        "scope": thread.scope,
                        "created_at": _iso(thread.created_at),
                        "updated_at": _iso(thread.updated_at),
                        "messages": [
                            {
                                "id": message.id,
                                "role": message.role,
                                "content": message.content,
                                "answer": message.answer,
                                "citations": message.citations,
                                "confidence": message.confidence,
                                "created_at": _iso(message.created_at),
                            }
                            for message in thread.messages
                        ],
                    }
                    for thread in qa_threads
                ]
            ),
        )
        bundle.writestr(
            "insight-dismissals.json",
            _json_bytes(
                [
                    {
                        "id": dismissal.id,
                        "insight_key": dismissal.insight_key,
                        "rule": dismissal.rule,
                        "entity_id": dismissal.entity_id,
                        "reason": dismissal.reason,
                        "created_at": _iso(dismissal.created_at),
                    }
                    for dismissal in insight_dismissals
                ]
            ),
        )
        bundle.writestr(
            "agent-actions.json",
            _json_bytes(
                [
                    {
                        "id": action.id,
                        "kind": action.kind,
                        "target_type": action.target_type,
                        "target_id": action.target_id,
                        "before": action.before_json,
                        "after": action.after_json,
                        "evidence_item_ids": action.evidence_json,
                        "status": action.status,
                        "approval": action.approval,
                        "error_code": action.error_code,
                        "audit": action.audit_json,
                        "expires_at": _iso(action.expires_at),
                        "created_at": _iso(action.created_at),
                        "undone_at": _iso(action.undone_at),
                    }
                    for action in agent_actions
                ]
            ),
        )
        bundle.writestr(
            "plugin-manifests.json",
            _json_bytes(
                [
                    {
                        "id": plugin.id,
                        "name": plugin.name,
                        "version": plugin.version,
                        "kind": plugin.kind,
                        "description": plugin.description,
                        "entrypoint": plugin.entrypoint,
                        "status": plugin.status,
                        "permissions": [
                            permission.permission
                            for permission in plugin.permissions
                            if permission.granted
                        ],
                        "created_at": _iso(plugin.created_at),
                        "updated_at": _iso(plugin.updated_at),
                    }
                    for plugin in plugin_manifests
                ]
            ),
        )
        bundle.writestr(
            "plugin-audit.json",
            _json_bytes(
                [
                    {
                        "id": entry.id,
                        "plugin_id": entry.plugin_id,
                        "action": entry.action,
                        "status": entry.status,
                        "detail": entry.detail_json,
                        "created_at": _iso(entry.created_at),
                    }
                    for entry in plugin_audit
                ]
            ),
        )
        store: ObjectStore = request.app.state.object_store
        object_keys = {run.object_key for run in runs if run.object_key}
        object_keys.update(item.object_key for item in items if item.object_key)
        for key in sorted(object_keys):
            try:
                content = store.get(key)
            except FileNotFoundError:
                missing_objects.append(key.rsplit("/", 1)[-1])
                continue
            source_id = key.split("/")[3] if len(key.split("/")) > 3 else "source"
            digest = key.split("/")[-2] if len(key.split("/")) > 1 else "object"
            bundle.writestr("originals/" + source_id + "/" + digest + ".bin", content)
        bundle.writestr("archive-manifest.json", _json_bytes({"missing_object_files": missing_objects}))
        bundle.writestr(
            "README.txt",
            "Personal AI Life OS account export. JSON files use UTF-8. The originals directory contains selected, stored source files; ChatGPT exports are minimized to chosen conversations and photos are sanitized copies. Keep this archive private.",
        )
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="lifeos-archive.zip"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("", status_code=204)
def delete_account(request: Request, user: DeletionUserDep, session: SessionDep) -> Response:
    if user.deletion_requested_at is None:
        store: ObjectStore = request.app.state.object_store
        tombstone = _json_bytes({"owner_id": user.id, "requested_at": datetime.now(UTC).isoformat()})
        try:
            store.write_deletion_tombstone(user.id, tombstone)
        except Exception as error:
            raise HTTPException(
                503,
                detail={"code": "account_tombstone_pending", "message": "Deletion could not be durably recorded. Retry shortly."},
            ) from error
        user.deletion_requested_at = datetime.now(UTC)
        cancel_all_jobs_for_owner(session, user.id)
        for source in session.scalars(
            select(SourceConnection).where(SourceConnection.owner_id == user.id)
        ):
            source.status = "deleting"
        session.commit()

    keys = set(
        session.scalars(
            select(SourceItem.object_key).where(SourceItem.owner_id == user.id)
        )
    )
    keys.update(
        key
        for key in session.scalars(
            select(SyncRun.object_key).where(
                SyncRun.owner_id == user.id,
                SyncRun.object_key.is_not(None),
            )
        )
        if key
    )
    store: ObjectStore = request.app.state.object_store
    try:
        for key in keys:
            store.delete(key)
        store.delete_owner_objects(user.id)
        store.write_deletion_tombstone(
            user.id,
            _json_bytes(
                {
                    "owner_id": user.id,
                    "requested_at": user.deletion_requested_at.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
    except Exception as error:
        raise HTTPException(
            503,
            detail={"code": "account_cleanup_pending", "message": "Account access is disabled. Retry deletion to finish object cleanup."},
        ) from error

    session.delete(user)
    session.commit()
    return Response(status_code=204)
