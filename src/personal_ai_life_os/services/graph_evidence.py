"""Graph evidence availability updates tied to source lifecycle."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from personal_ai_life_os.models import GraphEvidence


def mark_source_evidence_unavailable(
    session: Session,
    *,
    owner_id: str,
    source_id: str,
    availability: str,
) -> None:
    """Keep evidence rows for history while excluding them from extraction and Q&A."""
    session.execute(
        update(GraphEvidence)
        .where(
            GraphEvidence.owner_id == owner_id,
            GraphEvidence.source_id == source_id,
            GraphEvidence.availability == "active",
        )
        .values(availability=availability)
    )
