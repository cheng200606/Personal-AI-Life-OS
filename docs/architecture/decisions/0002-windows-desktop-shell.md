# ADR 0002: Windows desktop shell with Tauri and a Python sidecar

- **Status:** Proposed
- **Date:** 2026-11-25
- **Related:** [ADR 0001](0001-cloud-first.md), [Windows desktop architecture](../desktop.md)

## Context

The current product is a React/Vite web client backed by a FastAPI API, SQLAlchemy models, alembic migrations, a database-backed worker, SQLite/local storage for development, PostgreSQL/S3 templates for hosted deployment, and a Typer CLI. The declared product scope is now a single local user, with optional OpenAI-compatible cloud model calls.

The next product form includes a Windows desktop application. It must run without Docker, keep user data local by default, and provide Windows integration that a browser cannot: tray, notifications, autostart, single instance, native file/folder selection, direct Obsidian vault writes, signed installers, and automatic updates.

Rust and PyInstaller are not installed in the current development environment. WebView2 and Node 24 are present.

## Decision

Build the Windows desktop distribution with:

- **Tauri 2** as the shell, using the system WebView2 runtime.
- The **existing React/Vite UI**, built as static assets and extended with a small runtime adapter.
- A **packaged Python sidecar** (PyInstaller one-folder, Python 3.12 x64) that runs the existing FastAPI app, worker, SQLite database, local object store, Alembic migrations, and bundled Tesseract (English and Simplified Chinese).
- A **loopback-only local API** on a random port, protected by the existing bearer auth plus a per-launch desktop secret.
- **Local-first data** under `%LOCALAPPDATA%\PersonalAILifeOS`, with migration backups and signed auto-updates.
- **Tauri-owned OS integration** for file selection, folder authorization, notifications, Obsidian vault writes, single instance, tray, and autostart.

The existing web client remains supported as the development/reference client and the optional hosted path. Business logic stays in the Python API; the desktop shell must not fork domain behavior.

## Consequences

- Most API, domain, and UI code is reused; the main new code is desktop lifecycle, OS integration, packaging, signing, and update handling.
- A `desktop` configuration profile is required: SQLite, local object storage, worker enabled, no production TLS/invite/S3 requirements, loopback binding.
- Tokens must move from `sessionStorage` to Windows Credential Manager for persistent desktop sessions.
- File access is mediated by the Tauri shell; the sidecar must not accept arbitrary filesystem paths.
- Installer size and cold-start time include the Python runtime and Tesseract; these must be measured in D0.
- Windows CI, code signing, signed update manifests, and upgrade/rollback tests become release requirements.
- Web and desktop need a shared runtime adapter and the same test suite to avoid behavioral drift.
- The architecture adds a Rust toolchain and a Windows packaging pipeline; if Tauri blocks signing or WebView2 compatibility, Electron is the fallback.

## Alternatives considered

- **Electron + Python sidecar:** simpler JavaScript-only shell and mature packaging, but a larger installer, higher memory use, and more security hardening.
- **PyWebView + Python:** smallest change and no Rust, but weak updater, tray, permission, and release-security capabilities for a product distribution.
- **WinUI/WPF + WebView2:** strongest native integration, but requires a new C# stack and a second UI implementation.
