# ADR 0001: Cloud processing with explicit local source selection

- **Status:** Accepted
- **Date:** 2026-11-24

## Context

The product direction combines selected chat history, photos, and agent memory files, with a web timeline and AI-assisted reviews. The product decision is cloud processing, while the source material may live on a user's computer. Broad ambient collection would make consent, revocation, and source attribution difficult to explain and verify.

## Decision

Use a local CLI for explicit file/folder selection, preview, hashing, and upload to an authenticated HTTPS API. Keep parsing and review generation on the service side behind replaceable interfaces. Preserve the original source identity and provenance. Offer Obsidian output as plain Markdown written only after a user action.

The first supported path is local import of a synthetic `memory.md` and a ChatGPT data export. Do not assume access to private in-product conversations or silently watch a device. Cloud model processing is separately disclosed and opt-in.

## Consequences

- Users can inspect the upload scope before personal content leaves the device.
- The service can provide multi-device timelines, reviews, and reminders.
- The service must implement tenant isolation, export, deletion, retention, and provider disclosures before real-user hosting.
- A local-only deployment can be evaluated later, but is not the current product direction.
- Exported Markdown remains readable outside this application.
