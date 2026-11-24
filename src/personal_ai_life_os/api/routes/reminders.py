"""Owner-scoped application reminders."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    ReminderCreateRequest,
    ReminderResponse,
    ReminderStatusRequest,
)
from personal_ai_life_os.models import Reminder, SourceConnection, SourceItem

router = APIRouter(prefix="/reminders", tags=["reminders"])
ALLOWED_TRANSITIONS = {
    "pending": {"completed", "snoozed", "cancelled"},
    "snoozed": {"pending", "completed", "cancelled"},
    "completed": {"pending", "cancelled"},
    "cancelled": {"pending"},
}


@router.get("", response_model=list[ReminderResponse])
def list_reminders(user: CurrentUserDep, session: SessionDep) -> list[Reminder]:
    return list(
        session.scalars(
            select(Reminder)
            .where(Reminder.owner_id == user.id)
            .order_by(Reminder.due_at.is_(None), Reminder.due_at, Reminder.created_at.desc())
        )
    )


@router.post("", response_model=ReminderResponse, status_code=201)
def create_reminder(
    payload: ReminderCreateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> Reminder:
    source_items: list[SourceItem] = []
    if payload.source_item_ids:
        source_items = list(
            session.scalars(
                select(SourceItem)
                .join(SourceConnection, SourceConnection.id == SourceItem.source_id)
                .where(
                    SourceItem.id.in_(payload.source_item_ids),
                    SourceItem.owner_id == user.id,
                    SourceItem.deleted_at.is_(None),
                    SourceItem.is_current.is_(True),
                    SourceConnection.status.in_(("active", "paused", "revoked")),
                )
            )
        )
        if {item.id for item in source_items} != set(payload.source_item_ids):
            raise HTTPException(
                404,
                detail={"code": "source_item_not_found", "message": "One or more cited source items were not found."},
            )
    reminder = Reminder(
        owner_id=user.id,
        title=payload.title.strip(),
        notes=payload.notes,
        due_at=payload.due_at,
        status="pending",
        source_items=source_items,
    )
    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return reminder


@router.patch("/{reminder_id}/status", response_model=ReminderResponse)
def update_reminder_status(
    reminder_id: str,
    payload: ReminderStatusRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> Reminder:
    reminder = session.scalar(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.owner_id == user.id)
    )
    if reminder is None:
        raise HTTPException(404, detail={"code": "reminder_not_found", "message": "The reminder was not found."})
    if payload.status not in ALLOWED_TRANSITIONS[reminder.status]:
        raise HTTPException(
            409,
            detail={"code": "invalid_reminder_transition", "message": "This reminder cannot move to the requested status."},
        )
    reminder.status = payload.status
    if payload.status == "snoozed" and reminder.due_at is not None:
        reminder.due_at = reminder.due_at + timedelta(days=1)
    reminder.updated_at = datetime.now(UTC)
    session.commit()
    session.refresh(reminder)
    return reminder
