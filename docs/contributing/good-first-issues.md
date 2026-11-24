# Good First Issues

Starter issue drafts for the initial public backlog. Each task is bounded and can be implemented independently after its prerequisite interfaces are agreed.

## 1. ChatGPT export format inventory

**Labels:** `good first issue`, `documentation`


Document the export files and fields needed for messages, timestamps, and conversation IDs. Use small synthetic fixtures only; never commit a real personal export.

## 2. Markdown memory parser

**Labels:** `good first issue`, `parser`


Propose and implement a parser interface for a selected `memory.md` file. Preserve headings, links, and source line ranges as provenance.

## 3. Sync preview CLI design

**Labels:** `good first issue`, `cli`


Add a command that lists candidate files under explicitly provided paths, reports file size/type/hash, and requires confirmation before upload. Do not scan outside selected paths.

## 4. Obsidian note frontmatter spec

**Labels:** `good first issue`, `documentation`


Specify stable IDs, date format, tags, and source links for exported notes. Include a conflict policy that never silently overwrites user content.

## 5. Source consent copy

**Labels:** `good first issue`, `privacy`, `documentation`


Draft permission and revocation text for file import and future provider connectors. State fields read, storage, processing, and deletion behavior.

## 6. Sync run state model

**Labels:** `good first issue`, `backend`


Define statuses and error categories for retryable sync runs, including pause/cancel and partial failure behavior.

## 7. Synthetic photo fixture guidance

**Labels:** `good first issue`, `documentation`


Document how contributors can create safe, synthetic image metadata fixtures without including personal photos or EXIF data.

## 8. Weekly review prompt evaluation set

**Labels:** `good first issue`, `ai`


Create a tiny synthetic dataset and rubric to check source citations, fact/suggestion separation, and unsupported claims.

## 9. API health endpoint documentation

**Labels:** `good first issue`, `documentation`


Add an OpenAPI usage snippet and explain the difference between API liveness and dependency readiness.
