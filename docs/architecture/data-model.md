# Initial Data Model

This is a logical model for the MVP. Database schema and migrations will be added with the persistence milestone.

| Entity | Purpose | Key fields |
| --- | --- | --- |
| User | Account and isolation boundary | id, created_at, preferences |
| SourceConnection | Explicit source authorization | owner_id, kind, selected_scope, consent_version, status |
| SyncRun | Observable import attempt | owner_id, source_id, started_at, finished_at, result, cursor |
| SourceItem | Immutable imported item | owner_id, source_id, external_id, content_hash, occurred_at, object_key |
| MemoryRecord | Searchable user memory | owner_id, kind, body, generated_by, review_status, source_item_ids |
| Review | Periodic reflection draft/final | owner_id, period_start, period_end, draft, final_text, record_ids |
| Reminder | Confirmed follow-up | owner_id, title, due_at, status, source_record_ids |

## Integrity rules

- Use stable IDs for source items and generated records.
- Keep original content separate from parsed text and generated summaries.
- Make ingestion idempotent by owner, source, and source identity or content hash.
- Keep provenance as a many-to-many relation; one summary may cite several items.
- Store review status and model/parser versions so derived records can be regenerated or audited.
- Cascade deletion from the owner and source according to the published retention policy.
