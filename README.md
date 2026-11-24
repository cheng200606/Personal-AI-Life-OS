# Personal AI Life OS

**Your work and learning, captured with your consent, connected into useful personal memory.**

An open source, cloud-first system for bringing together selected chat exports, photos, and agent memory files; turning them into a searchable timeline and linked notes; and helping you review progress and commitments. Obsidian is the portable Markdown interface.

> **Status:** project foundation / MVP planning. The API currently has a health endpoint; source connectors and AI workflows are planned, not yet implemented.

## Product decisions

- Direction: integrated research across a person's work, learning, and life.
- Audience: broad, with individual privacy and portability as defaults.
- License: Apache-2.0.
- Architecture: cloud processing with explicit, user-controlled source sync.
- Interfaces: web review experience plus local source and Obsidian workflows.

## MVP path

1. Select files to sync: ChatGPT exports, photos, and agent `memory.md` files.
2. Normalize source items with timestamps, provenance, and duplicate detection.
3. Generate editable summaries, timeline entries, and review prompts.
4. Prepare weekly reviews and reminders from user-approved action items.
5. Export notes to an Obsidian vault as plain Markdown.

The first release will not scrape private chats or monitor devices in the background. It will process only sources the user explicitly connects or imports. See the [MVP PRD](docs/product/prd.md) and [architecture](docs/architecture/overview.md).

## Development

Requirements: Python 3.11+, Docker Compose.

```powershell
Copy-Item .env.example .env
docker compose up -d db redis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
uvicorn personal_ai_life_os.main:app --reload
```

Health check: `http://127.0.0.1:8000/api/v1/health`.

## Repository map

- `src/personal_ai_life_os/`: Python API foundation.
- `docs/product/`: product requirements.
- `docs/architecture/`: system and privacy design.
- `docs/roadmap/`: milestones and starter issues.

See [CONTRIBUTING.md](CONTRIBUTING.md) and [Good First Issues](docs/contributing/good-first-issues.md).

## 中文简介

Personal AI Life OS 是一个开源、云端优先的个人知识系统。用户可以选择同步聊天导出、照片和 agent 的 `memory.md`，将工作与学习经历整理成带来源的时间线、可编辑笔记、周期复盘和提醒，并导出为 Obsidian Markdown。

目前仓库处于项目框架阶段。API 只有健康检查；数据连接和 AI 工作流仍在路线图中。系统不会抓取私人聊天或在后台监控设备，只处理用户明确导入或授权的资料。

## License

Apache-2.0. See [LICENSE](LICENSE).
