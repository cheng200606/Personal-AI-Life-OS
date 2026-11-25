# Local and CI MVP Verification Record

**Date:** 2026-11-25
**Implementation commit:** `9fe60f4` (`feat: add recoverable worker and photo batch imports`)
**CI verification head:** `9fe60f4`; [run `45465885873`](https://github.com/cheng200606/Personal-AI-Life-OS/actions/runs/45465885873) passed on this revision
**Data:** generated fixtures and generated benchmark rows only; no personal source material
**Runtime:** Windows, local SQLite, FastAPI `TestClient`, Node/npm; production credentials unavailable

## Results

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Pass |
| GitHub Actions `uv run pytest` (Python 3.11 and 3.12) | 40 passed; one upstream test warning |
| `uv run python scripts/evaluate_reviews.py` | 30 cases; source location 100%; evidence support 100%; unsupported claims 0 |
| `uv run python scripts/benchmark_mvp.py` | Pass against local targets; measurements below |
| `uv run alembic upgrade head` in the Docker Compose CI smoke | Pass; all five migrations applied before readiness |
| `npm run lint` in `web/` | Pass |
| `npm run build` in `web/` | Pass |
| GitHub Actions run `45465885873` | Pass: Linux Python 3.11/3.12 lint and tests, Web lint/build, Docker Compose image build, startup, readiness checks, and cleanup. The runner reports a non-blocking Node.js 20 action-runtime deprecation notice. |
| `docker compose --env-file .env.example -f docker-compose.yml config --quiet` | Pass |
| `docker compose --env-file .env.production.example -f docker-compose.production.yml config --quiet` | Pass |
| `bash -n scripts/backup-production.sh scripts/restore-production.sh` | Pass |
| `git diff --check` | Pass |

## Synthetic performance run

- Timeline: 10,000 SQLite rows; 30 requests per query type. P95 was 43.55 ms for date range, 39.38 ms for source filter, and 49.26 ms for keyword lookup. Target: ≤500 ms.
- Import: 30 API imports, 500 parsed Markdown sections each, 50,498-byte file. P95 was 1,669.89 ms. Target: ≤30,000 ms.
- The benchmark ran against local SQLite and the in-process test client. It does not establish hosted PostgreSQL throughput or public-network latency.

The recorded API suite exercises model cost estimation and pricing disclosure, per-call budget fallback, estimated failed-call costs, cost fields in account archives and restricted metrics, and source-linked suggested reminders. Web CI runs lint and build. The UI contains selected-upload scope disclosure, source import status, consent revocation, reminder dismissal, and timeline pagination. Browser execution of those paths is pending dedicated evidence.

## Not verified

The local Windows Docker daemon was not available (`dockerDesktopLinuxEngine` pipe missing), so the API/web images were not built on this machine; the Linux GitHub Actions run did build and start them. No live DNS, TLS certificate, private S3 bucket, managed PostgreSQL, external provider, backup lifecycle, production restore exercise, security review, or user study was available. Those remain mandatory checklist items before accepting real personal data.
