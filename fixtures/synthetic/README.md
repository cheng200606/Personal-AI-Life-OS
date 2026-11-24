# Synthetic demo dataset

All names, conversations, events, and dates in this directory are fabricated for development and evaluation. Do not replace these files with personal exports.

The two-week sample contains:

- Markdown with dated sections, a missing date, and line-addressable evidence.
- A ChatGPT-shaped JSON export with a decision, follow-up, and an instruction-like user message that must remain inert data.
- A repeated-file case: importing the same fixture twice must not add duplicate source records.

Expected counts and facts are in `expected-ingest.json`.

`review-eval.json` adds 30 review cases: supported facts, conflicting sources, insufficient evidence, local-time boundaries, duplicate evidence, and model-failure fallback. Run `uv run python scripts/evaluate_reviews.py` to measure the deterministic template path. A separate API test forces a provider failure and verifies the cited template fallback.
