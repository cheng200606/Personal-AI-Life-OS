## 1. 使用的系统与工具

- **pydantic-settings** `BaseSettings`：作为唯一的运行时配置加载器，负责类型解析、默认值、环境变量注入与验证。
- **Python `.env` 文件**：可选的本地开发时覆盖层。
- **Docker / Compose 环境变量**：生产部署中通过 `docker-compose.production.yml` 以 `${VAR:-default}` / `${VAR:?error}` 形式注入配置。
- 依赖在 `pyproject.toml` 中以 `"pydantic-settings>=2.6,<3.0"` 声明。

## 2. 核心文件

| 文件 | 作用 |
|---|---|
| `src/personal_ai_life_os/config.py` | 定义 `Settings(BaseSettings)` 及其字段、默认值、`@model_validator(mode="after")` 的生产环境校验逻辑；导出单例 `settings = Settings()`。 |
| `src/personal_ai_life_os/main.py` | `create_app(config=None)` 从模块级 `settings` 或传入参数获取配置，挂载到 `application.state.settings`，并根据 `app_env`/`processing_mode` 决定是否启动后台 worker、调度器、桌面同步线程等。 |
| `docker-compose.production.yml` | 把敏感变量（`ACCESS_TOKEN_SECRET`、`SIGNUP_INVITE_CODE`、`METRICS_TOKEN`、`S3_*`）通过 `?` 操作符强制要求由外部提供，非敏感项用 `:-` 提供默认值。 |
| `tests/test_config.py` | 校验 `openai_chat_completions_url` 派生属性的行为，并构造 `Settings(_env_file=None, ...)` 来避免污染真实环境。 |

其它业务模块（`services/model_providers.py`、`security.py`、`storage.py`、`api/routes/*`、`desktop.py` 等）均通过导入模块级 `settings` 引用配置，而不是自行加载。

## 3. 架构与约定

### 分层方式

1. **定义层** (`config.Settings`)：所有配置字段在 `Settings` 中按域分组——应用模式/网络 (`app_env`, `api_host`, `api_port`)、数据库 (`database_url`, `auto_create_schema`)、worker (`processing_mode`, `worker_poll_interval_seconds`, `worker_lease_seconds`)、JWT/注册 (`access_token_secret`, `registration_mode`, `signup_invite_code`, `metrics_token`)、上传/CORS (`max_text_upload_bytes`, `cors_origins`)、对象存储 (`object_store_backend`, `s3_*`)、模型供应商 (`model_provider`, `openai_*`, `model_disclosure_*`, `model_input_cost_per_million_usd`, ...)、图构建/洞察/插件/agent 等业务开关。所有字段都有可推导 Python 类型或 Pydantic `Field(default, ge, le)` 约束。
2. **加载层**：`SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)` —— 优先从环境变量读，若存在 `.env` 再覆盖同名键；大小写不敏感；未定义的额外环境变量被忽略而非报错。
3. **使用层**：各模块直接 import `settings` 单例；FastAPI 在 `main.create_app` 中也把 `runtime_config` 挂在 `Application.state.settings`，供 DI/中间件访问。
4. **进程编排层**：`main.create_app` 根据 `app_env == "desktop"` 决定是否启用桌面桥接安全头校验、Swagger UI 是否暴露，并根据 `processing_mode == "worker"` 拉起后台处理/定时任务线程。因此配置不仅是数据，还控制进程形态。

### 生产安全门控

`validate_production_configuration` 在实例化后集中执行以下规则（来源于代码中的 `raise ValueError` 条件）：

- `S3_DELETION_JOURNAL_BUCKET` 不能与 `S3_BUCKET` 相同。
- `ACCESS_TOKEN_SECRET` 不能是默认值且长度 ≥ 32。
- `AUTO_CREATE_SCHEMA` 必须为 false（强制走 Alembic）。
- `PROCESSING_MODE` 必须为 `"worker"`。
- `REGISTRATION_MODE != "open"`；若为 `"invitation"` 则 `SIGNUP_INVITE_CODE` 必填。
- `CORS_ORIGINS` 不得包含任何带 `localhost`/`127.0.0.1` 的 origin，且必须提供。
- `METRICS_TOKEN` 必须存在且长度 ≥ 32。
- `OBJECT_STORE_BACKEND == "s3"` 且 `S3_BUCKET` 必须提供。
- `S3_DELETION_JOURNAL_BUCKET` 必须提供。
- 若启用 `MODEL_PROVIDER=openai`：必须提供 `OPENAI_API_KEY`、`MODEL_PRIVACY_URL`、长度 ≥ 20 的 `MODEL_DISCLOSURE_RETENTION`；输入/输出单价和单次调用预算必须为正数。

这些校验发生在实例化的 `__init__` → `model_validator` 阶段，即服务进程启动时失败，而非首次读取该字段时。

### 派生字段

- `cors_origin_list`：按逗号拆分、strip 后的 Python list，供 CORS 中间件直接使用。
- `openai_chat_completions_url`：基于 `openai_base_url.strip().rstrip("/") or "https://api.openai.com/v1"` 追加 `/chat/completions`；测试覆盖了默认值与带空格的 gateway URL。

## 4. 约定与约束

- **配置入口唯一**：所有配置统一经 `personal_ai_life_os.config.Settings`，没有散落的环境变量 `os.getenv` 调用。
- **`.env` 仅用于开发**：`env_file=".env"` 是默认生效路径，但测试用例显式传 `_env_file=None` 以避免污染；生产通过容器环境变量注入。
- **关键字段采用 `Literal[...]` 联合类型**，使不可接受的运行模式在类型解析阶段就报错（如 `app_env` 只允许 `development|test|production|desktop`，`processing_mode` 只允许 `inline|worker`，`object_store_backend` 只允许 `local|s3`，`registration_mode` 只允许 `open|invitation|closed`）。
- **生产密钥强制外部注入**：`docker-compose.production.yml` 对 `ACCESS_TOKEN_SECRET`、`SIGNUP_INVITE_CODE`、`METRICS_TOKEN`、`S3_BUCKET`、`S3_DELETION_JOURNAL_BUCKET`、`DATABASE_URL`、`LIFEOS_DOMAIN` 使用 `${VAR:?Set VAR}` 语法，若未在宿主机设置则容器启动即失败。
- **字段取值范围受 `pydantic.Field` 与 `model_validator` 双重约束**：例如 `registration_rate_limit` 的 `ge=1, le=1000` 在 BaseSettings 层级校验，而业务语义规则（不允许 open self-registration）在后端层校验。
- **`MODEL_PROVIDERS` 为 JSON 字符串**：代码在 validator 中尝试 `json.loads(self.model_providers)`，若非 dict 会抛错，使用者必须以合法 JSON 字符串提供。
- **Desktop 独立通道**：当 `app_env == "desktop"` 时，`create_app` 不接受普通的 config 文件路径作为配置来源，而是要求传入 `desktop_secret`/`desktop_path_key`，并在 HTTP 层校验 `x-lifeos-desktop` header。