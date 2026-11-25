"""Explainable rule insights over the evidence graph."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import (
    GraphEntity,
    GraphEvidence,
    GraphRelation,
    InsightDismissal,
    SourceConnection,
    SourceItem,
    utcnow,
)

RULE_GOAL_DELAY = "goal_delay"
RULE_COMMITMENT_FOLLOW_UP = "commitment_follow_up"
RULE_PROJECT_STALLED = "project_stalled"
RULE_SKILL_EVIDENCE_GAP = "skill_evidence_gap"
RULES = {
    RULE_GOAL_DELAY: "目标延期/风险",
    RULE_COMMITMENT_FOLLOW_UP: "承诺到期/未跟进",
    RULE_PROJECT_STALLED: "项目停滞",
    RULE_SKILL_EVIDENCE_GAP: "技能证据不足",
}
DATE_PATTERN = re.compile(r"(\d{4})[-/](\d{2})[-/](\d{2})")
DUE_WORDS = ("截止", "到期", "之前", "前完成", "deadline", "due", "by ")


class InsightError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _parse_dates(text: str) -> list[datetime]:
    values: list[datetime] = []
    for year, month, day in DATE_PATTERN.findall(text):
        try:
            values.append(datetime(int(year), int(month), int(day), tzinfo=UTC))
        except ValueError:
            continue
    return values


def _has_due_word(text: str) -> bool:
    lowered = text.casefold()
    return any(word in lowered for word in DUE_WORDS)


def _days_since(moment: datetime, now: datetime) -> int:
    return max(0, int((now - moment).total_seconds() // 86400))


def _evidence_rows(
    session: Session, *, owner_id: str, entity_ids: list[str]
) -> dict[str, list[tuple[GraphEvidence, SourceItem, SourceConnection]]]:
    if not entity_ids:
        return {}
    rows = session.execute(
        select(GraphEvidence, SourceItem, SourceConnection)
        .join(SourceItem, SourceItem.id == GraphEvidence.source_item_id)
        .join(SourceConnection, SourceConnection.id == GraphEvidence.source_id)
        .where(
            GraphEvidence.owner_id == owner_id,
            GraphEvidence.entity_id.in_(entity_ids),
            GraphEvidence.availability == "active",
            SourceItem.owner_id == owner_id,
            SourceItem.deleted_at.is_(None),
            SourceItem.is_current.is_(True),
            SourceConnection.owner_id == owner_id,
            SourceConnection.status.in_(("active", "paused")),
        )
        .order_by(GraphEvidence.created_at.desc())
    ).all()
    grouped: dict[str, list[tuple[GraphEvidence, SourceItem, SourceConnection]]] = defaultdict(list)
    for evidence, item, source in rows:
        if evidence.entity_id:
            grouped[evidence.entity_id].append((evidence, item, source))
    return grouped


def _relation_types(
    session: Session, *, owner_id: str, entity_ids: list[str]
) -> dict[str, set[str]]:
    if not entity_ids:
        return {}
    relations = session.scalars(
        select(GraphRelation).where(
            GraphRelation.owner_id == owner_id,
            GraphRelation.status == "active",
            (GraphRelation.from_entity_id.in_(entity_ids))
            | (GraphRelation.to_entity_id.in_(entity_ids)),
        )
    )
    result: dict[str, set[str]] = defaultdict(set)
    for relation in relations:
        if relation.from_entity_id in entity_ids:
            result[relation.from_entity_id].add(relation.relation_type)
        if relation.to_entity_id in entity_ids:
            result[relation.to_entity_id].add(relation.relation_type)
    return result


def _latest_activity(
    entity: GraphEntity,
    evidence: list[tuple[GraphEvidence, SourceItem, SourceConnection]],
    now: datetime,
) -> datetime | None:
    candidates: list[datetime] = []
    text = (entity.summary or "") + " " + " ".join(row[0].quote for row in evidence)
    candidates.extend(_parse_dates(text))
    for _evidence, item, _source in evidence:
        if item.occurred_at is not None:
            candidates.append(item.occurred_at)
    future = [value for value in candidates if value <= now]
    return max(future) if future else (max(candidates) if candidates else None)


def _evidence_payload(
    entity_id: str,
    evidence: list[tuple[GraphEvidence, SourceItem, SourceConnection]],
) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": row[0].id,
            "quote": row[0].quote,
            "confidence": round(float(row[0].confidence), 3),
            "source_id": row[0].source_id,
            "source_name": row[2].name,
            "source_item_id": row[0].source_item_id,
            "item_title": row[1].title,
            "occurred_at": row[1].occurred_at.isoformat() if row[1].occurred_at else None,
        }
        for row in evidence[:5]
        if row[0].entity_id == entity_id
    ]


def _insight(
    *,
    rule: str,
    entity: GraphEntity,
    severity: str,
    confidence: float,
    trigger: str,
    evidence: list[tuple[GraphEvidence, SourceItem, SourceConnection]],
    suggestion: str,
) -> dict[str, Any]:
    return {
        "insight_key": rule + ":" + entity.id,
        "rule": rule,
        "rule_label": RULES[rule],
        "entity_id": entity.id,
        "entity_type": entity.entity_type,
        "entity_name": entity.name,
        "severity": severity,
        "confidence": round(confidence, 3),
        "trigger": trigger,
        "evidence": _evidence_payload(entity.id, evidence),
        "suggestion": suggestion,
    }


def _evaluate_entity(
    entity: GraphEntity,
    evidence: list[tuple[GraphEvidence, SourceItem, SourceConnection]],
    relation_types: set[str],
    *,
    config: Settings,
    now: datetime,
) -> dict[str, Any] | None:
    latest = _latest_activity(entity, evidence, now)
    stale_days = _days_since(latest, now) if latest else None
    text = (entity.summary or "") + " " + " ".join(row[0].quote for row in evidence)
    dates = _parse_dates(text)
    due_dates = [value for value in dates if value < now] if _has_due_word(text) else []
    overdue = bool(due_dates) and (latest is None or latest <= max(due_dates))

    if entity.entity_type == "goal":
        if overdue:
            return _insight(
                rule=RULE_GOAL_DELAY,
                entity=entity,
                severity="high",
                confidence=0.9,
                trigger="目标的截止日期已过，之后没有新的进展证据。",
                evidence=evidence,
                suggestion="确认目标是否仍然有效，并补充新的进展或调整截止日期。",
            )
        if latest is None:
            return _insight(
                rule=RULE_GOAL_DELAY,
                entity=entity,
                severity="medium",
                confidence=0.65,
                trigger="目标没有可用的进展证据。",
                evidence=evidence,
                suggestion="为目标补充第一条可引用的进展证据。",
            )
        if stale_days is not None and stale_days > config.insight_stale_days:
            return _insight(
                rule=RULE_GOAL_DELAY,
                entity=entity,
                severity="medium",
                confidence=0.7,
                trigger=f"最近 {stale_days} 天没有新的目标进展证据。",
                evidence=evidence,
                suggestion="检查目标风险，补充进展或把目标标记为完成/暂停。",
            )
        return None

    if entity.entity_type == "commitment":
        if overdue:
            return _insight(
                rule=RULE_COMMITMENT_FOLLOW_UP,
                entity=entity,
                severity="high",
                confidence=0.88,
                trigger="承诺的到期日期已过，之后没有后续证据。",
                evidence=evidence,
                suggestion="确认承诺是否完成，必要时创建提醒或补充跟进记录。",
            )
        if latest is None or (stale_days is not None and stale_days > config.insight_stale_days):
            return _insight(
                rule=RULE_COMMITMENT_FOLLOW_UP,
                entity=entity,
                severity="medium",
                confidence=0.7,
                trigger="承诺长期没有新的跟进证据。",
                evidence=evidence,
                suggestion="回访这条承诺，补充结果或取消不再需要的承诺。",
            )
        return None

    if entity.entity_type == "project":
        has_structure = bool(relation_types & {"has_goal", "has_task"})
        if not has_structure and not relation_types:
            return _insight(
                rule=RULE_PROJECT_STALLED,
                entity=entity,
                severity="low",
                confidence=0.6,
                trigger="项目没有目标或任务关系，结构可能不完整。",
                evidence=evidence,
                suggestion="为项目添加目标或任务关系，明确下一步。",
            )
        if latest is None or (stale_days is not None and stale_days > config.insight_stale_days):
            return _insight(
                rule=RULE_PROJECT_STALLED,
                entity=entity,
                severity="medium",
                confidence=0.72,
                trigger="项目长期没有新的证据或状态更新。",
                evidence=evidence,
                suggestion="更新项目状态，补充新证据或结束停滞的项目。",
            )
        return None

    if entity.entity_type == "skill":
        if len(evidence) < config.insight_skill_min_evidence:
            return _insight(
                rule=RULE_SKILL_EVIDENCE_GAP,
                entity=entity,
                severity="low",
                confidence=0.62,
                trigger=f"技能只有 {len(evidence)} 条证据，低于 {config.insight_skill_min_evidence} 条。",
                evidence=evidence,
                suggestion="补充练习、项目或成长记录作为技能证据。",
            )
        if latest is None or (
            stale_days is not None and stale_days > config.insight_skill_stale_days
        ):
            return _insight(
                rule=RULE_SKILL_EVIDENCE_GAP,
                entity=entity,
                severity="low",
                confidence=0.58,
                trigger="技能长期没有新的练习或成长证据。",
                evidence=evidence,
                suggestion="安排一次练习，并记录新的成长证据。",
            )
    return None


def evaluate_rules(
    session: Session,
    *,
    owner_id: str,
    config: Settings,
    now: datetime | None = None,
    include_dismissed: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    current = now or utcnow()
    entities = list(
        session.scalars(
            select(GraphEntity).where(
                GraphEntity.owner_id == owner_id,
                GraphEntity.status == "active",
                GraphEntity.entity_type.in_(("goal", "commitment", "project", "skill")),
            )
        )
    )
    entity_ids = [entity.id for entity in entities]
    evidence_map = _evidence_rows(session, owner_id=owner_id, entity_ids=entity_ids)
    relation_map = _relation_types(session, owner_id=owner_id, entity_ids=entity_ids)
    dismissals = {
        dismissal.insight_key: dismissal
        for dismissal in session.scalars(
            select(InsightDismissal).where(InsightDismissal.owner_id == owner_id)
        )
    }
    insights: list[dict[str, Any]] = []
    dismissed_count = 0
    for entity in entities:
        insight = _evaluate_entity(
            entity,
            evidence_map.get(entity.id, []),
            relation_map.get(entity.id, set()),
            config=config,
            now=current,
        )
        if insight is None:
            continue
        dismissal = dismissals.get(insight["insight_key"])
        insight["dismissed"] = dismissal is not None
        insight["dismissed_reason"] = dismissal.reason if dismissal else None
        if dismissal is not None:
            dismissed_count += 1
            if not include_dismissed:
                continue
        insights.append(insight)
    insights.sort(key=lambda item: (item["severity"] != "high", item["severity"] != "medium", -item["confidence"]))
    return insights, dismissed_count


def dismiss_insight(
    session: Session,
    *,
    owner_id: str,
    insight_key: str,
    rule: str,
    entity_id: str | None = None,
    reason: str | None = None,
) -> InsightDismissal:
    if not insight_key.strip() or rule not in RULES:
        raise InsightError("invalid_insight", "Choose a valid insight to dismiss.")
    existing = session.scalar(
        select(InsightDismissal).where(
            InsightDismissal.owner_id == owner_id,
            InsightDismissal.insight_key == insight_key,
        )
    )
    if existing is not None:
        if reason:
            existing.reason = reason[:500]
        session.flush()
        return existing
    dismissal = InsightDismissal(
        owner_id=owner_id,
        insight_key=insight_key[:240],
        rule=rule,
        entity_id=entity_id,
        reason=reason[:500] if reason else None,
    )
    session.add(dismissal)
    session.flush()
    return dismissal


def restore_insight(session: Session, *, owner_id: str, insight_key: str) -> bool:
    result = session.execute(
        delete(InsightDismissal).where(
            InsightDismissal.owner_id == owner_id,
            InsightDismissal.insight_key == insight_key,
        )
    )
    session.flush()
    return bool(result.rowcount)
