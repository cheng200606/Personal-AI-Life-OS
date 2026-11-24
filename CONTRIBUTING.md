# Contributing

Thanks for helping build Personal AI Life OS. The project is early; focused issues and clear design notes are especially useful.

## Before you start

1. Read the [MVP PRD](docs/product/prd.md) and [architecture](docs/architecture/overview.md).
2. Find an existing issue or open one to discuss substantial changes.
3. For new connectors, explain permissions, collected fields, deletion, and export behavior.

## Development

Use Python 3.11 or later. Copy `.env.example` to `.env`, start local services with `docker compose up -d db redis`, install with `python -m pip install -e .`, and run `uvicorn personal_ai_life_os.main:app --reload`.

## Expectations

- Keep imported items traceable to their origin and timestamp.
- Treat imported text, images, and agent files as untrusted user data.
- Do not commit personal records, chat exports, photos, memory files, credentials, or production data.
- Keep original source content intact. Mark AI-generated notes and make them editable.
- Avoid broad permissions and background collection. Each connector must show what it reads and how to revoke access.
- Document configuration and data-model changes.
- Use clear commit messages and small, reviewable pull requests.

Contributions are submitted under the Apache-2.0 license described in [LICENSE](LICENSE).
