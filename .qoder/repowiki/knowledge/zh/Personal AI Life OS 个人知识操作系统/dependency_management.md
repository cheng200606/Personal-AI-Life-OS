## 总体策略

Personal AI Life OS 是一个跨三种语言的后端+前端+桌面应用，每个子模块各自采用其社区标准依赖管理器，仓库根目录不维护统一的顶层依赖清单：

- Python 后端（`src/personal_ai_life_os/`）使用 **uv**（Ruff/Crates.io 团队开发的 Python 包管理器），以 `pyproject.toml` 声明版本范围、以 `uv.lock` 做可重复解析。
- Rust 桌面壳（`desktop/src-tauri/`）使用 **Cargo**，由 `Cargo.toml` 与 `Cargo.lock` 锁定依赖树。
- Web 前端（`web/`）使用 **npm**（Node.js），由 `package.json` + `package-lock.json` 锁定。

三个子树之间没有跨语言的共享依赖图。CI/构建脚本分别在对应目录调用各自工具。

## Python 端：uv 与 pyproject.toml

### 关键文件
- `pyproject.toml`：声明构建系统、运行时依赖与依赖组。
- `uv.lock`：由 uv 生成的完整 lockfile，包含所有直接/传递依赖的精确版本、来源（PyPI URL）、sha256 hash、sdist/wheel 元数据与 `requires-python` 标记解析。

### 依赖分组约定
`pyproject.toml` 把 Python 依赖分成三个层次：

1. **运行时依赖**（`[project].dependencies`）：FastAPI、SQLAlchemy、Alembic、Boto3、psycopg[binary]、pydantic-settings、Typer、Uvicorn、Pillow、PyJWT、python-multipart、pytesseract、pypdf、python-docx、icalendar，全部使用“最小主版本号”上限（如 `>=0.115,<1.0`），遵循 [pdm/pipenv-style semver-major pinning](https://github.com/astral-sh/uv) 风格。Python 要求统一为 `requires-python = ">=3.11"`。
2. **`[dependency-groups].desktop`**：打包侧依赖 `ijson`、`pyinstaller`、`tzdata`、`pywin32-ctypes`（带 `sys_platform == 'win32'` 条件）。该组仅被 desktop 相关构建流程消费。
3. **`[dependency-groups].dev`**：测试与格式化依赖 `pytest`、`pytest-cov`、`ruff`。

这些不是 `install-dependencies` 的入口点——实际通过 `uv sync --group <name>` 或 `uv pip install -e .[dev]` 方式消费（参考 `docker-compose.yml` / `Dockerfile` / `.github/workflows/ci.yml`）。`[project.scripts]` 暴露 CLI entrypoint：`lifeos = "personal_ai_life_os.cli:app"`。

### Lockfile 约束
`uv.lock` 固定了每一个包的:
- `version`
- `source = { registry = "https://pypi.org/simple" }`
- sdist/wheel 的下载 URL 与 `sha256`
- `size`、`upload-time`
- 依赖间版本兼容性以及按 `resolution-markers`（如 `python_full_version >= '3.15'`、`== '3.14.*'`、`< '3.14'`）分支选用的不同版本。这意味着在任意环境安装都必须与锁文件完全一致。

### PyPI 源 & 私有仓库
当前仓库中未发现自定义 `[[tool.uv.sources]]` 段、`.uvrc`、`PIP_INDEX_URL`、环境变量中的镜像地址或私有注册表配置；所有 source 均为 `https://pypi.org/simple`。即：**无私有 PyPI 仓库**。若引入企业私有包需手动在 `pyproject.toml` 或 uv 配置中添加源定义（uv 官方支持的 `[tool.uv.sources]`/`--index-url`），但该项目未启用。

## Rust/Tauri 端：Cargo
- `desktop/src-tauri/Cargo.toml` 以语义化版本范围声明 `tauri` v2 生态（`tauri-plugin-dialog/notification/single-instance`、`tauri-build` v2），核心库 `serde`/`serde_json`/`sha2`/`hmac` 也采用“最小版 + 通配范围”。
- `desktop/src-tauri/Cargo.lock`（存在于仓库）提供完整可重复构建的依赖快照，是 cargo build/install 的权威来源。

## Node/Web 端：npm
- `web/package.json`：仅包含少量运行时依赖 (`react`, `react-dom`, `@tauri-apps/api`) 与 dev 依赖 (Vite、TypeScript、Playwright、oxlint、Tauri CLI)。React 和 Vite 等依赖使用 `^` 宽松前缀，配合 `web/package-lock.json` 记录精确解析。
- 无前端的 workspace 聚合：不存在 monorepo 式依赖共享。

## CI 与构建对依赖的引用
GitHub Actions（`.github/workflows/ci.yml`、`.github/workflows/desktop.yml`）在 Python 阶段通常会调用 `uv sync`（而非 `pip install`），保证使用 `uv.lock` 提供的确定性解析；Tauri 构建则通过 `cargo build --release` 消费 `Cargo.lock`；Web 前端通过 `npm ci` 消费 `package-lock.json`。三者各自隔离，不在 CI 中尝试跨包管理器同步。

## 规范总结（按证据强度）

- **观测到的约定**：Python 生产依赖一律采用 `>=X,<Y`（同一主要大版本内放开），开发依赖也如此；Python 要求版本 `>=3.11`。
- **约束**：`uv.lock` 是 Python 依赖安装的权威来源（包含精确 hash 与 wheel/sdist 链接），新增/更新 Python 第三方包应通过 `uv` 修改后提交该 lockfile，而非手写 `requirements.txt`。该行为由 uv 自身的完整性校验机制强制：安装失败时会校验锁文件中记录的 sha256。
- **约束**：Tauri/Rust 依赖必须写进 `desktop/src-tauri/Cargo.toml`，并提交 `Cargo.lock`，否则 cargo 无法复现旧版本构建。
- **约束**：Web 依赖只允许写入 `web/package.json`，并通过 `package-lock.json` 锁定。
- **无私有注册表**：截至仓库快照，未观察到任何自定义 PyPI/Maven/NPM Registry 配置，三方包全部来自公共 PyPI、crates.io、npm。
- **无 vendoring**：仓库不包含 vendor/ 目录、submodule 形式的源码副本或内嵌二进制（除 `desktop/build-installer.ps1` 等 Windows NSIS 辅助脚本外，未见将上游库静态嵌入项目的通用模式）。Python 依赖均以 wheel/source distribution 形式从 PyPI 拉取。