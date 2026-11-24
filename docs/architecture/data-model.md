# Data Model

The SQLAlchemy schema is migrated with Alembic. All user-owned tables carry an `owner_id`; API queries also verify the authenticated owner before following a resource relationship.

| Entity | Purpose | Important fields and links |
| --- | --- | --- |
| `User` | Authentication and isolation boundary | Unique email, Argon2 password hash, timezone, current AI consent, deletion state |
| `SourceConnection` | Explicit source selection and lifecycle | Kind, selected scope, consent version, active/paused/revoked/deleting status, last import time |
| `SyncRun` | Observable import attempt | File checksum, parser version, object key, counts, status, structured error, timestamps |
| `SourceItem` | Versioned parsed source entry | Stable external ID, source and stored hashes, parser version, timestamps/timezone, source locator, current/deleted state, owner/source/sync-run foreign keys |
| `MemoryRecord` | User-confirmed memory such as a photo description | Body, generated-by marker, review status, occurred time, many-to-many source items |
| `Review` | Periodic reflection draft and final text | Owner, timezone-normalized half-open period, status, structured draft, final text, many-to-many source items |
| `BackgroundJob` | Recoverable OCR and optional model work | Owner, source/review references, kind/status, identifier-only payload, private result, retry count, availability, lease, structured error |
| `Reminder` | User-confirmed follow-up | Title, optional notes/due date, status, optional source items and memory records |
| `ModelRun` | Content-free model usage record | Provider/model, purpose/status, prompt version, latency, input/output tokens, configured estimated cost, timestamp |

## Integrity and lifecycle

- `SourceItem` versions are unique by owner, source, external ID, and source-file checksum. Re-import uses conflict-safe insertion and preserves the current version flag.
- UTC-aware timestamps are normalized through a shared SQLAlchemy type. Date-only Markdown headings use the user's calendar day and preserve that timezone as the date basis.
- Review and reminder citations use many-to-many relations so deletion can invalidate or scrub all linked derivatives.
- Foreign keys cascade from user/source/sync records. The API writes an object-store deletion tombstone before source/account cleanup; the startup replay blocks serving while restored database rows are reconciled.
- `BackgroundJob` payloads store identifiers and processing controls rather than source content. Generated photo-description drafts can be retrieved by the owner and are removed with their source.
- `ModelRun` stores usage and cost metadata only. Request and source content are not written into this table. Cost is calculated from operator-configured per-million-token rates; failed calls reserve a conservative estimate.

Schema revisions: `0de3d72c2e1f` initial tenant-scoped schema, `513becf54638` deletion/reminder citation relations, `958b551e0397` model usage, `eb3ff930ec06` estimated model cost, and `c101bc66b1a3` durable background jobs.
