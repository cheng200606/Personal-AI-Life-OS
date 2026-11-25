# Local and CI MVP Verification Record

**Date:** 2026-11-25, re-verified at `2be4f1c` on the same day
**Implementation commit:** `9fe60f4` (`feat: add recoverable worker and photo batch imports`); current record `2be4f1c`
**CI verification head:** `9fe60f4`; [run `45465885873`](https://github.com/cheng200606/Personal-AI-Life-OS/actions/runs/45465885873) passed on this revision
**Data:** generated fixtures and generated benchmark rows only; no personal source material
**Runtime:** Windows, local SQLite, FastAPI `TestClient`, Node/npm, local Docker Compose; production credentials unavailable

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

## Re-verification at `2be4f1c`

| Check | Result |
| --- | --- |
| `uv run ruff check .` | Pass |
| `uv run pytest -q` | 50 passed; one upstream `StarletteDeprecationWarning` |
| `uv run python scripts/evaluate_reviews.py` | 30 cases; source location 100%; evidence support 100%; unsupported claims 0 |
| `npm run lint` in `web/` | Pass; 0 warnings, 0 errors |
| `npm run build` in `web/` | Pass |
| `docker compose -f docker-compose.yml -f docker-compose.codespaces.yml config --quiet` | Pass |
| `docker compose up --build --detach --wait` (local Docker, disposable port override) | Pass; `db`, `api`, and `web` reached healthy |
| `GET /` with a forwarded-host name and `GET /api/v1/health` / `ready` through the web proxy | 200, `{"status":"ok"}` and 200 |

The local Compose run used a temporary port override because a local PostgreSQL already held 5432; the volumes were removed after the check. It does not change the Codespaces configuration.

## Synthetic performance run

- Timeline: 10,000 SQLite rows; 30 requests per query type. P95 was 43.55 ms for date range, 39.38 ms for source filter, and 49.26 ms for keyword lookup. Target: ≤500 ms.
- Import: 30 API imports, 500 parsed Markdown sections each, 50,498-byte file. P95 was 1,669.89 ms. Target: ≤30,000 ms.
- The benchmark ran against local SQLite and the in-process test client. It does not establish hosted PostgreSQL throughput or public-network latency.

The recorded API suite exercises model cost estimation and pricing disclosure, per-call budget fallback, estimated failed-call costs, cost fields in account archives and restricted metrics, and source-linked suggested reminders. Web CI runs lint and build. The UI contains selected-upload scope disclosure, source import status, consent revocation, reminder dismissal, and timeline pagination. Browser execution of those paths is covered by [`web/e2e/workflow.spec.ts`](../../web/e2e/workflow.spec.ts) and the runs recorded in the [iteration log](../roadmap/next-iteration.md); this table keeps only local command results.

## Not verified

The images were built and the three Compose services reached healthy on local Docker during the `2be4f1c` re-check, but no live DNS, TLS certificate, private S3 bucket, managed PostgreSQL, external provider, backup lifecycle, hosted restore exercise, security review, or user study was available. Those remain mandatory checklist items before accepting real personal data.
