"""Agent actions with audited automatic writes, red lines, and 24-hour undo."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import (
    AgentAction,
    BackgroundJob,
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    Reminder,
    Review,
    SourceConnection,
    SourceItem,
    User,
    utcnow,
)
from personal_ai_life_os.services.graph_extraction import monthly_spend
from personal_ai_life_os.services.jobs import enqueue_background_job
from personal_ai_life_os.services.model_usage import model_cost_usd, model_rates_configured

AGENT_TOOLS: dict[str, dict[str, Any]] = {
    "graph.search": {
        "kind": "read",
        "permission": "agent.read_graph",
        "requires_approval": False,
        "red_line": False,
        "description": "Search the owner's evidence graph.",
    },
    "timeline.read": {
        "kind": "read",
        "permission": "agent.read_timeline",
        "requires_approval": False,
        "red_line": False,
        "description": "Read selected timeline items.",
    },
    "file.read": {
        "kind": "read",
        "permission": "agent.read_files",
        "requires_approval": True,
        "red_line": False,
        "description": "Read a user-selected local file.",
    },
    "file.write": {
        "kind": "write",
        "permission": "agent.write_files",
        "requires_approval": True,
        "red_line": True,
        "description": "Modify or rename an original file.",
    },
    "external.send": {
        "kind": "external",
        "permission": "agent.external_send",
        "requires_approval": True,
        "red_line": True,
        "description": "Send or submit content outside the app.",
    },
    "payment.charge": {
        "kind": "external",
        "permission": "agent.payment",
        "requires_approval": True,
        "red_line": True,
        "description": "Spend money, place orders, or make irreversible transactions.",
    },
    "data.delete": {
        "kind": "write",
        "permission": "agent.delete_data",
        "requires_approval": True,
        "red_line": True,
        "description": "Delete personal data or long-term memory.",
    },
    "goal.change": {
        "kind": "write",
        "permission": "agent.change_goal",
        "requires_approval": True,
        "red_line": True,
        "description": "Delete or change a goal.",
    },
}

ACTION_TOOLS: dict[str, str] = {
    "create_reminder": "reminder.create",
    "create_task": "task.create",
    "create_project": "project.create",
    "create_growth_record": "growth.create",
    "update_goal_progress": "goal.progress",
    "create_review_draft": "review.draft",
}

WRITE_TOOLS: dict[str, dict[str, Any]] = {
    "reminder.create": {
        "kind": "write",
        "permission": "agent.write_internal",
        "requires_approval": False,
        "red_line": False,
        "description": "Create an in-app reminder.",
    },
    "task.create": {
        "kind": "write",
        "permission": "agent.write_internal",
        "requires_approval": False,
        "red_line": False,
        "description": "Create a task entity in the graph.",
    },
    "project.create": {
        "kind": "write",
        "permission": "agent.write_internal",
        "requires_approval": False,
        "red_line": False,
        "description": "Create a project entity in the graph.",
    },
    "growth.create": {
        "kind": "write",
        "permission": "agent.write_internal",
        "requires_approval": False,
        "red_line": False,
        "description": "Create a growth record in the graph.",
    },
    "goal.progress": {
        "kind": "write",
        "permission": "agent.write_internal",
        "requires_approval": False,
        "red_line": False,
        "description": "Append goal progress as a linked growth record.",
    },
    "review.draft": {
        "kind": "write",
        "permission": "agent.write_internal",
        "requires_approval": False,
        "red_line": False,
        "description": "Create a weekly review draft.",
    },
}


class AgentActionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 403,
        action: AgentAction | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.action = action


def list_tools() -> list[dict[str, Any]]:
    tools = []
    for name, policy in {**AGENT_TOOLS, **WRITE_TOOLS}.items():
        tools.append({"name": name, **policy})
    return tools


def ensure_tool_allowed(tool_name: str, *, approved: bool = False) -> dict[str, Any]:
    policy = AGENT_TOOLS.get(tool_name)
    if policy is None:
        raise AgentActionError("agent_tool_unknown", "This agent tool is not registered.", 422)
    if policy["red_line"] and not approved:
        raise AgentActionError(
            "agent_requires_human_approval",
            "This action requires explicit human approval and cannot run automatically.",
            403,
        )
    if policy["requires_approval"] and not approved:
        raise AgentActionError(
            "agent_requires_human_approval",
            "This tool requires explicit approval.",
            403,
        )
    return policy


def _rejected(
    session: Session,
    *,
    owner_id: str,
    kind: str,
    code: str,
    message: str,
    config: Settings,
    now: datetime,
    status_code: int = 403,
) -> AgentActionError:
    action = AgentAction(
        owner_id=owner_id,
        kind=kind,
        target_type="tool",
        before_json={},
        after_json={},
        evidence_json=[],
        status="rejected",
        approval="required",
        error_code=code,
        audit_json={"reason": message, "automatic": False},
        expires_at=now + timedelta(hours=config.agent_undo_hours),
    )
    session.add(action)
    session.flush()
    return AgentActionError(code, message, status_code, action)


def _tool_name(kind: str) -> str:
    if kind in AGENT_TOOLS:
        return kind
    tool = ACTION_TOOLS.get(kind)
    if tool is None:
        raise AgentActionError("agent_action_unknown", "This agent action kind is not supported.", 422)
    return tool


def _source_items(
    session: Session, *, owner_id: str, item_ids: list[str]
) -> list[SourceItem]:
    if not item_ids:
        raise AgentActionError("agent_evidence_required", "Choose at least one source item as evidence.", 422)
    unique = list(dict.fromkeys(item_ids))
    if len(unique) > 20:
        raise AgentActionError("agent_evidence_too_large", "Choose at most 20 evidence items.", 413)
    rows = list(
        session.scalars(
            select(SourceItem)
            .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
            .where(
                SourceItem.owner_id == owner_id,
                SourceItem.id.in_(unique),
                SourceItem.deleted_at.is_(None),
                SourceItem.is_current.is_(True),
                SourceConnection.owner_id == owner_id,
                SourceConnection.status == "active",
            )
            .order_by(SourceItem.occurred_at)
        )
    )
    if len(rows) != len(unique):
        raise AgentActionError("source_item_not_found", "One or more evidence items were not found.", 404)
    return rows


def _entity(
    session: Session,
    *,
    owner_id: str,
    entity_type: str,
    name: str,
    summary: str | None,
    items: list[SourceItem],
) -> GraphEntity:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise AgentActionError("agent_name_required", "Enter a title for the generated record.", 422)
    entity = GraphEntity(
        owner_id=owner_id,
        entity_type=entity_type,
        name=cleaned[:500],
        normalized_name=" ".join(cleaned.split()).casefold()[:500],
        summary=summary,
        confidence=0.9,
        status="active",
        created_by="agent",
    )
    session.add(entity)
    session.flush()
    for item in items:
        quote = (item.content_text.strip() or item.title)[:300]
        session.add(
            GraphEvidence(
                owner_id=owner_id,
                entity_id=entity.id,
                source_id=item.source_id,
                source_item_id=item.id,
                quote=quote,
                locator=item.source_locator,
                confidence=0.9,
                availability="active",
            )
        )
    return entity


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise AgentActionError("agent_invalid_date", f"{field_name} must be YYYY-MM-DD.", 422) from error
    raise AgentActionError("agent_invalid_date", f"{field_name} must be YYYY-MM-DD.", 422)


def _local_bounds(start_value: date, end_value: date, timezone_name: str) -> tuple[datetime, datetime]:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(timezone_name)
    start = datetime.combine(start_value, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(end_value, time.min, tzinfo=zone).astimezone(UTC)
    return start, end


def _review_items(
    session: Session, *, owner_id: str, start_at: datetime, end_at: datetime
) -> list[SourceItem]:
    return list(
        session.scalars(
            select(SourceItem)
            .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
            .where(
                SourceItem.owner_id == owner_id,
                SourceItem.is_current.is_(True),
                SourceItem.deleted_at.is_(None),
                SourceItem.occurred_at >= start_at,
                SourceItem.occurred_at < end_at,
                SourceConnection.status == "active",
            )
            .order_by(SourceItem.occurred_at, SourceItem.id)
            .limit(500)
        )
    )


def _review_draft(
    session: Session,
    *,
    owner_id: str,
    payload: dict[str, Any],
    config: Settings,
    now: datetime,
) -> tuple[Review, dict[str, Any]]:
    from personal_ai_life_os.api.routes.reviews import (
        PROMPT_VERSION,
        _estimate_openai_input_tokens,
        _render_markdown,
        _template,
    )

    start_date = _parse_date(payload.get("period_start"), "period_start")
    end_date = _parse_date(payload.get("period_end"), "period_end")
    if end_date <= start_date:
        raise AgentActionError("agent_invalid_period", "The review period must end after it starts.", 422)
    user = session.get(User, owner_id)
    if user is None:
        raise AgentActionError("agent_user_missing", "The account could not be loaded.", 404)
    start_at, end_at = _local_bounds(start_date, end_date, user.timezone)
    items = _review_items(session, owner_id=owner_id, start_at=start_at, end_at=end_at)
    if not items:
        raise AgentActionError("agent_no_evidence", "No active timeline items fall inside this period.", 422)
    existing = session.scalar(
        select(Review).where(
            Review.owner_id == owner_id,
            Review.period_start == start_at,
            Review.period_end == end_at,
        )
    )
    if existing is not None:
        raise AgentActionError("agent_review_exists", "A review already exists for this period.", 409)
    draft = _template(items)
    use_external = bool(payload.get("use_external_model"))
    status = "draft"
    job_id = None
    reserved_cost: Decimal | None = None
    if use_external:
        provider_ready = config.model_provider == "openai" and bool(config.openai_api_key)
        consented = (
            user.ai_consent_at is not None
            and user.ai_consent_provider == config.model_provider
            and user.ai_consent_disclosure_version == config.model_disclosure_version
        )
        rates_ready = model_rates_configured(config)
        reserved_cost = (
            model_cost_usd(
                _estimate_openai_input_tokens(items),
                config.model_max_output_tokens,
                config,
            )
            if rates_ready
            else None
        )
        spent = monthly_spend(session, owner_id, now)
        if not provider_ready:
            raise AgentActionError("agent_model_unavailable", "Configure a provider before using a model draft.", 409)
        if not consented:
            raise AgentActionError("agent_consent_required", "Enable current model consent before using a model draft.", 409)
        if reserved_cost is None:
            raise AgentActionError("agent_model_unconfigured", "Configure current token prices first.", 409)
        if reserved_cost > config.model_max_cost_per_call_usd:
            raise AgentActionError("agent_budget_exceeded", "This draft exceeds the per-call budget.", 409)
        if config.model_monthly_budget_usd > 0 and spent + reserved_cost > config.model_monthly_budget_usd:
            raise AgentActionError("agent_budget_exhausted", "This draft would exceed the monthly model budget.", 409)
        if config.processing_mode != "worker":
            raise AgentActionError("agent_worker_required", "Model drafts require worker mode.", 409)
        status = "processing"
        draft["model"] = {
            "provider": config.model_provider,
            "status": "processing",
            "model": config.openai_model,
            "prompt_version": PROMPT_VERSION,
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    rendered = _render_markdown(draft, items)
    review = Review(
        owner_id=owner_id,
        period_start=start_at,
        period_end=end_at,
        status=status,
        draft_json=draft,
        final_text=rendered,
        source_items=items,
    )
    session.add(review)
    session.flush()
    if use_external and reserved_cost is not None:
        job = enqueue_background_job(
            session,
            owner_id=owner_id,
            review_id=review.id,
            kind="weekly_review",
            dedupe_key=f"weekly-review:{review.id}",
            payload={
                "review_id": review.id,
                "prompt_version": PROMPT_VERSION,
                "provider": config.model_provider,
                "model": config.openai_model,
                "reserved_cost_usd": str(reserved_cost),
            },
            max_attempts=1,
        )
        job_id = job.id
        review.draft_json = {
            **review.draft_json,
            "model": {**review.draft_json["model"], "job_id": job.id},
        }
    return review, {"review_id": review.id, "job_id": job_id, "item_ids": [item.id for item in items]}


def create_action(
    session: Session,
    *,
    owner_id: str,
    kind: str,
    payload: dict[str, Any],
    config: Settings,
    approved: bool = False,
    now: datetime | None = None,
) -> AgentAction:
    current = now or utcnow()
    tool_name = _tool_name(kind)
    if tool_name in AGENT_TOOLS:
        try:
            ensure_tool_allowed(tool_name, approved=approved)
        except AgentActionError as error:
            raise _rejected(
                session,
                owner_id=owner_id,
                kind=kind,
                code=error.code,
                message=error.message,
                config=config,
                now=current,
                status_code=error.status_code,
            ) from error
        raise AgentActionError("agent_action_unknown", "Use a registered write action.", 422)

    target_type = "internal"
    target_id: str | None = None
    after: dict[str, Any] = {}
    evidence_item_ids: list[str] = []
    try:
        if kind == "create_reminder":
            title = str(payload.get("title") or "").strip()
            if not title:
                raise AgentActionError("agent_title_required", "Enter a reminder title.", 422)
            due_at = payload.get("due_at")
            if isinstance(due_at, str):
                from datetime import datetime as _datetime

                due_at = _datetime.fromisoformat(due_at)
            reminder = Reminder(
                owner_id=owner_id,
                title=title[:500],
                notes=payload.get("notes"),
                due_at=due_at,
                status="pending",
            )
            session.add(reminder)
            session.flush()
            target_type, target_id = "reminder", reminder.id
            after = {"reminder_id": reminder.id}
            if isinstance(payload.get("source_item_ids"), list):
                for item in _source_items(
                    session, owner_id=owner_id, item_ids=list(payload["source_item_ids"])
                ):
                    reminder.source_items.append(item)
                    evidence_item_ids.append(item.id)
        elif kind in ("create_task", "create_project", "create_growth_record"):
            items = _source_items(session, owner_id=owner_id, item_ids=list(payload.get("source_item_ids") or []))
            entity_type = {
                "create_task": "task",
                "create_project": "project",
                "create_growth_record": "growth_record",
            }[kind]
            name = str(payload.get("name") or payload.get("title") or "")
            entity = _entity(
                session,
                owner_id=owner_id,
                entity_type=entity_type,
                name=name,
                summary=payload.get("summary"),
                items=items,
            )
            target_type, target_id = "graph_entity", entity.id
            after = {"entity_id": entity.id, "entity_type": entity_type}
            evidence_item_ids = [item.id for item in items]
        elif kind == "update_goal_progress":
            goal = session.scalar(
                select(GraphEntity).where(
                    GraphEntity.id == str(payload.get("goal_id") or ""),
                    GraphEntity.owner_id == owner_id,
                    GraphEntity.entity_type == "goal",
                    GraphEntity.status == "active",
                )
            )
            if goal is None:
                raise AgentActionError("graph_entity_not_found", "The selected goal was not found.", 404)
            items = _source_items(session, owner_id=owner_id, item_ids=list(payload.get("source_item_ids") or []))
            summary = str(payload.get("summary") or "").strip()
            if not summary:
                raise AgentActionError("agent_summary_required", "Enter progress text.", 422)
            record = _entity(
                session,
                owner_id=owner_id,
                entity_type="growth_record",
                name=(payload.get("name") or goal.name + " progress")[:500],
                summary=summary,
                items=items,
            )
            relation = GraphRelation(
                owner_id=owner_id,
                from_entity_id=record.id,
                to_entity_id=goal.id,
                relation_type="supports_goal",
                confidence=0.9,
                status="active",
                created_by="agent",
            )
            session.add(relation)
            session.flush()
            target_type, target_id = "graph_entity", record.id
            after = {
                "entity_id": record.id,
                "entity_type": "growth_record",
                "relation_id": relation.id,
                "goal_id": goal.id,
            }
            evidence_item_ids = [item.id for item in items]
        elif kind == "create_review_draft":
            review, after = _review_draft(
                session, owner_id=owner_id, payload=payload, config=config, now=current
            )
            target_type, target_id = "review", review.id
            evidence_item_ids = after.pop("item_ids")
        else:
            raise AgentActionError("agent_action_unknown", "This agent action kind is not supported.", 422)
    except AgentActionError as error:
        session.rollback()
        raise _rejected(
            session,
            owner_id=owner_id,
            kind=kind,
            code=error.code,
            message=error.message,
            config=config,
            now=current,
            status_code=error.status_code,
        ) from error

    action = AgentAction(
        owner_id=owner_id,
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        before_json={},
        after_json=after,
        evidence_json=evidence_item_ids,
        status="active",
        approval="automatic",
        audit_json={
            "automatic": True,
            "kind": kind,
            "tool": tool_name,
            "evidence_count": len(evidence_item_ids),
        },
        expires_at=current + timedelta(hours=config.agent_undo_hours),
    )
    session.add(action)
    session.flush()
    return action


def undo_action(
    session: Session, *, owner_id: str, action_id: str, now: datetime | None = None
) -> AgentAction:
    current = now or utcnow()
    action = session.scalar(
        select(AgentAction).where(
            AgentAction.id == action_id,
            AgentAction.owner_id == owner_id,
        )
    )
    if action is None:
        raise AgentActionError("agent_action_not_found", "The agent action was not found.", 404)
    if action.status != "active":
        raise AgentActionError("agent_action_resolved", "This agent action is no longer active.", 409)
    if current >= action.expires_at:
        action.status = "expired"
        session.flush()
        raise AgentActionError("agent_action_expired", "The 24-hour undo window has expired.", 409, action)

    after = action.after_json or {}
    if action.target_type == "reminder":
        reminder = session.get(Reminder, action.target_id)
        if reminder is not None and reminder.owner_id == owner_id:
            reminder.status = "cancelled"
    elif action.target_type == "graph_entity":
        entity = session.get(GraphEntity, after.get("entity_id") or action.target_id)
        if entity is not None and entity.owner_id == owner_id:
            entity.status = "invalid"
        relation_id = after.get("relation_id")
        if relation_id:
            relation = session.get(GraphRelation, relation_id)
            if relation is not None and relation.owner_id == owner_id:
                relation.status = "invalid"
    elif action.target_type == "review":
        review = session.get(Review, action.target_id)
        if review is not None and review.owner_id == owner_id:
            review.status = "invalidated"
            review.final_text = None
            review.draft_json = {"notice": "An agent-created draft was undone by the user."}
            session.execute(
                update(BackgroundJob)
                .where(
                    BackgroundJob.review_id == review.id,
                    BackgroundJob.owner_id == owner_id,
                    BackgroundJob.status.in_(("queued", "running")),
                )
                .values(
                    status="cancelled",
                    error_code="agent_action_undone",
                    completed_at=current,
                    lease_expires_at=None,
                    worker_id=None,
                )
            )
    action.status = "undone"
    action.undone_at = current
    action.audit_json = {**(action.audit_json or {}), "undone": True, "undone_at": current.isoformat()}
    session.flush()
    return action


def list_actions(
    session: Session, *, owner_id: str, status: str | None = None, limit: int = 50
) -> list[AgentAction]:
    conditions = [AgentAction.owner_id == owner_id]
    if status:
        conditions.append(AgentAction.status == status)
    return list(
        session.scalars(
            select(AgentAction)
            .where(*conditions)
            .order_by(AgentAction.created_at.desc(), AgentAction.id)
            .limit(limit)
        )
    )


def action_payload(action: AgentAction, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or utcnow()
    return {
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
        "expires_at": action.expires_at,
        "undo_available": action.status == "active" and current < action.expires_at,
        "created_at": action.created_at,
        "undone_at": action.undone_at,
    }
