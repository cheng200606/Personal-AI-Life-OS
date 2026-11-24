# Privacy and Data Handling

The selected architecture is cloud-based, so user-selected source material is transmitted to and processed by the configured service. Consent and visibility are core product behavior.

## User controls

- Show which source and files are selected before first sync.
- Provide pause, resume, disconnect, per-item delete, full export, and account deletion.
- Show sync history, failures, and the last successful sync.
- Keep generated notes and reminders as drafts until the user confirms them.
- Never write back to original source files; Obsidian export is an explicit user action.

## Data minimization

- Begin with local file imports rather than broad account permissions.
- Request only file types and scopes needed for the connector.
- Store source text and media only when required for review and configured search.
- Do not log source text, image bytes, tokens, or private memory file contents.
- Document retention and backup deletion behavior before production hosting.

## Security baseline

- Use TLS in transit and managed secrets in hosted deployments.
- Use infrastructure encryption at rest for databases and object storage.
- Scope every query and object key to the authenticated owner/workspace.
- Treat imported content as untrusted data; keep it separate from system prompts and tool instructions.
- Use signed, short-lived URLs for object access and audit source access.
- Make export and deletion cover originals, parsed text, embeddings, summaries, and backups according to a published retention policy.

## Model providers

Before sending content to an external model provider, disclose which fields are sent, which provider processes them, and what retention terms apply. Keep a provider adapter so self-hosted models can be considered later. Do not claim end-to-end encryption while server-side processing needs plaintext.

## Current status

These are design requirements, not yet implemented controls. The current API is a health-check shell and must not be used to upload real personal data.
