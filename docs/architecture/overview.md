# System Architecture

## Principles

1. Users choose the source files and conversations that enter the system.
2. Imported originals are immutable; parsed items and generated notes are separate records.
3. Generated facts include source-item references and remain drafts until the user confirms them.
4. Markdown and JSON exports keep user data portable.
5. Storage and optional model providers sit behind narrow interfaces.

## MVP topology

```text
Selected local files
  ├─ lifeos CLI: preview, select, authenticate, sync, export
  └─ React web app: select chats/photos, review timeline, manage data
       └─ FastAPI API
            ├─ PostgreSQL (Compose/production) or SQLite (API-only development)
            ├─ Local object store (development) or private S3-compatible bucket
            ├─ bounded import parsers (Markdown, ChatGPT JSON, complete-snapshot ICS, sanitized photos)
            ├─ database-backed leased worker (photo OCR, requested reviews/descriptions)
            └─ optional consent-gated model calls from the worker
```

## Windows desktop topology (implemented, D0–D5)

The Windows 10/11 x64 desktop distribution is implemented and passed local single-user acceptance on 2026-11-27. It uses a Tauri 2 shell to host the same React UI in WebView2 and to supervise a packaged Python sidecar containing the FastAPI app, the database-backed worker, SQLite and local object storage, Alembic migrations, and Tesseract. The shell owns file and folder selection, notifications, tray, autostart, single-instance behavior, and launch/restart supervision. It does not require Docker, and the local API binds to a random loopback port with a per-launch secret and short-lived native path grants. Signed updates remain a public-distribution gate and are not implemented. See [Windows desktop architecture](desktop.md), [ADR 0002](decisions/0002-windows-desktop-shell.md), and [desktop acceptance](../operations/desktop-acceptance.md).

## Stack

- **API:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic.
- **Database:** PostgreSQL for Compose/hosted configuration; SQLite for local API-only development. Vector search is not part of the MVP implementation.
- **Storage:** local filesystem adapter for development and an S3-compatible adapter for production templates.
- **Web:** React, TypeScript, Vite, served by Nginx in the production Compose template.
- **Desktop:** Tauri 2 shell with WebView2, a PyInstaller one-folder Python sidecar, and an unsigned per-user NSIS installer for local single-user use.
- **Local integration:** Python CLI for explicit file selection, preview, sync, and Obsidian export.
- **Deployment:** Docker Compose with Caddy TLS proxy; operator-supplied database, private bucket, secrets, and backups.

The MVP uses a database-backed queue with leases, bounded retries, and owner-scoped status/retry endpoints. A worker thread starts with the API process; PostgreSQL claims use `FOR UPDATE SKIP LOCKED`, and expired leases make interrupted tasks eligible for recovery. Redis is not required or currently integrated. Markdown and ChatGPT parsing remain synchronous under their upload limits; photo OCR and requested model work use the worker when `PROCESSING_MODE=worker`.

## Data flow

1. **Select or write:** the user chooses a Markdown file, ChatGPT export conversations, an ICS calendar snapshot, up to ten photos/files from a selected folder, or writes a quick note in the web app. Chat selection and minimization happen in the browser or CLI before upload. Calendar preview counts events and unsupported recurrence properties locally.
2. **Authorize:** create a source record with selected scope and consent version; source access is tied to the authenticated owner.
3. **Import:** upload through a size-limited endpoint. The API hashes the selected bytes, stores the original or sanitized photo, parses records, and records line/message/file provenance. Photo OCR is recorded as a durable job and becomes searchable when it finishes.
4. **Review:** date/source filters and bounded keyword search show imported records. Unified search on the Search page returns grouped matches across timeline items, weekly reviews, and reminders, with links back to each record. Raw file access goes through an owner-scoped API endpoint.
5. **Reflect:** an on-demand review uses confirmed timeline records. Template output copies source text with citations. Optional external output is validated against accessible source IDs and falls back to the template on provider failure.
6. **Confirm and export:** the user edits and confirms review text, creates or updates reminders, and exports notes to Markdown. CLI export uses stable IDs and detects hand-edited files.
7. **Delete:** source or account deletion records a durable tombstone before removing data. Startup replays tombstones before serving a restored database.

## Evidence graph (v0.5)

Manually selected source items can be sent to the configured OpenAI-compatible provider for graph extraction. The service returns entities, relations, exact quotes, and confidence; high-confidence records become active, low-confidence records enter a review state, and every record keeps item-level evidence. Source-level cloud consent is required, and the monthly/per-call model budget is enforced. A completed identical batch is idempotent. Low-confidence items can be edited, approved, or rejected in the review queue; duplicate entities can be merged through aliases with an undo snapshot, and approved custom ontology types enter later extraction prompts.

The Q&A layer answers locally without a model call. It retrieves active evidence from approved entities and relations, filters by source, project/topic, and date range, excludes revoked sources, deleted items, and inactive evidence, and returns facts, citations, confidence, fact/inference/uncertain labels, missing information, and action suggestions. Question threads are stored locally, remember the last scope, and can be exported or deleted.

Rule insights evaluate four explainable conditions over active entities and evidence: overdue goals, commitments without follow-up, stalled projects, and skills with weak or stale evidence. Dismissals are stored per owner and key so a false positive does not repeat.

Agent actions are deterministic internal writes: reminders, task/project/growth entities, goal-progress records, and review drafts. Each action stores before/after values, evidence item IDs, audit metadata, and a 24-hour undo deadline. The tool policy layer rejects external sending, original-file changes, spending or irreversible transactions, and deleting data or changing goals unless explicit human approval is supplied.

Plugins are local manifests for connectors and agent tools. Each manifest declares permissions; undeclared permissions are denied at invocation. The reference connector previews and imports user-selected JSON/JSONL/Markdown, and the reference agent tool searches active graph entities and evidence. Invocation and failures are audited, and a plugin failure does not alter the main application flow.

## Calendar snapshots and quick notes (M7)

ICS uploads are complete snapshots for one `calendar_ics` source. The parser accepts bounded UTF-8 iCalendar, normalizes zoned, all-day, and floating times to UTC, and preserves the original TZID and UID locator. Ingestion uses UID as the stable event identity and SEQUENCE as the monotonic version. A newer event version supersedes the prior current row; lower-sequence uploads are skipped. `METHOD:CANCEL`, `STATUS:CANCELLED`, and events absent from a later complete snapshot soft-remove the affected current row. RRULE/RDATE/EXDATE/RECURRENCE-ID are reported and skipped rather than expanded.

Quick notes are mutable user-authored `SourceItem(kind="quick_note")` rows under one hidden internal source per owner. This representation reuses timeline, search, dated review evidence, Markdown export, and archive behavior without a second content store. Generic source management rejects the internal source, so notes cannot be accidentally paused, revoked, deleted, or opted into cloud extraction through source controls. Note deletion is item-scoped, unlike imported-source deletion. Both note deletion and calendar reconciliation write item-level deletion batches to the independent object-store journal; startup replay prevents a database restore from resurrecting removed content.

`SyncRun` records created, updated, duplicate, removed, skipped, and failed item counts. Calendar imports lock the source row on PostgreSQL before reconciliation so concurrent uploads cannot independently choose the current snapshot.

## Data entities

- **User:** authentication, timezone, current model consent, and deletion state.
- **SourceConnection:** source type, selected scope, status, consent version, and sync history.
- **SyncRun:** upload checksum, parser version, outcome, created/updated/duplicate/removed/skipped/failed item counts, and stored-object reference.
- **SourceItem:** owner/source, original locator, content digest, event time, timezone, parsed or user-authored text, and metadata. `calendar_event` rows preserve ICS UID/SEQUENCE; `quick_note` rows are editable user content.
- **MemoryRecord:** user-confirmed notes or confirmed photo descriptions with source links.
- **Review:** requested period, cited source items, model metadata, queued/draft/confirmed state, and user-confirmed text.
- **Reminder:** user-owned action with optional source and memory references.
- **ModelRun:** provider, model, purpose, status, prompt version, latency, and token counts without source content.
- **ModelConsent:** owner/provider-unique disclosure acceptance, grant time, and revocation time; credentials are not stored.
- **ReviewVersion:** immutable review draft/text/status snapshot with a monotonically increasing version number and reason.
- **GraphEntity / GraphRelation:** owner-scoped nodes and edges with type, name, confidence, status, and optional merge target.
- **GraphEvidence:** quote, source, item, locator, confidence, and availability (`active`, `revoked`, `deleted`) linking a graph record to its origin.
- **ExtractionRun / GraphReviewItem:** model/provider/cost metadata for a selected batch and low-confidence records awaiting review.
- **EntityAlias / EntityMergeLog / OntologyType:** durable aliases, reversible merge snapshots, and proposed or approved custom entity/relation types with creator and version.
- **QaThread / QaMessage:** local question threads with remembered scope, stored questions, and structured answers with citations.
- **InsightDismissal:** owner-scoped ignored rule insight key with an optional reason.
- **AgentAction:** action kind, before/after values, evidence item IDs, status, approval mode, audit metadata, and undo expiry.
- **PluginManifest / PluginPermission / PluginAuditLog:** local plugin identity, declared permissions, and invocation or lifecycle audit.
- **Tag / Collection:** owner-scoped organization metadata with casefold-unique names; tags have optional colors and collections optional descriptions.
- **ItemTags / ItemCollections:** many-to-many links from current source items to owner-scoped tags and collections.
- **SavedSearch:** owner-scoped name, query, and serialized type/date/source/status/tag/collection filters.

## Review intelligence and model routing (M9)

The model registry is built from environment-backed configuration. The existing `MODEL_PROVIDER/OPENAI_*` settings form the built-in `default` provider; `MODEL_PROVIDERS` adds named OpenAI-compatible endpoints with model lists, token prices, disclosure text, optional privacy URLs, and loopback local providers. API keys are never persisted in SQLite/PostgreSQL, returned by the registry API, written to archives, or logged. `MODEL_TRUST_ENV` is opt-in for deployments that require proxy environment variables.

`ModelConsent` is unique per owner and provider and records the accepted disclosure version. Manual and scheduled reviews persist provider/model selection. Inline calls and workers resolve the current registry entry again, recheck consent, credentials, disclosure, pricing, per-call limit, and remaining monthly budget before sending. Revoking one provider cancels only jobs carrying that provider ID; the legacy default consent endpoint remains compatible with photo descriptions and existing clients.

Review insights are deterministic and local: topic frequency across prior periods, commitment sentences with explicit dates/weekdays, and active goal-name associations all retain source-item IDs. `ReviewVersion` stores immutable draft/text/status snapshots for generation, suggestion edits, confirmation, regeneration, and worker completion. Model facts are filtered again against cited text before a draft is accepted; suggestions remain cited inferences. `ModelRun` continues to power period/provider/purpose cost summaries and failure reserves.

## Search quality and organization (M8)

SQLite creates FTS5 trigram candidate tables and synchronization triggers for timeline items, reviews, and reminders. PostgreSQL conditionally installs `pg_trgm` and creates GIN indexes on lowercased title/content fields. If FTS5, the extension, or required privileges are unavailable, search falls back to case-insensitive `LIKE`; short queries also use `LIKE`.

Indexes only narrow candidates. Every query rejoins authoritative rows and reapplies owner, current-version, deletion, source-status, result-type, date, source, status, tag, collection, ordering, and snippet rules. Stale index rows therefore cannot recall deleted content or cross-owner data. `scripts/rebuild_search_index.py` rebuilds SQLite candidate tables from current rows and reports the active PostgreSQL backend.

Unified search supports type, user-timezone half-open date range, source, status, tag, and collection filters. Saved searches persist the query and complete filter object. The Organize page manages tags/collections and replaces an item's associations only after validating that every ID belongs to the same owner. When ingestion creates a newer current version of an existing item, its tag and collection links are copied to the new version.

`GET /api/v1/search` returns three groups—timeline, weekly reviews, and reminders—each with a total and at most 20 results (10 by default). Title matches sort before body matches and snippets are capped at 200 characters. There is no semantic/vector index. Text upload is capped at 5 MB per file, photo upload at 20 MB, photo decoding at 40 megapixels, and a review period at 500 source items.

## Obsidian export and mobile capture (M10)

Web export builds one frontmatter contract for timeline items, quick notes, and weekly reviews. `lifeos_id` is the stable identity; `title`, `type`, `source`, `occurred_at`, `tags`, `collections`, and `exported_at` describe the exported record, while item exports retain `source_locator` and review exports retain period/status/version fields. Empty tag and collection lists are emitted as YAML arrays, not null values.

File System Access API calls happen only after an explicit export action. The browser asks the user to choose a Vault directory; the server never receives or stores that path. Same-origin exports are serialized with Web Locks. Existing filenames default to `keep`, `copy` adds numeric suffixes, and `overwrite` requires an explicit policy selection. Unsupported browsers, cancelled directory selection, and denied permission use the local download path; other write failures are surfaced instead of being reported as successful downloads.

The production web build registers a service worker with a standalone manifest, installation icons, a `/capture` shortcut, and a text/title/URL share target. The worker precaches the shell and hashed assets, uses network-first navigation, and stores only same-origin static assets. Shared content waits in a 15-minute browser Cache Storage inbox; the capture page consumes and deletes it, logout clears it, and the most recently focused same-origin client is preferred for capture navigation. API responses, bearer tokens, source objects, and model output are never cached. There is no offline write queue or background push service.

Due reminders remain in the sidebar, review page, and mobile capture layout. Browser notifications require a user click and permission; once granted, the open app emits one notification per due-reminder set and notification clicks focus and reuse an existing authenticated client when available. Permission denial, service-worker timeout, or notification failure leaves the in-app reminder flow unchanged.

See the [support matrix](../operations/support-matrix.md), [privacy design and current limits](privacy.md), and [deployment guide](../operations/deployment.md).
