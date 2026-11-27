## 1. 使用的框架与工具

该仓库是 Python FastAPI + React Web + Rust/Tauri Desktop + PostgreSQL 的多组件项目，采用以下构建链：

- **依赖管理**：使用 [uv](https://github.com/astral-sh/uv)（镜像 `ghcr.io/astral-sh/uv:0.12.5`）进行锁定式依赖同步；Python 包元数据位于 `pyproject.toml`（`setuptools.build_meta`），锁定文件为根级 `uv.lock`。
- **Web 前端**：Vite + TypeScript + Playwright，由 `web/package.json` 中的 npm 脚本驱动，产物由 `nginx:1.29-alpine` 托管。
- **桌面客户端**：Tauri v2（Rust 1.100.0），在 Windows 上通过 NSIS 打包 `.exe`。
- **容器化**：`Dockerfile`（后端）、`web/Dockerfile`（前端）、`.devcontainer/Dockerfile`（开发环境）三个独立镜像，以及 docker-compose.yml / production.yml / codespaces.yml 编排。
- **CI/CD**：GitHub Actions，两个 workflow——通用 CI（lint/smoke）和独立的 Windows 桌面构建流程。

## 2. 关键文件

- 根级构建入口：`Dockerfile`、`pyproject.toml`、`alembic.ini`、`docker-compose.production.yml`、`docker-compose.yml`、`docker-compose.codespaces.yml`
- Web 前端：`web/Dockerfile`、`web/nginx.conf`、`web/vite.config.ts`、`web/playwright.config.ts`
- 桌面客户端：`desktop/src-tauri/Cargo.toml`、`desktop/src-tauri/tauri.conf.json`、`desktop/build-installer.ps1`、`desktop/build-sidecar.ps1`、`desktop/prepare-ocr.ps1`
- CI：`.github/workflows/ci.yml`、`.github/workflows/desktop.yml`
- 开发环境：`.devcontainer/Dockerfile`、`.devcontainer/devcontainer.json`、`.devcontainer/setup.sh`
- 迁移：`migrations/env.py`、`migrations/script.py.mako`、`alembic.ini`

## 3. 架构与约定

### 后端 (Python)
- `Dockerfile` 以 `python:3.12-slim` 为基础镜像，从 GitHub Container Registry 拉取 uv 二进制，先安装 OCR（`tesseract-ocr` + `chi-sim`）并创建非 root 用户 `lifeos`。
- 依赖安装分为两阶段：先仅安装生产依赖（`--no-dev --no-install-project`），再 `COPY src/` 后二次 `uv sync` 以避免将源代码缓存进虚拟环境层。
- 运行时命令直接执行 `uvicorn personal_ai_life_os.main:app`，默认 `0.0.0.0:8000`。
- `pyproject.toml` 声明 Python ≥3.11，版本 `0.1.1`。依赖组按用途划分：`desktop`（PyInstaller、ijson）、`dev`（ruff、pytest-cov）。Ruff 行宽限制 100，目标 py311。

### 前端 (Web)
- `web/Dockerfile` 双阶段构建：`node:24-alpine` 中 `npm ci` → `npm run build`，再由 `nginx:1.29-alpine` 静态托管 `dist/`。
- Healthcheck 通过 `wget -qO- http://127.0.0.1/` 验证 Nginx 可达性。
- E2E 测试使用 Playwright（`playwright.config.ts`）。

### 桌面端 (Tauri)
- CI 仅在 PR/触发器匹配 `desktop/** | src/** | web/** | tests/test_desktop_mvp.py | migrations/** | uv.lock | .github/workflows/desktop.yml` 时运行。
- Windows Labeled `windows-latest`，耗时上限 35 分钟；步骤顺序为：setup python 3.12 → setup Node 24 → rustup install 1.100.0 → `npm ci` → `uv sync --locked --group desktop` → pytest desktop MVP → PowerShell 构建流程。
- `build-installer.ps1` 强制要求先在 `web/` 执行 `npm ci`，然后依次调用 `prepare-ocr.ps1`、`build-sidecar.ps1`，最终 `tauri.cmd build --bundles nsis -- --locked`；产物路径为 `desktop/src-tari/target/release/bundle/nsis/*.exe`，并通过 `Get-FileHash` 输出校验值作为 Artifact 上传。
- `smoke-installer.ps1` 用于安装器冒烟测试。

### Compose 编排
- `docker-compose.production.yml` 定义三层：Caddy 反代（暴露 80/443，需 `LIFEOS_DOMAIN`）→ Nginx Web（依赖 api 健康）→ FastAPI（依赖 pgvector/pg16，启动前执行 `alembic upgrade head`）→ PostgreSQL（pgvector 扩展）。
- API healthcheck 调用 `/api/v1/ready`，DB healthcheck 用 `pg_isready`。
- 部署变量强制校验（`${VAR:?Set ...}`），包含 S3 对象存储、模型供应商、Secrets 等。

### DevContainer
- 基础镜像 `mcr.microsoft.com/devcontainers/base:ubuntu-24.04`，叠加 uv 二进制（`uv:0.12.5`）和中文字体 `fonts-noto-cjk`。

## 4. 约定与约束

- **锁定依赖**：所有 `uv` 调用均使用 `--locked` / `--frozen`（见 `Dockerfile` 与 CI 各 step），禁止在安装/构建时变更 `uv.lock`。
- **Python 兼容矩阵**：CI matrix 覆盖 3.11 与 3.12（`ci.yml` 的 `strategy.matrix.python-version`）；运行时基线 `>=3.11`。
- **Node 版本固定**：CI 使用 `actions/setup-node@v4` 指定 Node 24；前端 Docker 亦基于 `node:24-alpine`。
- **Rust 版本固定**：桌面 CI 通过 `rustup toolchain install 1.100.0 --profile minimal` 显式安装特定版本。
- **安全运行**：后端容器以 `USER lifeos` 非 root 用户运行，工作目录 `/app`，数据目录 `/data` 均 chown 给该用户。
- **健康检查契约**：HTTP API 必须提供 `/api/v1/health` 与 `/api/v1/ready` 两个端点，被 `ci.yml` 与 `production.yml` 共同依赖。
- **发布制品**：桌面候选安装包作为 GitHub Actions artifact 上传，artifact 名 `lifeos-windows-x64-candidate`，类型为 `*.exe`。
- **迁移入口**：容器启动通过 `alembic upgrade head` 自动应用迁移，版本号位于 `migrations/versions/` 目录下（Alembic 风格命名哈希）。
- **环境变量必填校验**：Production Compose 通过 `${VAR:?message}` shell 语法强制要求外部注入必要配置（DATABASE_URL、ACCESS_TOKEN_SECRET、S3_*、OPENAI_* 等），缺失即中止服务启动。
