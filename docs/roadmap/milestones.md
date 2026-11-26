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

## M5 — Unified search: implemented

- `GET /api/v1/search` returns owner-scoped, case-insensitive substring matches grouped by timeline items, weekly reviews, and reminders, with per-group totals, 10 results by default and at most 20, title-first ordering, and snippets capped at 200 characters. Deleted, non-current, `deleting`-source timeline entries and `invalidated` reviews are excluded.
- The web client adds a keyboard-accessible Search page with grouped results, jump links to the timeline item, review card, or reminder, and loading, empty, no-result, and error states that keep the entered query.
- `scripts/evaluate_search.py` runs 22 bilingual queries against 10,000 synthetic timeline rows plus reviews and reminders. On local SQLite, hit@5 is 1.0 in every group and query P95 is about 59–63 ms against a 500 ms target.
- **Boundaries:** PostgreSQL was not measured because Docker is unavailable, and the measurements use synthetic data. Full-text and vector search, saved searches, and cross-group relevance ranking remain post-MVP.

## M6 — Automated review and reminder loop: implemented

- `ReviewSchedule` stores the owner's weekday, local time, timezone, enabled state, external-model preference, last run, next run, and last generated review. `GET/PUT /api/v1/review-schedule` validates and persists it.
- The worker scheduler atomically claims due schedules and generates at most one draft per local weekly period. It uses only active sources, skips periods with no items, honors deletion/pause, and falls back to the cited template when provider consent, consent version, or per-call budget is unavailable. In worker mode, external drafts are queued through the existing `weekly_review` job.
- The web client adds a weekly schedule panel, a sidebar badge for due/overdue reminders, a "Due now" panel, and a scheduled-review-ready notice.
- `scripts/register-scheduled-sync.ps1` registers the existing idempotent `lifeos sync <folder> --yes` command as a daily Windows Task Scheduler task with a log file.
- Tests cover defaults, validation, owner isolation, local-period idempotency, existing-period reuse, disabled/paused sources, consent fallback, budget fallback, and worker-job enqueue. Full Python suite: 68 passed; browser suite: 2 passed.
- **Boundaries:** scheduled review generation requires `PROCESSING_MODE=worker`; notifications are in-app only; scheduled sync depends on the API running and the OS task; there is no email/push or server-side filesystem watcher.

## v0.5 — Evidence graph, Q&A, insights, agent, and plugins: implemented

- Evidence graph extraction accepts Claude/Gemini/ZCode/DeepSeek harness/WorkBuddy JSON/JSONL or Markdown plus TXT, text-based PDF, and DOCX. Cloud extraction is source-level opt-in; revoked evidence is excluded and deleted sources cascade-delete evidence.
- Low-confidence review supports edit, approve, reject, and bulk decisions. Entity merges keep aliases and a reversible snapshot; approved custom ontology types enter later extraction prompts. The timeline and pending page show review counts inline.
- The Chinese-first Ask page retrieves graph evidence, timeline items, and reviews with source/project/topic/date scope, remembers the last scope, and returns facts, citations, confidence, fact/inference/uncertain labels, missing information, and suggestions. Threads are stored locally and can be exported or deleted.
- Four explainable rule insights cover goals, commitments, projects, and skills; false positives can be dismissed and restored without repeating.
- Agent actions create reminders, tasks, projects, growth records, goal progress, and review drafts with audit metadata and a 24-hour undo. The tool policy layer rejects external sending, file changes, spending, and deletion or goal changes without explicit approval.
- Local plugin manifests cover connectors and agent tools with declared permissions, audit, failure isolation, a reference JSON/Markdown connector with preview/import/delete, and a reference graph-search tool.
- `scripts/evaluate_graph_qa.py` runs 30 bilingual synthetic cases across four question types plus revoked and deleted evidence. The latest run reports citation accuracy 1.0, 0 unsupported claims, and about 20–30 ms P95 on local SQLite.
- **Boundaries:** extraction is still API-triggered rather than fully automatic; Q&A uses keyword and rule retrieval rather than semantic/vector search; plugin safety is permission declaration plus audit, not a strong sandbox; no multi-device sync, mobile, desktop package, OCR of scanned PDFs, or model-written answers.

## M7 — Connectors and quick capture: implemented

- `calendar_ics` accepts a bounded UTF-8 ICS complete snapshot through the web importer. The parser normalizes UTC/IANA, all-day, and floating times, preserves UID/TZID/location/description, and reports unsupported recurrence properties.
- Ingestion uses UID as stable identity and SEQUENCE as monotonic version. Re-import is idempotent, newer versions supersede prior current rows, lower sequences are skipped, and cancellation or disappearance from a complete snapshot soft-removes the affected event.
- Web preview shows event/recurrence counts and can update an existing calendar source instead of creating a duplicate source.
- Quick notes use owner-scoped `SourceItem(kind="quick_note")` under a hidden internal source. `POST/PATCH/DELETE /api/v1/quick-notes` supports create, edit, and item-scoped deletion; notes flow through timeline, search, dated reviews, Markdown export, and account archive.
- Item-level deletion batches extend the existing independent tombstone journal. Startup replay covers quick-note deletion and ICS reconciliation so a database restore cannot resurrect removed content.
- Migration `e8c4f2a7b913` adds created/updated/duplicate/removed/skipped/failed reconciliation counts to `SyncRun`.
- Verification: Ruff and 117 Python tests pass; web lint/build and seven Playwright workflows pass, including ICS preview/update/cancel and quick-note create/edit/search/export/delete.
- **Boundaries:** no RRULE/RDATE/EXDATE/RECURRENCE-ID expansion, CalDAV/API sync, URL/attachment fetching, partial snapshots, semantic search, mobile capture, or desktop package. PostgreSQL reconciliation is protected by a source-row lock but this round's automated evidence is local SQLite.

## M8 — Search quality and knowledge organization: implemented

- SQLite uses FTS5 trigram candidate tables with synchronization triggers; PostgreSQL conditionally installs `pg_trgm` and creates GIN indexes. Missing extensions, privileges, or FTS5 support fall back to `LIKE`, and short queries use `LIKE`.
- Every candidate is rejoined with authoritative rows and rechecked for owner, current version, deletion, source status, and filters. `scripts/rebuild_search_index.py` rebuilds SQLite candidates from current records.
- Unified search adds result-type, user-timezone date, source, status, tag, and collection filters. Saved searches persist the query and full filter object with owner-scoped CRUD.
- Tags and collections use casefold-unique owner-scoped names, optional colors/descriptions, and validated many-to-many item associations. Deleting organization metadata removes links, not items.
- The Chinese Organize page manages tags/collections and item associations; search pages expose filters and saved searches. Markdown export and account archive include organization metadata.
- The expanded 31-query bilingual evaluation reports hit@5 1.0 for indexed and baseline search. Indexed P95 is 93.85 ms on SQLite and 62.55 ms on PostgreSQL 16 against a 500 ms target; deleted-item exclusion passes on both.
- PostgreSQL 16 migration upgrade, downgrade/re-upgrade, `alembic check`, extension installation, and all five GIN indexes pass. Full Python suite: 121 passed; browser suite: 9 passed.

## M9 — Review intelligence and model selection: implemented

- Environment-backed provider/model registry with named OpenAI-compatible endpoints, model lists, token prices, disclosure text, optional loopback local providers, and opt-in proxy environment support. API keys are excluded from database records, registry responses, archives, and logs.
- `ModelConsent` isolates consent by owner/provider/disclosure version. Manual and scheduled reviews persist provider/model selection; inline and worker paths re-resolve configuration and recheck consent, credentials, pricing, per-call limit, and remaining monthly budget.
- Provider-scoped consent revocation cancels only matching queued/running jobs. The legacy default consent endpoint remains compatible with existing photo-description and review clients.
- Deterministic review insights add cross-period topic trends, commitment/due-date extraction, and active goal associations with source-item references. `ReviewVersion` stores immutable snapshots and the API/UI expose read-only comparisons.
- Model facts are rechecked against cited text before drafts are accepted. Usage summaries support day/week/month periods plus provider/purpose costs, token counts, latency, and failure reserves; archives include consent and version metadata.
- Fixed 30-case evaluation supports multiple configured providers and a deterministic loopback baseline. MiniMax and the local baseline both report citation accuracy 1.0, fact support 1.0, zero unsupported claims, and passing latency; MiniMax P95 is 6484 ms with estimated cost $0.00583950.
- Migration `a1b7c9d3e504` passes SQLite and PostgreSQL 16 upgrade, downgrade/re-upgrade, and `alembic check`. Full Python suite: 126 passed; browser suite: 10 passed.
- **Boundaries:** no provider credential administration UI, automatic local-model installation, cross-provider consent inheritance, or model fine-tuning. Local endpoints must be loopback and still require configured pricing for budget enforcement.

## M10 — Obsidian export and mobile capture: implemented

- Web export publishes stable `lifeos_id`, title/type/source/date, tag/collection, and export-time frontmatter for timeline items, quick notes, and weekly reviews. Item exports retain source locators; review exports retain period, status, and version metadata. Empty lists are YAML arrays.
- Supported Chromium browsers use File System Access API after an explicit user action to select an Obsidian Vault directory. The server never receives the path. Conflicts default to keep, copy adds numeric suffixes, overwrite requires explicit selection, and unsupported or denied access falls back to download without overwriting.
- The production PWA includes a standalone manifest, 192/512 icons, `/capture` shortcut, offline application shell, and text/title/URL share target. The service worker never caches API responses, tokens, source objects, or model output; shared text is deleted from the browser inbox after the capture page reads it.
- The 390×844 capture flow reuses owner-scoped quick notes and shows recent records. Due reminders remain visible in mobile navigation, capture, and review layouts. Browser notifications require explicit permission, emit at most once per due-reminder set while the app is open, and fail without blocking in-app reminders.
- Verification: Ruff and 126 Python tests pass; Web lint/build and all 18 Edge Playwright workflows pass. The 8 M10-specific tests cover frontmatter, filename sanitization, keep/copy/overwrite, manual-edit preservation, permission fallback, mobile capture, real service-worker sharing/inbox cleanup, no API caching, and denied notifications. A production-preview smoke confirmed an active service worker, two precached JS/CSS assets, no API cache entries, and offline `/capture` reload with zero console errors at 390×844. Obsidian 1.15.1 opened the exported file and rendered tag/collection properties and body text; a manual edit was confirmed on disk.
- **Boundaries:** File System Access API is Chromium-oriented; no two-way sync, server-side Vault access, offline write queue, background push service, native mobile package, or shared-file/media capture. Same-origin Vault writes are serialized, but the browser API has no atomic no-replace primitive against an external editor race; close an open note before re-export. PWA installation and sharing require a secure context and the production Web build.

## Release and follow-up

Use the [release checklist](../operations/release-checklist.md) and [support matrix](../operations/support-matrix.md) to review evidence and limits. Invite users only after hosted acceptance checks and recovery exercises have actually passed. Additional connectors, full-text/vector search, email or push delivery, and mobile capture remain post-MVP.
