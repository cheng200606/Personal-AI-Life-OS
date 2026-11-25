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
            ├─ bounded import parsers (Markdown, ChatGPT JSON, sanitized photos)
            ├─ database-backed leased worker (photo OCR, requested reviews/descriptions)
            └─ optional consent-gated model calls from the worker
```

## Planned Windows desktop topology

A Windows desktop distribution is planned but not implemented. It uses a Tauri 2 shell to host the same React UI in WebView2 and to supervise a packaged Python sidecar containing the FastAPI app, the database-backed worker, SQLite and local object storage, Alembic migrations, and Tesseract. The shell owns file and folder selection, notifications, tray, autostart, single-instance behavior, and signed updates. It does not require Docker, and the local API binds to a random loopback port. See [Windows desktop architecture](desktop.md) and [ADR 0002](decisions/0002-windows-desktop-shell.md).

## Stack

- **API:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic.
- **Database:** PostgreSQL for Compose/hosted configuration; SQLite for local API-only development. Vector search is not part of the MVP implementation.
- **Storage:** local filesystem adapter for development and an S3-compatible adapter for production templates.
- **Web:** React, TypeScript, Vite, served by Nginx in the production Compose template.
- **Local integration:** Python CLI for explicit file selection, preview, sync, and Obsidian export.
- **Deployment:** Docker Compose with Caddy TLS proxy; operator-supplied database, private bucket, secrets, and backups.

The MVP uses a database-backed queue with leases, bounded retries, and owner-scoped status/retry endpoints. A worker thread starts with the API process; PostgreSQL claims use `FOR UPDATE SKIP LOCKED`, and expired leases make interrupted tasks eligible for recovery. Redis is not required or currently integrated. Markdown and ChatGPT parsing remain synchronous under their upload limits; photo OCR and requested model work use the worker when `PROCESSING_MODE=worker`.

## Data flow

1. **Select:** user chooses a Markdown file, ChatGPT export conversations, or up to ten photos/files from a selected folder. Chat selection and minimization happen in the browser or CLI before upload.
2. **Authorize:** create a source record with selected scope and consent version; source access is tied to the authenticated owner.
3. **Import:** upload through a size-limited endpoint. The API hashes the selected bytes, stores the original or sanitized photo, parses records, and records line/message/file provenance. Photo OCR is recorded as a durable job and becomes searchable when it finishes.
4. **Review:** date/source filters and bounded keyword search show imported records. Unified search on the Search page returns grouped matches across timeline items, weekly reviews, and reminders, with links back to each record. Raw file access goes through an owner-scoped API endpoint.
5. **Reflect:** an on-demand review uses confirmed timeline records. Template output copies source text with citations. Optional external output is validated against accessible source IDs and falls back to the template on provider failure.
6. **Confirm and export:** the user edits and confirms review text, creates or updates reminders, and exports notes to Markdown. CLI export uses stable IDs and detects hand-edited files.
7. **Delete:** source or account deletion records a durable tombstone before removing data. Startup replays tombstones before serving a restored database.

## Evidence graph (v0.5)

Manually selected source items can be sent to the configured OpenAI-compatible provider for graph extraction. The service returns entities, relations, exact quotes, and confidence; high-confidence records become active, low-confidence records enter a review state, and every record keeps item-level evidence. Source-level cloud consent is required, and the monthly/per-call model budget is enforced. A completed identical batch is idempotent. Low-confidence items can be edited, approved, or rejected in the review queue; duplicate entities can be merged through aliases with an undo snapshot, and approved custom ontology types enter later extraction prompts.

The Q&A layer answers locally without a model call. It retrieves active evidence from approved entities and relations, filters by source, project/topic, and date range, excludes revoked sources, deleted items, and inactive evidence, and returns facts, citations, confidence, fact/inference/uncertain labels, missing information, and action suggestions. Question threads are stored locally, remember the last scope, and can be exported or deleted. Rule insights, agent actions, and plugins remain later v0.5 work.

## Data entities

- **User:** authentication, timezone, current model consent, and deletion state.
- **SourceConnection:** source type, selected scope, status, consent version, and sync history.
- **SyncRun:** upload checksum, parser version, outcome, item counts, and stored-object reference.
- **SourceItem:** owner/source, original locator, content digest, event time, timezone, parsed text, and metadata.
- **MemoryRecord:** user-confirmed notes or confirmed photo descriptions with source links.
- **Review:** requested period, cited source items, model metadata, queued/draft/confirmed state, and user-confirmed text.
- **Reminder:** user-owned action with optional source and memory references.
- **ModelRun:** provider, model, purpose, status, prompt version, latency, and token counts without source content.
- **GraphEntity / GraphRelation:** owner-scoped nodes and edges with type, name, confidence, status, and optional merge target.
- **GraphEvidence:** quote, source, item, locator, confidence, and availability (`active`, `revoked`, `deleted`) linking a graph record to its origin.
- **ExtractionRun / GraphReviewItem:** model/provider/cost metadata for a selected batch and low-confidence records awaiting review.
- **EntityAlias / EntityMergeLog / OntologyType:** durable aliases, reversible merge snapshots, and proposed or approved custom entity/relation types with creator and version.
- **QaThread / QaMessage:** local question threads with remembered scope, stored questions, and structured answers with citations.

## Search and limits

Search uses owner-scoped, case-insensitive SQL `LIKE` substring matching. `GET /api/v1/search` returns three groups—timeline, weekly reviews, and reminders—each with a total and at most 20 results (10 by default). Title matches sort before body matches, snippets are capped at 200 characters, and deleted/non-current timeline entries, sources pending deletion, and invalidated reviews are excluded. There is no full-text or semantic index. Text upload is capped at 5 MB per file and photo upload at 20 MB by default. Photo decoding is limited to 40 megapixels. A review period is limited to 500 source items.

See the [support matrix](../operations/support-matrix.md), [privacy design and current limits](privacy.md), and [deployment guide](../operations/deployment.md).
