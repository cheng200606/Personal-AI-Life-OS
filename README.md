# Personal AI Life OS

**Your work and learning, captured with your consent, connected into useful personal memory.**

An Apache-2.0 open source project for importing selected chat exports, photos, and agent memory files; reviewing a source-linked timeline; preparing weekly reflections and reminders; and exporting portable Markdown for Obsidian.

> **MVP status:** the local API, CLI, web workflow, review/reminder flow, photo processing, and production deployment templates are implemented. The project has not been deployed to a hosted environment or approved for real personal data. Follow the [release checklist](docs/operations/release-checklist.md) before inviting users.

## What works

- Select and preview Markdown or ChatGPT export files locally. Chat messages are not printed in preview; the upload contains only chosen conversations.
- Import up to ten user-selected JPEG, PNG, or WebP photos, including from a selected folder. The server re-encodes images to strip metadata and runs OCR inline or as a recoverable job, depending on configuration. Optional external reviews and photo descriptions require consent and use jobs in worker mode.
- Browse and search an owner-scoped timeline with date and source filters, inspect the original source, and export stable Markdown files with conflict handling.
- Generate an editable weekly review with source citations, save reminders, and export reviews as Markdown. Template reviews continue to work if external AI is unavailable.
- Pause, resume, or revoke a source; download an account archive; delete a source or account.
- Run with SQLite and local object storage for development, PostgreSQL in Compose, or a private S3-compatible store in a production deployment.

The current text search uses bounded SQL `LIKE` matching. Vector search, broad connectors, scheduled sync, automatic review delivery, and mobile capture are outside this MVP.

## Local development

Requirements: Python 3.11+ with [uv](https://docs.astral.sh/uv/), and Node.js 24 with npm for the web client. Docker Desktop is optional for API-only work.

### API and CLI

```powershell
uv sync --python 3.11 --all-groups
Copy-Item .env.example .env
uv run uvicorn personal_ai_life_os.main:app --reload
```

The API listens on `127.0.0.1:8000` by default and uses a local SQLite database. Interactive API documentation is at `http://127.0.0.1:8000/docs`. The `lifeos` CLI offers `register`, `login`, `whoami`, `preview`, `sync`, and `export`; run `uv run lifeos --help` for usage.

### Web client

In a second terminal:

```powershell
cd web
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The development proxy connects to the local API.

### PostgreSQL and web Compose stack

```powershell
docker compose -f docker-compose.yml up --build --detach --wait
docker compose -f docker-compose.yml down
```

The API and web ports are bound to loopback. The API applies Alembic migrations before serving. Add `--volumes` to `down` only when intentionally removing the local test database and source files.

## Verification and operations

```powershell
uv run ruff check .
uv run pytest -q
uv run python scripts/evaluate_reviews.py
uv run python scripts/benchmark_mvp.py
```

The benchmark uses only generated data on local SQLite; it is not evidence of hosted PostgreSQL performance. For production configuration and database backup/restore procedures, see [deployment](docs/operations/deployment.md), [backup and restore](docs/operations/backup-restore.md), and the [support matrix](docs/operations/support-matrix.md).

## Repository map

- `src/personal_ai_life_os/`: API, CLI, parsers, storage, and lifecycle services.
- `web/`: React and TypeScript review client.
- `migrations/`: versioned SQLAlchemy/Alembic schema changes.
- `fixtures/synthetic/`: fabricated import and review evaluation data only.
- `scripts/`: synthetic review evaluation and local performance benchmark.
- `docs/`: product requirements, architecture, roadmap, operations, and contributor guidance.

## 中文简介

Personal AI Life OS 是一个 Apache-2.0 开源的个人工作与学习记忆系统。用户明确选择资料后，可以导入 ChatGPT 导出、照片和 agent 的 `memory.md`，查看可追溯的时间线，生成可编辑周复盘与提醒，并导出 Obsidian Markdown。

MVP 的本地开发主流程已实现，但尚未部署到托管环境，也未通过真实用户私测准入。不要把真实个人资料放入未验证的共享部署；上线前请完成[发布清单](docs/operations/release-checklist.md)。

## License

Apache-2.0. See [LICENSE](LICENSE).
