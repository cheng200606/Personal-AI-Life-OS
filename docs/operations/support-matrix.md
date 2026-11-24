# MVP Support Matrix

The current limits are enforced by the API and parsers where possible. They should be updated with any release that changes parser behavior.

| Input / workflow | Supported | Limit and behavior | Not supported in this MVP |
| --- | --- | --- | --- |
| Agent memory / notes | UTF-8 `.md` and `.markdown` files through CLI or web | 5 MB per file. Markdown headings become separate timeline entries; a `YYYY-MM-DD` in a heading sets the date. Source file and line range are retained. Missing dates stay unknown. | PDF, DOCX, HTML, arbitrary directories outside explicitly selected files, non-UTF-8 input |
| ChatGPT export | UTF-8 JSON through CLI or web | 5 MB per file. Root array or an object containing a `conversations` array. Each conversation uses a `mapping` of message nodes or a `messages` array. Only `user` and `assistant` text is parsed. The user selects conversation IDs locally; only those conversations are uploaded. Message and conversation identifiers are retained. | Direct ChatGPT API access, scraping, unselected conversation upload, audio/video/other binary message extraction, unrecognized JSON layouts |
| Photos | User-selected JPEG/JPG, PNG, or WebP through the web app | Up to 10 photos per selection, including one user-selected folder. Each photo is limited to 20 MB and 40 megapixels by default. The server applies orientation and re-encodes to remove EXIF/GPS metadata. OCR runs inline or as a worker job, depending on `PROCESSING_MODE`; Tesseract extracts English and Simplified Chinese text when installed. OCR may return no text or fail. User-supplied capture time requires a timezone. | HEIC/HEIF, RAW, GIF, video, face recognition, automatic photo-library scanning, guaranteed OCR quality |
| Photo description | Optional OpenAI image description through the web app | Requires provider configuration and current consent. Only the sanitized image is sent; worker mode uses a durable job. Output stays a draft until the user confirms it. | Unrequested automatic descriptions, unconfigured providers, unconditional inference |
| Weekly review | On demand in the web app | Uses a selected half-open date range and at most 500 timeline items. Template mode is available without external AI. Optional external output must cite accessible source IDs and falls back on provider failure; worker mode uses a durable job. | Scheduled delivery, cross-period automatic digest, guaranteed semantic correctness of model prose |
| Timeline lookup | Date range, source filter, keyword query | Owner-scoped, paginated, simple case-insensitive SQL `LIKE` search. Undated items can remain visible. | Full-text ranking, semantic/vector retrieval, saved searches |
| Markdown export | CLI for timeline records and confirmed reviews; web for individual records/reviews | UTF-8 Markdown, stable Life OS IDs, source/date metadata. CLI offers keep/overwrite/copy behavior and atomic writes. | Silent writes to source files or automatic Obsidian sync |

## Verification fixtures

`fixtures/synthetic/` contains fabricated Markdown and ChatGPT exports. It contains no user data. Run:

```powershell
uv run pytest -q
uv run python scripts/evaluate_reviews.py
```

`scripts/benchmark_mvp.py` separately measures 30 timeline-query samples against 10,000 synthetic SQLite rows and 30 imports of 500 synthetic Markdown sections. It is a local smoke benchmark, not hosted performance evidence.
