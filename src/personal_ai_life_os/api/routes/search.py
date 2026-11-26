"""Owner-scoped unified search across timeline items, reviews, and reminders."""

from datetime import UTC, date, datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    SearchFilters,
    SearchReminderGroup,
    SearchReminderResult,
    SearchResponse,
    SearchReviewGroup,
    SearchReviewResult,
    SearchTimelineGroup,
    SearchTimelineResult,
)
from personal_ai_life_os.models import Reminder, Review, SourceConnection, SourceItem
from personal_ai_life_os.services.search_index import fts_candidate_filter, search_backend

router = APIRouter(prefix="/search", tags=["search"])
SNIPPET_LIMIT = 200
ELLIPSIS = "\u2026"


def _snippet(text: str | None, query: str, *, fallback: str = "") -> str:
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


def _date_bounds(filters: SearchFilters, timezone_name: str) -> tuple[datetime | None, datetime | None]:
    zone = ZoneInfo(timezone_name)
    start_at = datetime.combine(filters.start, time.min, tzinfo=zone).astimezone(UTC) if filters.start else None
    end_at = datetime.combine(filters.end, time.min, tzinfo=zone).astimezone(UTC) if filters.end else None
    return start_at, end_at


def _search_timeline(
    session: Session,
    owner_id: str,
    query: str,
    limit: int,
    filters: SearchFilters,
    timezone_name: str,
) -> SearchTimelineGroup:
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
    candidate = fts_candidate_filter(session, "timeline_fts", SourceItem.id, query)
    if candidate is not None:
        conditions.append(candidate)
    start_at, end_at = _date_bounds(filters, timezone_name)
    if start_at:
        conditions.append(SourceItem.occurred_at >= start_at)
    if end_at:
        conditions.append(SourceItem.occurred_at < end_at)
    if filters.source_id:
        conditions.append(SourceItem.source_id == filters.source_id)
    if filters.tag_id:
        conditions.append(SourceItem.tags.any(id=filters.tag_id))
    if filters.collection_id:
        conditions.append(SourceItem.collections.any(id=filters.collection_id))
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


def _search_reviews(
    session: Session,
    owner_id: str,
    query: str,
    limit: int,
    filters: SearchFilters,
    timezone_name: str,
) -> SearchReviewGroup:
    conditions = [
        Review.owner_id == owner_id,
        Review.status != "invalidated",
        Review.final_text.icontains(query),
    ]
    candidate = fts_candidate_filter(session, "review_fts", Review.id, query, "record_id")
    if candidate is not None:
        conditions.append(candidate)
    start_at, end_at = _date_bounds(filters, timezone_name)
    if start_at:
        conditions.append(Review.period_end > start_at)
    if end_at:
        conditions.append(Review.period_start < end_at)
    if filters.status:
        conditions.append(Review.status.in_(filters.status))
    base = select(Review).where(*conditions)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    reviews = list(session.scalars(base.order_by(Review.period_end.desc(), Review.id).limit(limit)))
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
    session: Session,
    owner_id: str,
    query: str,
    limit: int,
    filters: SearchFilters,
    timezone_name: str,
) -> SearchReminderGroup:
    conditions = [
        Reminder.owner_id == owner_id,
        or_(Reminder.title.icontains(query), Reminder.notes.icontains(query)),
    ]
    candidate = fts_candidate_filter(session, "reminder_fts", Reminder.id, query, "record_id")
    if candidate is not None:
        conditions.append(candidate)
    start_at, end_at = _date_bounds(filters, timezone_name)
    if start_at:
        conditions.append(Reminder.due_at >= start_at)
    if end_at:
        conditions.append(Reminder.due_at < end_at)
    if filters.status:
        conditions.append(Reminder.status.in_(filters.status))
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


def _split_values(value: str | None) -> list[str]:
    return list(dict.fromkeys(part.strip() for part in (value or "").split(",") if part.strip()))


@router.get("", response_model=SearchResponse)
def search(
    user: CurrentUserDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    types: Annotated[str | None, Query(max_length=80)] = None,
    start: date | None = None,
    end: date | None = None,
    source_id: Annotated[str | None, Query(max_length=64)] = None,
    status: Annotated[str | None, Query(max_length=160)] = None,
    tag_id: Annotated[str | None, Query(max_length=64)] = None,
    collection_id: Annotated[str | None, Query(max_length=64)] = None,
) -> SearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(
            422,
            detail={"code": "invalid_search_query", "message": "Enter a search query."},
        )
    try:
        filters = SearchFilters(
            types=_split_values(types) or ["timeline", "reviews", "reminders"],
            start=start,
            end=end,
            source_id=source_id,
            status=_split_values(status),
            tag_id=tag_id,
            collection_id=collection_id,
        )
    except ValidationError as error:
        raise HTTPException(
            422,
            detail={"code": "invalid_search_filters", "message": error.errors()[0]["msg"]},
        ) from error
    return SearchResponse(
        query=query,
        index_backend=search_backend(session),
        timeline=(
            _search_timeline(session, user.id, query, limit, filters, user.timezone)
            if "timeline" in filters.types
            else SearchTimelineGroup(total=0, results=[])
        ),
        reviews=(
            _search_reviews(session, user.id, query, limit, filters, user.timezone)
            if "reviews" in filters.types
            else SearchReviewGroup(total=0, results=[])
        ),
        reminders=(
            _search_reminders(session, user.id, query, limit, filters, user.timezone)
            if "reminders" in filters.types
            else SearchReminderGroup(total=0, results=[])
        ),
    )
