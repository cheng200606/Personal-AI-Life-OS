# MVP Support Matrix

The current limits are enforced by the API and parsers where possible. They should be updated with any release that changes parser behavior.

| Input / workflow | Supported | Limit and behavior | Not supported in this MVP |
| --- | --- | --- | --- |
| Agent memory / notes | UTF-8 `.md` and `.markdown` files through CLI or web | 5 MB per file. Markdown headings become separate timeline entries; a `YYYY-MM-DD` in a heading sets the date. Source file and line range are retained. Missing dates stay unknown. | PDF, DOCX, HTML, arbitrary directories outside explicitly selected files, non-UTF-8 input |
| ChatGPT export | UTF-8 JSON through CLI or web | 5 MB per file. Root array or an object containing a `conversations` array. Each conversation uses a `mapping` of message nodes or a `messages` array. Only `user` and `assistant` text is parsed. The user selects conversation IDs locally; only those conversations are uploaded. Message and conversation identifiers are retained. | Direct ChatGPT API access, scraping, unselected conversation upload, audio/video/other binary message extraction, unrecognized JSON layouts |
| Photos | User-selected JPEG/JPG, PNG, or WebP through the web app | Up to 10 photos per selection, including one user-selected folder. Each photo is limited to 20 MB and 40 megapixels by default. The server applies orientation and re-encodes to remove EXIF/GPS metadata. OCR runs inline or as a worker job, depending on `PROCESSING_MODE`; Tesseract extracts English and Simplified Chinese text when installed. OCR may return no text or fail. User-supplied capture time requires a timezone. | HEIC/HEIF, RAW, GIF, video, face recognition, automatic photo-library scanning, guaranteed OCR quality |
| Photo description | Optional OpenAI image description through the web app | Requires provider configuration and current consent. Only the sanitized image is sent; worker mode uses a durable job. Output stays a draft until the user confirms it. | Unrequested automatic descriptions, unconfigured providers, unconditional inference |
| Weekly review | On demand or on a saved weekly schedule in the web app | Uses a selected half-open date range and at most 500 timeline items. Template mode is available without external AI. Optional external output must cite accessible source IDs and falls back on provider failure; worker mode uses a durable job. Draft suggestions can be edited, dismissed, or restored; dismissed suggestions drop out of the rendered review until restored. Scheduled generation uses the user's weekday/time and only active sources; it requires `PROCESSING_MODE=worker`, skips periods with no active items, and falls back to the template when consent, provider, or budget is unavailable. Due and overdue reminders appear in the sidebar and Weekly review page. | Cross-period automatic digest, email/push delivery, guaranteed semantic correctness of model prose |
| Scheduled folder sync | CLI plus Windows Task Scheduler | `lifeos sync <folder> --yes` reuses the source identity and SHA-256 deduplication. `scripts/register-scheduled-sync.ps1` registers a daily task, writes `data/logs/scheduled-sync.log`, and reads only the selected folder. The API must be running, and the project checkout/`uv` must remain available. | Server-side filesystem watching, cross-device sync, provider-hosted scheduling |
| Timeline lookup | Date range, source filter, keyword query | Owner-scoped, paginated, simple case-insensitive SQL `LIKE` search. Undated items can remain visible. | Full-text ranking, semantic/vector retrieval, saved searches |
| Unified search | Timeline items, weekly reviews, and reminders through the Search page | Owner-scoped, case-insensitive substring matching on titles and text. Results are grouped with per-group totals; each group returns 10 results by default and at most 20. Snippets are capped at 200 characters, and title matches sort before body matches. Deleted, non-current, `deleting`-source timeline entries and `invalidated` reviews are excluded. | Full-text ranking, semantic/vector retrieval, saved searches, cross-group relevance scoring |
| Markdown export | CLI for timeline records and confirmed reviews; web for individual records/reviews | UTF-8 Markdown, stable Life OS IDs, source/date metadata. CLI offers keep/overwrite/copy behavior and atomic writes. | Silent writes to source files or automatic Obsidian sync |

## Verification fixtures

Photo file and directory selection is available in the web importer. The CLI imports Markdown and ChatGPT JSON, and both interfaces can export a photo timeline entry as Markdown. Deleting an item can remove the shared imported original and other entries created from that original. The web action names the imported source and states that its original file and every entry created from it are removed. Photo-description and weekly review flows have their own confirmation controls. Weekly review suggestions can be edited, dismissed, or restored while the review is a draft; reminder creation uses the edited text, and the rendered review text follows automatic edits unless the user has already rewritten it.

`fixtures/synthetic/` contains fabricated Markdown and ChatGPT exports. It contains no user data. Run:

```powershell
uv run pytest -q
uv run python scripts/evaluate_reviews.py
uv run python scripts/evaluate_search.py
```

`scripts/evaluate_search.py` runs 22 bilingual queries against 10,000 synthetic timeline rows plus reviews and reminders. It defaults to disposable SQLite data and accepts a separate PostgreSQL database through `LIFEOS_BENCHMARK_POSTGRES_URL` when one is available.

`scripts/benchmark_mvp.py` separately measures 30 timeline-query samples against 10,000 synthetic SQLite rows and 30 imports of 500 synthetic Markdown sections. It is a local smoke benchmark, not hosted performance evidence.
