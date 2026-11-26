# MVP Product Requirements

The Windows single-user distribution follows the [desktop MVP plan](../roadmap/desktop-mvp.md), including local profile setup, directory authorization, chat selection, and desktop acceptance criteria.

## Product direction

Personal AI Life OS helps people build a useful, searchable memory of work, learning, and life. It connects selected information sources, preserves provenance, and prepares summaries and reviews users can inspect and edit.

**Positioning:** integrated research across personal context.


**Audience:** individuals with varied workflows, including researchers, students, and knowledge workers.


**License:** Apache-2.0.


**Interaction model:** web review experience plus local source and Obsidian workflows.


**Privacy choice:** cloud processing with explicit source authorization and user controls.

## Problem

Personal context is scattered across chat histories, photos, notes, and agent memory files. People lose useful decisions and experiences, and reflection depends on remembering to collect material manually. The system should reduce that effort while keeping users in control of what is collected and saved.

## Goals and initial success signals

- Capture selected work and learning records with low recurring effort.
- Make every generated summary traceable to its source.
- Provide a useful timeline, periodic review, and follow-up reminders.
- Keep the knowledge base portable through Markdown and Obsidian export.
- Give users clear controls to pause sync, export data, and delete data.
- A new user can import a source and see a cited timeline entry.
- Re-importing the same file does not create a duplicate.
- A weekly review can be edited before saving.
- Exported notes open as ordinary Markdown in Obsidian.
- Users can identify the origin of generated facts and remove an imported item.

## Core journeys

1. **Connect:** create an account, review source permissions, choose specific files/folders, and inspect a sync preview.
2. **Capture:** import a ChatGPT data export, selected photos, or an agent `memory.md` through local sync.
3. **Review:** inspect extracted events, dates, summaries, and source links; edit or dismiss suggestions.
4. **Reflect:** open a weekly review with progress, themes, commitments, and cited source records.
5. **Follow up:** turn a suggested commitment into a reminder, set a due date, snooze, or dismiss.
6. **Keep ownership:** export Markdown, download an account archive, or delete source and derived records.

## Functional requirements

### P0 — MVP

- **Source consent:** show the source, selected scope, fields read, last sync time, and revoke control.
- **Imports:** ChatGPT export files; user-selected image files/directories; user-selected agent `memory.md` files. Start with local file/folder import; direct provider APIs are later work.
- **Incremental ingestion:** retain source identity, file hash, capture/import times, and parser version; detect duplicates and changes.
- **Multimodal extraction:** produce searchable text and optional image descriptions. Preserve the original reference and distinguish extracted facts from user-authored notes.
- **Timeline:** group extracted events by date/source and link each to its originating item.
- **AI review:** create summaries, themes, and possible action items as drafts. The user confirms or edits them before they become durable memory or reminders.
- **Periodic review:** generate an on-demand weekly review first; scheduled delivery follows once preferences exist.
- **Reminders:** create, complete, snooze, or dismiss a user-confirmed reminder in the web experience.
- **Obsidian export:** write plain Markdown with frontmatter and source links into a selected vault folder; never overwrite a conflicting note without confirmation.
- **Data controls:** pause/resume sync, disconnect a source, export data, and delete imported and derived data.

### P1 — after MVP

- Scheduled source sync and weekly review delivery.
- More chat, calendar, task, and photo connectors.
- Search across original items and derived notes.
- Configurable AI provider/model adapter.
- Mobile-friendly capture and notification channels.

## Non-functional requirements

- **Privacy:** per-user data isolation, explicit source selection, visible sync state, export and deletion.
- **Security:** TLS in transit, managed secrets, encrypted storage at rest through deployment infrastructure, and no source content in logs.
- **Traceability:** generated claims link to sources and are marked as generated.
- **Portability:** records remain exportable as JSON and Markdown.
- **Reliability:** ingestion is idempotent and retryable; failures are visible.
- **Accessibility:** keyboard-accessible review and reminder workflows.
- **Flexibility:** ingestion and model-provider interfaces can be replaced.

## Out of scope for MVP

- Scraping private ChatGPT conversations or bypassing service access controls.
- Always-on microphone, camera, screen, or device monitoring.
- Silent, unreviewed edits to original files or the Obsidian vault.
- Facial recognition or sensitive-trait inference from photos.
- Medical, legal, or financial decision making.
- Broad organization-wide ingestion or team knowledge sharing.

## Risks and open decisions

- Chat and photo providers differ in export formats and API permissions; start with local imports and publish a connector support matrix.
- Disclose which model provider receives content and its retention terms before inference.
- Background sync must be bounded, observable, and revocable.
- Define retention defaults and backup deletion guarantees before multi-user hosting.
- Confirm whether self-hosted deployments need a first-class local-only mode; current direction is cloud-first.
