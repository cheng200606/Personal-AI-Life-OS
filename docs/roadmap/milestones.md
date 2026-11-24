# Development Milestones

## M0 — Repository foundation (current)

- Apache-2.0 license, contribution/security docs, and product/architecture decisions.
- FastAPI package, health route, Docker Compose dependencies, and container recipe.
- Source consent, provenance, and data portability principles.

## M1 — Local import and persistence

- Add SQLAlchemy models and Alembic migrations for users, source connections, sync runs, and source items.
- Implement authenticated upload and an allowlisted local sync CLI.
- Parse ChatGPT export JSON and Markdown memory files.
- Add content hashing, duplicate detection, retryable sync runs, and deletion.

## M2 — Searchable timeline

- Add photo metadata and optional image description pipeline.
- Add editable event and decision drafts with source citations.
- Add basic web UI for source management and timeline review.
- Add text and semantic search.

## M3 — Reviews and reminders

- Generate an on-demand weekly review from confirmed records.
- Let users edit/save reviews and confirm action items.
- Add in-app reminders with due date, snooze, and completion state.
- Add Obsidian Markdown export with conflict-safe writes.

## M4 — Private beta readiness

- Add robust authentication, tenant isolation checks, audit events, retention controls, export, and account deletion.
- Document model providers, data flows, backup deletion windows, and deployment.
- Add observability that avoids logging source content.
- Invite early users after security and data-control workflows are implemented.
