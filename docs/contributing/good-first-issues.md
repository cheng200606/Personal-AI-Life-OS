# Good First Issues

Historical starter issue drafts with status checked against `55831c2`. Use [M4 audit and next iteration](../roadmap/next-iteration.md) for current priorities.

## 1. ChatGPT export format inventory

**Implemented for supported shapes.** [Support matrix](../operations/support-matrix.md) and synthetic parser fixtures document the supported fields. Additional variants need evidence.

**Labels:** `good first issue`, `documentation`


Document the export files and fields needed for messages, timestamps, and conversation IDs. Use small synthetic fixtures only; never commit a real personal export.

## 2. Markdown memory parser

**Implemented.** The parser and tests cover headings, line ranges, and unknown dates. Markdown links are retained in the input text.

**Labels:** `good first issue`, `parser`


Propose and implement a parser interface for a selected `memory.md` file. Preserve headings, links, and source line ranges as provenance.

## 3. Sync preview CLI design

**Implemented.** CLI preview and sync handle explicit paths, file information, and confirmation. The CLI also supports explicit non-interactive confirmation.

**Labels:** `good first issue`, `cli`


Add a command that lists candidate files under explicitly provided paths, reports file size/type/hash, and requires confirmation before upload. Do not scan outside selected paths.

## 4. Obsidian note frontmatter spec

**Partially complete.** Stable metadata and conflict handling are implemented and tested at file level. Published field examples, tag semantics, and Obsidian application acceptance remain open.

**Labels:** `good first issue`, `documentation`


Specify stable IDs, date format, tags, and source links for exported notes. Include a conflict policy that never silently overwrites user content.

## 5. Source consent copy

**File import implemented.** The UI shows selected scope and revocation; future connectors require their own disclosure.

**Labels:** `good first issue`, `privacy`, `documentation`


Draft permission and revocation text for file import and future provider connectors. State fields read, storage, processing, and deletion behavior.

## 6. Sync run state model

**Partially complete.** State and retry behavior are implemented. Production worker recovery and the complete lifecycle matrix need dedicated tests.

**Labels:** `good first issue`, `backend`


Define statuses and error categories for retryable sync runs, including pause/cancel and partial failure behavior.

## 7. Synthetic photo fixture guidance

**Partially complete.** Tests construct synthetic photo metadata in memory. The contributor directions for generating reusable OCR fixtures remain open.

**Labels:** `good first issue`, `documentation`


Document how contributors can create safe, synthetic image metadata fixtures without including personal photos or EXIF data.

## 8. Weekly review prompt evaluation set

**Template evaluation implemented.** The deterministic suite covers 30 cases. Semantic evaluation of a live provider remains open.

**Labels:** `good first issue`, `ai`


Create a tiny synthetic dataset and rubric to check source citations, fact/suggestion separation, and unsupported claims.

## 9. API health endpoint documentation

**Partially complete.** Separate liveness and readiness endpoints exist and CI exercises both. A concise OpenAPI usage example can still be added.

**Labels:** `good first issue`, `documentation`


Add an OpenAPI usage snippet and explain the difference between API liveness and dependency readiness.
