"""Rebuild the configured search candidate index from authoritative rows."""

import json

from sqlalchemy import func, select

from personal_ai_life_os.config import Settings
from personal_ai_life_os.db import create_database_engine, create_session_factory
from personal_ai_life_os.models import Reminder, Review, SourceItem
from personal_ai_life_os.services.search_index import rebuild_search_index


def main() -> int:
    config = Settings()
    engine = create_database_engine(config)
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as session:
            backend = rebuild_search_index(session)
            report = {
                "backend": backend,
                "timeline_items": session.scalar(
                    select(func.count()).select_from(SourceItem).where(
                        SourceItem.is_current.is_(True), SourceItem.deleted_at.is_(None)
                    )
                )
                or 0,
                "reviews": session.scalar(
                    select(func.count()).select_from(Review).where(Review.status != "invalidated")
                )
                or 0,
                "reminders": session.scalar(select(func.count()).select_from(Reminder)) or 0,
            }
        print(json.dumps(report, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
