"""Owner-scoped ontology proposals, approvals, and extraction vocabulary."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_ai_life_os.models import OntologyType, utcnow

KINDS = ("entity", "relation")
STATUSES = ("proposed", "approved", "rejected")
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class OntologyError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def validate_name(value: str) -> str:
    name = value.strip().lower()
    if not NAME_PATTERN.fullmatch(name):
        raise OntologyError(
            "invalid_ontology_name",
            "Use 2-64 lowercase letters, digits, or underscores, starting with a letter.",
            422,
        )
    return name


def list_types(
    session: Session,
    *,
    owner_id: str,
    kind: str | None = None,
    status: str | None = None,
) -> list[OntologyType]:
    conditions = [OntologyType.owner_id == owner_id]
    if kind:
        conditions.append(OntologyType.kind == kind)
    if status:
        conditions.append(OntologyType.status == status)
    return list(
        session.scalars(
            select(OntologyType)
            .where(*conditions)
            .order_by(OntologyType.kind, OntologyType.name)
        )
    )


def _type_or_404(session: Session, owner_id: str, type_id: str) -> OntologyType:
    entry = session.scalar(
        select(OntologyType).where(
            OntologyType.id == type_id,
            OntologyType.owner_id == owner_id,
        )
    )
    if entry is None:
        raise OntologyError("ontology_type_not_found", "The ontology type was not found.", 404)
    return entry


def create_type(
    session: Session,
    *,
    owner_id: str,
    kind: str,
    name: str,
    description: str | None = None,
    source: str = "user",
    created_by: str = "user",
) -> OntologyType:
    if kind not in KINDS:
        raise OntologyError("invalid_ontology_kind", "Choose entity or relation.", 422)
    normalized = validate_name(name)
    existing = session.scalar(
        select(OntologyType).where(
            OntologyType.owner_id == owner_id,
            OntologyType.kind == kind,
            OntologyType.name == normalized,
        )
    )
    if existing is not None:
        raise OntologyError(
            "ontology_type_exists",
            "This type already exists. Review its current status instead.",
        )
    entry = OntologyType(
        owner_id=owner_id,
        kind=kind,
        name=normalized,
        description=description,
        status="proposed",
        source=source,
        created_by=created_by,
        version=1,
    )
    session.add(entry)
    session.flush()
    return entry


def set_status(
    session: Session, *, owner_id: str, type_id: str, status: str
) -> OntologyType:
    if status not in ("approved", "rejected"):
        raise OntologyError("invalid_ontology_status", "Choose approve or reject.", 422)
    entry = _type_or_404(session, owner_id, type_id)
    if entry.status != "proposed":
        raise OntologyError(
            "ontology_type_resolved",
            "This type has already been approved or rejected.",
        )
    entry.status = status
    entry.version += 1
    entry.updated_at = utcnow()
    session.flush()
    return entry


def approved_names(session: Session, *, owner_id: str, kind: str) -> set[str]:
    return set(
        session.scalars(
            select(OntologyType.name).where(
                OntologyType.owner_id == owner_id,
                OntologyType.kind == kind,
                OntologyType.status == "approved",
            )
        )
    )
