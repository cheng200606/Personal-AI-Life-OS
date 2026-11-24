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
            ├─ synchronous bounded parsers (Markdown, ChatGPT JSON, photos/OCR)
            └─ optional consent-gated model calls
```

## Stack

- **API:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic.
- **Database:** PostgreSQL for Compose/hosted configuration; SQLite for local API-only development. Vector search is not part of the MVP implementation.
- **Storage:** local filesystem adapter for development and an S3-compatible adapter for production templates.
- **Web:** React, TypeScript, Vite, served by Nginx in the production Compose template.
- **Local integration:** Python CLI for explicit file selection, preview, sync, and Obsidian export.
- **Deployment:** Docker Compose with Caddy TLS proxy; operator-supplied database, private bucket, secrets, and backups.

There is no Redis queue in the current MVP. Upload parsing and OCR run synchronously inside the API with input limits. Longer or background processing requires a later durable worker design.

## Data flow

1. **Select:** user chooses a Markdown file, ChatGPT export conversations, or individual photo. Chat selection and minimization happen in the browser or CLI before upload.
2. **Authorize:** create a source record with selected scope and consent version; source access is tied to the authenticated owner.
3. **Import:** upload through a size-limited endpoint. The API hashes the selected bytes, stores the original or sanitized photo, parses records, and records line/message/file provenance.
4. **Review:** date/source filters and bounded keyword search show imported records. Raw file access goes through an owner-scoped API endpoint.
5. **Reflect:** an on-demand review uses confirmed timeline records. Template output copies source text with citations. Optional external output is validated against accessible source IDs and falls back to the template on provider failure.
6. **Confirm and export:** the user edits and confirms review text, creates or updates reminders, and exports notes to Markdown. CLI export uses stable IDs and detects hand-edited files.
7. **Delete:** source or account deletion records a durable tombstone before removing data. Startup replays tombstones before serving a restored database.

## Data entities

- **User:** authentication, timezone, current model consent, and deletion state.
- **SourceConnection:** source type, selected scope, status, consent version, and sync history.
- **SyncRun:** upload checksum, parser version, outcome, item counts, and stored-object reference.
- **SourceItem:** owner/source, original locator, content digest, event time, timezone, parsed text, and metadata.
- **MemoryRecord:** user-confirmed notes or confirmed photo descriptions with source links.
- **Review:** requested period, cited source items, model metadata, draft and user-confirmed text.
- **Reminder:** user-owned action with optional source and memory references.
- **ModelRun:** provider, model, purpose, status, prompt version, latency, and token counts without source content.

## Search and limits

Timeline queries use owner, date, source, current/deleted state, and simple case-insensitive SQL `LIKE` matching. There is no full-text or semantic index. Text upload is capped at 5 MB per file and photo upload at 20 MB by default. Photo decoding is limited to 40 megapixels. A review period is limited to 500 source items.

See the [support matrix](../operations/support-matrix.md), [privacy design and current limits](privacy.md), and [deployment guide](../operations/deployment.md).
