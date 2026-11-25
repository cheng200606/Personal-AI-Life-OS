# Development Milestones

This status reflects repository implementation and local checks. It does not mean a hosted system, real-user beta, or production security review has been completed.

## M0 — Repository foundation: implemented

- Apache-2.0 license, contribution/security docs, product/architecture decisions, synthetic fixtures, Ruff/pytest, and GitHub Actions.
- FastAPI startup, health/readiness routes, Python containers, local Compose stack, and web build/lint CI steps.
- Windows API-only development and Linux CI paths are documented. GitHub Actions passed the Python 3.11/3.12 matrix and Docker Compose build/readiness smoke; local container execution remains dependent on an available Docker engine.

## M1 — Local import and persistence: implemented

- SQLAlchemy models, Alembic migrations, owner-scoped authentication and APIs, local/S3 storage adapters.
- CLI preview, explicit conversation selection, minimized ChatGPT upload, sync, retry-safe hashing, and conflict-safe Markdown export.
- UTF-8 Markdown and supported ChatGPT JSON parsers; source and account deletion with durable tombstone replay.
- Automated tests cover parser behavior, idempotency, owner isolation, import/export, deletion, and account archive.

## M2a — Searchable timeline implemented; text Alpha study pending

- React/TypeScript web application for authentication, selected imports, source management, timeline filtering/search, provenance inspection, and Markdown export.
- CLI and web paths work without Swagger. Keyword search is a bounded SQL `LIKE` query; full-text and semantic search remain post-MVP.
- Browser workflow, keyboard accessibility, Obsidian compatibility, and participant outcomes need dedicated acceptance evidence.

## M3 — Reviews and reminders: implemented

- On-demand weekly review, cited template output, optional consent-gated OpenAI review, output citation validation, model-failure fallback, and Markdown export.
- User can edit/confirm review text and create, complete, snooze, or cancel reminders.
- Review suggestions can be edited, dismissed, or restored while the review is a draft; dismissed items are excluded from the rendered review until restored.
- Synthetic fixture includes 30 review cases. Local deterministic evidence evaluation and API tests verify citation and fallback behavior.

## M4 — Text private beta readiness: implementation present; hosted gates pending

- Invitation-only production configuration, private S3 adapter, Caddy TLS template, account archive/delete, metrics, backup/restore scripts, and operational checklists are in the repository.
- Two-owner API tests cover isolation; source/account deletion replay is exercised with synthetic data.
- **Pending:** actual TLS/DNS and cloud configuration, private bucket policy and lifecycle verification, hosted database/object authorization tests, production dashboards, backup restore exercise, and review by an operator before inviting real users.
- **Solo-local scope:** shared-original deletion is covered by tests and explicit UI wording; the maintainer confirmed that prompt on 2026-11-25. Hosted gates and the first-user study are not current targets.

## M2b — Photo implementation present; end-to-end acceptance pending

- User-selected JPEG, PNG, and WebP imports, including up to ten files or a selected directory, local preview, capture date/timezone form for a single photo, metadata stripping, searchable OCR, source references, and optional consent-gated photo description.
- Database-backed leased jobs cover photo OCR, requested external weekly reviews, and requested photo descriptions. Job status, retry controls, source/consent cancellation, and queue metrics are implemented.
- Synthetic tests cover EXIF/GPS stripping, OCR behavior, descriptions, search, access scope, and deletion.
- **Pending:** browser file/folder batch acceptance, real OCR in the target image, worker recovery coverage, hosted privacy and deletion verification, and the shared release gates in M4.

## Release and follow-up

Use the [release checklist](../operations/release-checklist.md) and [support matrix](../operations/support-matrix.md) to review evidence and limits. Invite users only after hosted acceptance checks and recovery exercises have actually passed. Scheduled imports/reviews, more connectors, full-text/vector search, and mobile capture remain post-MVP.
