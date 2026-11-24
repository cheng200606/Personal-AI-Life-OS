# System Architecture

## Principles

1. The user chooses which sources enter the system.
2. Original material stays immutable; parsed records and AI notes are separate outputs.
3. Generated claims point back to source items.
4. Markdown export keeps notes portable.
5. Connectors and model providers use replaceable interfaces.

## MVP topology

```text
Selected folders / exports
  └─ Local sync CLI (allowlist, scan, hash, preview)
       └─ HTTPS upload API
            ├─ FastAPI service
            ├─ PostgreSQL + pgvector (metadata, records, embeddings)
            ├─ Object storage (original files and derived thumbnails)
            └─ Redis job queue (parsing, image descriptions, reviews)

Web review UI ── HTTPS API
Obsidian vault ◀── Markdown export / local sync
```

## Stack

- **API:** Python 3.11+, FastAPI, Pydantic.
- **Primary store:** PostgreSQL; pgvector for semantic search when that feature lands.
- **Async work:** Redis-backed queue for ingestion and scheduled jobs.
- **Original files:** S3-compatible object storage in hosted deployments; local filesystem adapter for development.
- **Web client:** React + TypeScript, planned as a separate `web/` app.
- **Local integration:** Python CLI for explicit file selection and Obsidian export.
- **Packaging:** Docker Compose for local dependencies; container image for the API.

This repository currently implements only the FastAPI shell and health route. Persistence, authentication, upload handling, and the web app are roadmap work.

## Data flow

1. **Authorize:** select source files and confirm a sync preview.
2. **Discover:** scan only configured paths; record metadata and content hash.
3. **Upload:** send changed files over HTTPS to the authenticated API; allow sync to stop/resume.
4. **Normalize:** parse source items and timestamps while retaining source identity and parser version.
5. **Enrich:** queued workers produce searchable text, optional image descriptions, and draft summaries.
6. **Review:** present drafts with provenance; the user confirms, edits, or dismisses them.
7. **Reflect:** prepare a cited review from confirmed events and pending commitments.
8. **Export:** emit approved notes as Markdown with stable IDs and source references.

## Initial entities

- **User / Workspace:** owner and isolation boundary.
- **SourceConnection:** connector type, selected scope, consent version, sync state, and revocation time.
- **SourceItem:** immutable source identity, timestamps, content hash, storage key, and parser metadata.
- **MemoryRecord:** generated or user-authored fact, event, decision, or note with provenance and review status.
- **Review:** date range, draft, included record IDs, and user-edited final text.
- **Reminder:** user-confirmed action, due time, status, and originating records.
- **SyncRun:** start/end time, counts, failures, and resumable cursor.

All user-owned records need an owner/workspace key and must be scoped at query boundaries.

## Deployment and interfaces

Local development uses Docker Compose Postgres and Redis. Hosted deployment adds a web client, authenticated API, managed PostgreSQL, private object storage, workers, secret management, backups, and monitoring.

Define narrow interfaces around `SourceConnector`, `Parser`, `ObjectStore`, `JobQueue`, `ModelProvider`, and `MarkdownExporter`. The initial import path does not need direct ChatGPT or photo-provider API access: local export files are the first connector.
