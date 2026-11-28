"""Owner-scoped unified search across timeline items, reviews, and reminders."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    SearchReminderGroup,
    SearchReminderResult,
    SearchResponse,
    SearchReviewGroup,
    SearchReviewResult,
    SearchTimelineGroup,
    SearchTimelineResult,
)
from personal_ai_life_os.models import Reminder, Review, SourceConnection, SourceItem

router = APIRouter(prefix="/search", tags=["search"])
SNIPPET_LIMIT = 200
ELLIPSIS = "\u2026"


def _snippet(text: str | None, query: str, *, fallback: str = "") -> str:
    """Return a bounded window around the first match, never the full long body."""
    normalized = " ".join((text or "").split()) or " ".join((fallback or "").split())
    if not normalized:
        return ""
    match_at = normalized.casefold().find(query.casefold())
    if match_at < 0:
        head = normalized[:SNIPPET_LIMIT]
        return head if len(head) == len(normalized) else head[: SNIPPET_LIMIT - 1].rstrip() + ELLIPSIS
    match_end = match_at + len(query)
    if len(normalized) <= SNIPPET_LIMIT:
        return normalized
    if len(query) >= SNIPPET_LIMIT:
        return normalized[match_at:match_end]

    # Keep the whole match and spend the remaining budget on both sides, trimming
    # context or a marker so the result never exceeds SNIPPET_LIMIT characters.
    budget = SNIPPET_LIMIT - len(query)
    before = min(match_at, budget // 2)
    after = min(len(normalized) - match_end, budget - before)
    before = min(match_at, budget - after)
    start = match_at - before
    end = match_end + after
    prefix = ELLIPSIS if start > 0 else ""
    suffix = ELLIPSIS if end < len(normalized) else ""
    while len(prefix) + (end - start) + len(suffix) > SNIPPET_LIMIT:
        if after > 0:
            after -= 1
            end -= 1
        elif before > 0:
            before -= 1
            start += 1
        elif prefix:
            prefix = ""
        elif suffix:
            suffix = ""
        else:
            break
    return prefix + normalized[start:end].strip() + suffix


def _timeline_snippet(item: SourceItem, query: str) -> str:
    metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
    description = metadata.get("user_description")
    candidates = [item.content_text or ""]
    if isinstance(description, str):
        candidates.append(description)
    for candidate in candidates:
        if candidate and query.casefold() in candidate.casefold():
            return _snippet(candidate, query, fallback=item.title)
    return _snippet(item.content_text, query, fallback=item.title)


def _search_timeline(session: Session, owner_id: str, query: str, limit: int) -> SearchTimelineGroup:
    conditions = [
        SourceItem.owner_id == owner_id,
        SourceItem.deleted_at.is_(None),
        SourceItem.is_current.is_(True),
        SourceConnection.status != "deleting",
        or_(
            SourceItem.title.icontains(query),
            SourceItem.content_text.icontains(query),
            SourceItem.metadata_json["user_description"].as_string().icontains(query),
        ),
    ]
    base = (
        select(SourceItem, SourceConnection.name)
        .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
        .where(*conditions)
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.execute(
        base.order_by(
            case((SourceItem.title.icontains(query), 0), else_=1),
            SourceItem.occurred_at.is_(None),
            SourceItem.occurred_at.desc(),
            SourceItem.id,
        ).limit(limit)
    ).all()
    return SearchTimelineGroup(
        total=total,
        results=[
            SearchTimelineResult(
                id=item.id,
                source_id=item.source_id,
                source_name=source_name,
                title=item.title,
                snippet=_timeline_snippet(item, query),
                occurred_at=item.occurred_at,
                kind=item.kind,
            )
            for item, source_name in rows
        ],
    )


def _search_reviews(session: Session, owner_id: str, query: str, limit: int) -> SearchReviewGroup:
    conditions = [
        Review.owner_id == owner_id,
        Review.status != "invalidated",
        Review.final_text.icontains(query),
    ]
    base = select(Review).where(*conditions)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    reviews = list(
        session.scalars(base.order_by(Review.period_end.desc(), Review.id).limit(limit))
    )
    return SearchReviewGroup(
        total=total,
        results=[
            SearchReviewResult(
                id=review.id,
                period_start=review.period_start,
                period_end=review.period_end,
                status=review.status,
                snippet=_snippet(review.final_text, query),
                updated_at=review.updated_at,
            )
            for review in reviews
        ],
    )


def _search_reminders(
    session: Session, owner_id: str, query: str, limit: int
) -> SearchReminderGroup:
    conditions = [
        Reminder.owner_id == owner_id,
        or_(Reminder.title.icontains(query), Reminder.notes.icontains(query)),
    ]
    base = select(Reminder).where(*conditions)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    reminders = list(
        session.scalars(
            base.order_by(
                Reminder.due_at.is_(None),
                Reminder.due_at.asc(),
                Reminder.updated_at.desc(),
                Reminder.id,
            ).limit(limit)
        )
    )
    return SearchReminderGroup(
        total=total,
        results=[
            SearchReminderResult(
                id=reminder.id,
                title=reminder.title,
                snippet=_snippet(reminder.notes, query, fallback=reminder.title),
                due_at=reminder.due_at,
                status=reminder.status,
            )
            for reminder in reminders
        ],
    )


@router.get("", response_model=SearchResponse)
def search(
    user: CurrentUserDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> SearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(
            422,
            detail={"code": "invalid_search_query", "message": "Enter a search query."},
        )
    return SearchResponse(
        query=query,
        timeline=_search_timeline(session, user.id, query, limit),
        reviews=_search_reviews(session, user.id, query, limit),
        reminders=_search_reminders(session, user.id, query, limit),
    )
