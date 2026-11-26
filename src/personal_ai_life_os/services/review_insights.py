"""Deterministic, source-linked review insights across periods."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_ai_life_os.models import GraphEntity, Review, SourceItem

EN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")
ZH_TERM = re.compile(r"[\u4e00-\u9fff]{2,8}")
STOP_WORDS = {
    "the", "and", "for", "with", "this", "that", "from", "have", "will", "into",
    "review", "weekly", "synthetic", "item", "record", "project", "plan", "next",
}
COMMITMENT_WORDS = (
    "承诺", "决定", "计划", "待办", "跟进", "到期", "deadline", "due", "commit",
    "decided", "will", "need to", "follow up",
)
WEEKDAYS = {
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}


def _keywords(text: str) -> list[str]:
    values = [match.group(0).casefold() for match in EN_WORD.finditer(text)]
    values.extend(match.group(0) for match in ZH_TERM.finditer(text))
    return [value for value in values if value not in STOP_WORDS and len(value) >= 3]


def _topic_counts(items: list[SourceItem]) -> tuple[Counter, dict[str, set[str]]]:
    counts: Counter = Counter()
    sources: dict[str, set[str]] = defaultdict(set)
    for item in items:
        for topic in set(_keywords(item.title + " " + item.content_text)):
            counts[topic] += 1
            sources[topic].add(item.id)
    return counts, sources


def _due_date(text: str, period_end: datetime) -> date | None:
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        try:
            return date(period_end.year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None
    lowered = text.casefold()
    for label, weekday in WEEKDAYS.items():
        if label in lowered:
            target = period_end.date() + timedelta(days=(weekday - period_end.weekday()) % 7 or 7)
            return target
    return None


def build_review_insights(session: Session, review: Review) -> dict:
    items = [item for item in review.source_items if item.deleted_at is None and item.is_current]
    current_counts, current_sources = _topic_counts(items)
    history = list(
        session.scalars(
            select(Review)
            .where(
                Review.owner_id == review.owner_id,
                Review.id != review.id,
                Review.period_end <= review.period_start,
                Review.status.in_(("draft", "confirmed")),
            )
            .order_by(Review.period_end.desc())
            .limit(8)
        )
    )
    previous_counts: Counter = Counter()
    for past in history:
        counts, _sources = _topic_counts(
            [item for item in past.source_items if item.deleted_at is None and item.is_current]
        )
        previous_counts.update(counts)

    trends = []
    for topic, count in current_counts.most_common(8):
        previous = previous_counts.get(topic, 0)
        if previous == 0 and count < 2:
            continue
        direction = "up" if count > previous else "down" if count < previous else "flat"
        trends.append(
            {
                "topic": topic,
                "current_count": count,
                "previous_count": previous,
                "direction": direction,
                "source_ids": sorted(current_sources[topic]),
            }
        )

    commitments = []
    for item in items:
        for sentence in re.split(r"[\n。；;!?！？]+", item.content_text):
            text = " ".join(sentence.split()).strip()
            if not text or len(text) > 500:
                continue
            if not any(word in text.casefold() for word in COMMITMENT_WORDS):
                continue
            due_date = _due_date(text, review.period_end)
            commitments.append(
                {
                    "text": text,
                    "due_date": due_date.isoformat() if due_date else None,
                    "source_ids": [item.id],
                }
            )
            if len(commitments) >= 20:
                break
        if len(commitments) >= 20:
            break

    goals = []
    active_goals = list(
        session.scalars(
            select(GraphEntity).where(
                GraphEntity.owner_id == review.owner_id,
                GraphEntity.entity_type == "goal",
                GraphEntity.status == "active",
            ).limit(100)
        )
    )
    for goal in active_goals:
        name = " ".join(goal.name.split()).casefold()
        if not name:
            continue
        matched = [
            item.id
            for item in items
            if name in (item.title + " " + item.content_text).casefold()
            or any(keyword in name for keyword in _keywords(item.title + " " + item.content_text))
        ]
        if matched:
            goals.append(
                {
                    "entity_id": goal.id,
                    "name": goal.name,
                    "source_ids": sorted(set(matched)),
                    "confidence": goal.confidence,
                }
            )
    return {"trends": trends, "commitments": commitments, "goals": goals}
