# Local MVP Verification Record

**Date:** 2026-11-25
**Base revision:** `7f7156a` with uncommitted MVP implementation changes in this working tree
**Data:** generated fixtures and generated benchmark rows only; no personal source material
**Runtime:** Windows, local SQLite, FastAPI `TestClient`, Node/npm; production credentials unavailable

## Results

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Pass |
| `uv run pytest -q` | 39 passed; one upstream Starlette deprecation warning about `httpx` in `TestClient` |
| `uv run python scripts/evaluate_reviews.py` | 30 cases; source location 100%; evidence support 100%; unsupported claims 0 |
| `uv run python scripts/benchmark_mvp.py` | Pass against local targets; measurements below |
| `uv run alembic upgrade head` on a fresh temporary SQLite database, then `uv run alembic check` | Pass; all four migrations applied, no model/schema drift |
| `npm run lint` in `web/` | Pass |
| `npm run build` in `web/` | Pass |
| GitHub Actions run `45455087848` | Pass: Linux Python 3.11/3.12 lint and tests, Web lint/build, Docker Compose image build, startup, readiness checks, and cleanup. The runner reported a non-blocking Node.js 20 action-runtime deprecation notice. |
| `docker compose --env-file .env.example -f docker-compose.yml config --quiet` | Pass |
| `docker compose --env-file .env.production.example -f docker-compose.production.yml config --quiet` | Pass |
| `bash -n scripts/backup-production.sh scripts/restore-production.sh` | Pass |
| `git diff --check` | Pass |

## Synthetic performance run

- Timeline: 10,000 SQLite rows; 30 requests per query type. P95 was 43.55 ms for date range, 39.38 ms for source filter, and 49.26 ms for keyword lookup. Target: ≤500 ms.
- Import: 30 API imports, 500 parsed Markdown sections each, 50,498-byte file. P95 was 1,669.89 ms. Target: ≤30,000 ms.
- The benchmark ran against local SQLite and the in-process test client. It does not establish hosted PostgreSQL throughput or public-network latency.

The current test set also exercises model cost estimation and pricing disclosure, per-call budget fallback, estimated failed-call costs, cost fields in account archives and restricted metrics, and source-linked suggested reminders. Web verification includes selected-upload scope disclosure, source import status, consent revocation, reminder dismissal, and timeline pagination.

## Not verified

The local Windows Docker daemon was not available (`dockerDesktopLinuxEngine` pipe missing), so the API/web images were not built on this machine; the Linux GitHub Actions run did build and start them. No live DNS, TLS certificate, private S3 bucket, managed PostgreSQL, external provider, backup lifecycle, production restore exercise, security review, or user study was available. Those remain mandatory checklist items before accepting real personal data.
