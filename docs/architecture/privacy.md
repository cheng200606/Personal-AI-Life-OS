# Privacy and Data Handling

The project supports cloud deployment, but cloud hosting is not enabled by this repository. A deployment operator controls the API, database, object store, logs, TLS, and backups. Users must select the files and conversations they want to import.

## Implemented controls

- CLI previews show file metadata and conversation titles/counts, not chat message bodies. ChatGPT JSON is read locally and the upload is reduced to the selected conversations.
- Authentication uses Argon2 password hashes and signed bearer tokens. Records and API lookups are scoped to the authenticated owner.
- Imports have configured size limits, content hashes, parser versions, stable source locators, and duplicate detection. Markdown and ChatGPT parsing are bounded synchronous work. In `worker` mode, photo OCR, requested external weekly reviews, and user-requested photo descriptions run as database-backed jobs with leases and bounded retries. Job payloads store identifiers and controls; source content remains in its owner-scoped records or object storage. Job results, including unconfirmed description drafts, are owner-scoped and removed with the related source.
- Photos are decoded, orientation-corrected, and re-encoded before storage. The copy removes EXIF and GPS metadata. OCR output is searchable when Tesseract is installed.
- External review and photo-description calls require current, explicit consent. The UI discloses provider, data fields, retention text, and privacy URL. Queued model work is cancelled when consent is withdrawn; photo descriptions are drafts until the user confirms them.
- Graph extraction sends only the user-selected source items, and only when the source has current cloud-extraction consent. Revoked sources keep their entities and relations for history but mark evidence unavailable; deleted sources cascade-delete their evidence. Low-confidence items stay in a review queue until the user approves or rejects them.
- Graph questions are answered locally without an external model call. Answers cite active evidence only and exclude revoked sources, deleted items, and inactive evidence; with no evidence the answer states that no reliable evidence was found. Question threads, scopes, and answers are stored locally and can be exported or deleted.
- Rule insights, agent actions, and plugin invocations are local and owner-scoped. Agent writes record before/after values, evidence item IDs, and audit metadata, expire after 24 hours, and can be undone. External sending, original-file changes, spending, and deleting data or changing goals are rejected by the tool policy layer unless explicit human approval is provided.
- Plugin manifests declare permissions. Undeclared permissions are denied, invocation and failures are audited, and a failing plugin does not alter the main application flow. The reference connector reads only content the user supplies to the invocation; it does not scan arbitrary folders or use the network.
- Scheduled weekly review generation runs inside the local worker and follows the same consent, provider, price, and per-call budget path. It adds no email or push channel; due reminders and review-ready notices appear only inside the app.
- Logs and metrics contain operation types, status, latency, and token counts, not source text or image bytes. Metrics require a separate bearer token.
- External calls require operator-configured input/output token prices. Reviews reserve a conservative cost estimate before sending and fall back to the local template when the per-call budget would be exceeded. Usage and estimated spend are aggregated without user identifiers.
- Source and account deletion first write a durable tombstone, block ordinary access, scrub linked generated records, and erase object-store data. Tombstones are replayed during startup before the API serves traffic, including after a database restore.
- Account archive includes a JSON manifest, source records, generated records, background job results, model usage metadata, and available imported objects.

## Data sent to external models

When external review is requested, selected timeline item dates, titles, source-item IDs, and text for the requested review period are sent to the configured provider. When a user explicitly requests a photo description, the sanitized image is sent. The provider name, data fields, retention disclosure, and provider privacy URL must be shown before consent. Model use remains optional; a cited template review is available without a provider.

No external model call should be enabled until the operator verifies the provider's current terms and fills the deployment disclosure accurately. No end-to-end encryption is claimed because server-side parsing and optional model processing require plaintext.

## Deletion and backups

Deleting an item currently deletes its source connection and every uploaded file and parsed item associated with that source. For a photo batch, deleting one item removes the other selected photos in that batch too. The UI warns before this operation. Deleting a source also invalidates reviews and reminders that cite it and removes their copied evidence.

Database backups can restore deleted rows. The S3 deletion ledger is therefore retained separately from user object prefixes and is replayed before a restored database is served. A production operator must test that recovery path and set a published backup expiry window. The example operating policy is 35 days; it is a deployment requirement, not a retention guarantee supplied by this repository. See [backup and restore](../operations/backup-restore.md).

## Deployment requirements

- Use TLS, managed secrets, private S3-compatible object storage, server-side encryption, and an encrypted database volume.
- Require invitation-only registration and strong unique secrets; keep API and database ports private.
- Configure and test backup retention, deletion replay, monitoring, and incident response before real user data is accepted.
- Publish an operator privacy contact and retention policy. Remove access logs or tracing that could capture request bodies or authorization headers.

## Known limits

- There is no hosted identity provider, formal audit log, Redis integration, or managed backup service in the repository. The database-backed worker runs inside the API process; operators should use a process manager and verify queue age/failure metrics.
- Source deletion tombstones are stored in the configured object store. Database-only restore replay is implemented; disaster recovery of both the database and the entire object bucket requires a tested, current object-store backup and preserved tombstones.
- Local development secrets and the development Compose stack are not suitable for public hosting.
- No real-user data, beta participants, hosted deletion SLA, or production restore exercise has been verified.
