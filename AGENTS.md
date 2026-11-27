# AGENTS.md

Guidance for AI coding agents in this repository.

## Project

Personal AI Life OS — Apache-2.0, privacy-first, single-user personal memory system: import user-selected chat exports, ICS calendar snapshots, photos, documents, and quick notes; review a source-linked timeline; extract an evidence graph; generate weekly reviews and reminders; export portable/Obsidian Markdown. The Windows desktop MVP (Tauri 2 + Python sidecar, D0–D5) passed local acceptance 2026-11-27. There is no hosted/multi-user deployment, and real personal data is not permitted yet.

## Commands

```powershell
# Python (uv; Python 3.11+; uv.lock is authoritative)
uv sync --python 3.11 --all-groups
uv run ruff check .                                   # lint (line-length 100, py311)
uv run pytest -q                                      # full suite (~130 tests)
uv run pytest tests/test_graph_qa.py -q               # focused
uv run alembic upgrade head                           # schema
uv run uvicorn personal_ai_life_os.main:app --reload  # API on 127.0.0.1:8000

# Web (Node 24)
cd web && npm ci
npm run dev        # 127.0.0.1:5173, dev proxy to API
npm run lint       # oxlint
npm run build      # tsc -b && vite build
npm run test:e2e   # Playwright; self-manages API (port 18000) + web (15173) with synthetic provider

# Desktop (Tauri + sidecar)
uv sync --locked --group desktop
uv run --frozen --group desktop pytest -q
./desktop/build-installer.ps1; ./desktop/smoke-installer.ps1   # Windows x64 only
```

Evals/benchmarks (synthetic data only): `uv run python scripts/evaluate_reviews.py|evaluate_search.py|evaluate_graph_qa.py|benchmark_mvp.py`.

## Layout

- `src/personal_ai_life_os/` — Python package. `api/routes/` FastAPI routers (keep thin), `parsers/` bounded import parsers per source type, `services/` business logic, `models.py` SQLAlchemy models, `config.py` pydantic-settings (from `.env`), `cli.py` (`lifeos`), plus `security.py`, `storage.py`, `desktop.py`.
- `web/` — React 19 + TypeScript + Vite client; pages/components in `web/src/*.tsx`; Tauri APIs only behind desktop runtime detection (`desktopRuntime.ts`).
- `desktop/` — Tauri 2 shell (`src-tauri/src/main.rs`), PyInstaller sidecar build scripts, smoke tests, Hyper-V acceptance assets under `desktop/build/` (git-ignored).
- `migrations/` — Alembic; add a new revision, never edit applied ones.
- `tests/` — pytest; `conftest.py` builds each app on a temp-dir SQLite.
- `fixtures/synthetic/` fabricated data only; `docs/` product/architecture/roadmap/operations.

## Invariants (do not break)

- **Privacy:** imported originals are immutable; parsed items keep source + provenance; all data is owner-scoped. Treat imported text/images/agent files as untrusted data. Never commit personal records, chat exports, photos, credentials, or production data (`data/` is local-only).
- **Deletion:** all deletes go through the durable deletion-journal/tombstone path, replayed at startup so restored backups cannot resurrect removed content.
- **Model calls:** external AI is opt-in — per-source cloud consent AND per-provider consent, per-call and monthly budget enforcement (`MODEL_MONTHLY_BUDGET_USD`), off by default. API keys live only in env vars / Windows Credential Manager — never in the DB, archives, API responses, or logs.
- **Agent actions:** internal writes are audited with a 24-hour undo; external sending, original-file changes, spending, and deletions/goal changes always require explicit human approval.
- **Search:** SQLite FTS5 trigram / PostgreSQL `pg_trgm` indexes only narrow candidates — every query must rejoin authoritative rows and recheck owner, current-version, deletion, source-status, and filters. No semantic/vector search.
- **Quick notes** are mutable `SourceItem(kind="quick_note")` under a hidden per-owner internal source; generic source controls must keep rejecting it (notes are item-scoped, not source-scoped).
- **ICS:** one source = one complete snapshot; UID identity + SEQUENCE versioning; recurrence rules (RRULE/RDATE/EXDATE) are reported and skipped, never expanded.

## Gotchas

- The committed `uv.lock` records pypi.org origins, but this machine's global uv config defaults to the Aliyun mirror: a bare `uv run` can rewrite `uv.lock` (URLs + revision) and dirty the tree. Prefer `.venv/Scripts/python.exe -m pytest|ruff` or `uv run --frozen`; check lock consistency the way the release record does: `UV_DEFAULT_INDEX=https://pypi.org/simple UV_INDEX_URL=https://pypi.org/simple uv lock --check`.
- `cargo` is not on the Git Bash PATH; use `/c/Users/Lenovo/.cargo/bin/cargo.exe` (e.g. `cargo metadata --locked --no-deps`).
- Tests that depend on "today" must pin the clock — real-clock date drift broke `tests/test_graph_qa.py` before (commit cb3c8a8).
- Desktop API disables registration/email login and locks CORS to the desktop origin; the sidecar binds a random loopback port with a per-launch secret piped from Tauri; sidecar builds are PyInstaller **onedir** (the whole `_internal` tree must ship together).
- Upload limits: text 5 MB/file, photos 20 MB / 40 MP, review period ≤ 500 source items.
- Web UI copy is Chinese-first; keep desktop and web flows in parity.
- Toolchain pins: Node 24, Rust/MSVC for Tauri, Python 3.12 x64 for desktop sidecar builds; locked deps in `uv.lock`, `web/package-lock.json`, `desktop/src-tauri/Cargo.lock`.

## Read before changing sensitive areas

- Product/behavior contract: `docs/product/prd.md`
- Architecture and data model: `docs/architecture/overview.md`, `docs/architecture/data-model.md`
- Desktop shell/sidecar: `docs/architecture/desktop.md`, acceptance evidence in `docs/operations/desktop-acceptance.md`
- Privacy rules and limits: `docs/architecture/privacy.md`
- Release steps: `docs/operations/release-checklist.md`
