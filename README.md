# Personal AI Life OS

**Your work and learning, captured with your consent, connected into useful personal memory.**

An Apache-2.0 open source project for importing selected chat exports, photos, and agent memory files; reviewing a source-linked timeline; preparing weekly reflections and reminders; and exporting portable Markdown for Obsidian.

> **MVP status:** the local API, CLI, web workflow, review/reminder flow, photo processing, and production deployment templates are implemented. The project has not been deployed to a hosted environment or approved for real personal data. Follow the [release checklist](docs/operations/release-checklist.md) before inviting users.

## What works

- Select and preview Markdown or ChatGPT export files locally. Chat messages are not printed in preview; the upload contains only chosen conversations.
- Import Claude, Gemini, ZCode, DeepSeek harness, and WorkBuddy JSON/JSONL or Markdown exports, plus TXT, text-based PDF, and DOCX documents. Text extraction is local; scanned PDFs are not supported yet.
- Extract an evidence graph from manually selected items: entities, relations, exact quotes, confidence, and a low-confidence review state. Cloud extraction requires per-source consent, a configured provider, and the monthly/per-call budget.
- Review, edit, approve, or reject low-confidence items; merge duplicate entities with a reversible snapshot; and approve custom ontology types before they enter later extraction prompts.
- Ask questions over active evidence in the Chinese-first Ask page. Answers include structured facts, original citations, confidence, fact/inference/uncertain labels, missing information, and action suggestions. Threads remember the last scope and can be exported or deleted; revoked sources and deleted evidence are excluded.
- Review four explainable rule insights: overdue goals, commitments without follow-up, stalled projects, and skills with weak evidence. Dismissed false positives do not repeat.
- Let the agent create reminders, tasks, projects, growth records, goal progress, and review drafts automatically, with an in-app audit record and a 24-hour undo. External sending, file changes, spending, and deletion or goal changes always require human approval.
- Install local connector and agent-tool plugins from a manifest. The reference JSON/Markdown connector can preview and import selected files; the reference graph-search tool reads owner-scoped evidence. Undeclared permissions are denied and plugin failures are isolated.
- Use the Chinese-first navigation for timeline, Ask, graph, pending review, projects and goals, reviews, search, and settings, including budget, plugins, and source authorization.
- Import up to ten user-selected JPEG, PNG, or WebP photos, including from a selected folder. The server re-encodes images to strip metadata and runs OCR inline or as a recoverable job, depending on configuration. Optional external reviews and photo descriptions require consent and use jobs in worker mode.
- Browse and search an owner-scoped timeline with date and source filters, inspect the original source, and export stable Markdown files with conflict handling.
- Search timeline items, weekly reviews, and reminders together on one page, with grouped results, per-group totals, snippets, and links back to each record.
- Generate an editable weekly review with source citations, save reminders, and export reviews as Markdown. Template reviews continue to work if external AI is unavailable. Save a weekly day/time to generate drafts automatically in worker mode, and see due or overdue reminders in the sidebar and "Due now" panel.
- Run a daily folder sync through the CLI with the Windows Task Scheduler helper; repeated runs reuse the source and SHA-256 deduplication.
- Pause, resume, or revoke a source; download an account archive; delete a source or account.
- Run with SQLite and local object storage for development, PostgreSQL in Compose, or a private S3-compatible store in a production deployment.

The current search uses bounded, case-insensitive SQL `LIKE` substring matching across timeline items, weekly reviews, and reminders; there is no full-text or semantic index. Scheduled folder sync and scheduled weekly review drafts are available. Full-text/vector search, broad connectors, email or push delivery, and mobile capture remain outside this MVP.

## Local development

### GitHub Codespaces

Create or rebuild a Codespace using this repository's Dev Container configuration. It installs the locked Python and Node dependencies and starts the development stack. Open the **Web client** on private port 5173 in the Ports panel. The stack uses synthetic data for acceptance exercises and disables external AI. See the [Codespaces verification commands](docs/operations/deployment.md#synthetic-acceptance-in-codespaces). [GitHub Dev Containers](https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces/adding-a-dev-container-configuration/introduction-to-dev-containers)

### API and CLI

For development on your own machine, install Python 3.11+ with [uv](https://docs.astral.sh/uv/) and Node.js 24 with npm for the Web client. Docker Desktop is optional for API-only work.

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

### Optional cloud AI

External reviews and photo descriptions stay off by default so a local instance runs without a provider key. To enable them, set `MODEL_PROVIDER=openai`, `OPENAI_API_KEY`, and non-zero `MODEL_INPUT_COST_PER_MILLION_USD` / `MODEL_OUTPUT_COST_PER_MILLION_USD` values. Any OpenAI-compatible gateway works: point `OPENAI_BASE_URL` at its API root. The web client asks for consent before the first external call, and template reviews keep working when the provider is unavailable. Graph extraction uses the same configured provider by default; `GRAPH_MODEL_PROVIDERS` can define named providers, and `MODEL_MONTHLY_BUDGET_USD` (default 5.00) warns at 80% and blocks over-budget calls. Every source needs an explicit cloud-extraction consent before its items can be sent.

Local data lives in `data/lifeos.db` and `data/objects`. Copy both together to back up or move the instance.

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
uv run python scripts/evaluate_search.py
uv run python scripts/evaluate_graph_qa.py
uv run python scripts/benchmark_mvp.py
```

The benchmark uses only generated data on local SQLite; it is not evidence of hosted PostgreSQL performance. For production configuration and database backup/restore procedures, see [deployment](docs/operations/deployment.md), [backup and restore](docs/operations/backup-restore.md), and the [support matrix](docs/operations/support-matrix.md).

## Repository map

- `src/personal_ai_life_os/`: API, CLI, parsers, storage, and lifecycle services.
- `web/`: React and TypeScript review client.
- `migrations/`: versioned SQLAlchemy/Alembic schema changes.
- `fixtures/synthetic/`: fabricated import and review evaluation data only.
- `scripts/`: synthetic review, search, graph-Q&A evaluation, and local performance benchmarks.
- `docs/`: product requirements, architecture, roadmap, operations, and contributor guidance.

## 中文简介

Personal AI Life OS 是一个 Apache-2.0 开源的个人工作与学习记忆系统。用户明确选择资料后，可以导入 ChatGPT、Claude、Gemini、ZCode、DeepSeek harness、WorkBuddy 导出，以及 Markdown/TXT/PDF/DOCX 文档，查看可追溯的时间线，抽取带证据的实体/关系图谱，生成可编辑周复盘与提醒，并导出 Obsidian Markdown。可设置每周复盘计划并在应用内查看到期/逾期提醒，也可用 Windows 计划任务运行可重复的文件夹同步。

v0.5 进一步提供中文优先的时间线、提问、图谱、待审、项目与目标、复盘、搜索和设置界面；图谱支持低置信度待审、可撤销实体合并与自定义本体；个人问答只使用有效证据并给出引用与置信度；四条规则洞察支持忽略误报；Agent 可在 24 小时内撤销内部写入，四条红线必须人工批准；本地插件清单同时覆盖参考连接器与图谱检索工具。

MVP 的本地开发主流程已实现，但尚未部署到托管环境，也未通过真实用户私测准入。不要把真实个人资料放入未验证的共享部署；上线前请完成[发布清单](docs/operations/release-checklist.md)。

## License

Apache-2.0. See [LICENSE](LICENSE).
