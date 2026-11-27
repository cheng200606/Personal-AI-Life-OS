## 总体方案

本项目在 Python FastAPI 后端中采用**「领域自定义异常 + HTTPException + 全局异常处理器」三层结构**：
- 服务层/解析器层抛出语义化的局部异常类（多数继承 `RuntimeError`，格式校验类继承 `ValueError`）。
- API 路由层捕获业务异常后统一转译为 `fastapi.HTTPException(status_code=..., detail={...})`，其 `detail` 字段必须携带 `{"code": ..., "message": ...}` 双键结构。
- `src/personal_ai_life_os/main.py` 集中注册三个全局 `exception_handler`，对所有入站请求进行异常收敛、状态码映射与错误体标准化。桌面 Rust/Tauri 端通过 panic/recover 暴露给 Python sidecar，但侧脚本 `desktop/smoke-sidecar.py` 仅做进程级存活判断，未定义 Rust 侧的领域错误类型；本卡片聚焦 Python/FastAPI 部分。

## 关键文件

- `src/personal_ai_life_os/main.py` — `create_app` 内挂载全局异常处理器与 HTTP 中间件，统一输出 `{"error":{"code","message"}}`。
- `src/personal_ai_life_os/api/deps.py` — 认证依赖 `_authenticated_user` 直接 raise 401/410 的 `HTTPException`。
- 各 `services/*.py` 中的领域异常局部 class 定义。
- 各 `api/routes/*.py` 中调用 service 后对领域异常的 `try/except` → `HTTPException` 适配代码。

## 架构与约定

### 1. 领域自定义异常（按子模块划分）

每个子系统在各自模块顶部以局部 class 声明领域异常，避免引入独立 error package：

| 模块 | 异常类 | 基类 | 用途 |
|---|---|---|---|
| `services/agent_actions.py` | `AgentActionError` | `RuntimeError` | Agent 动作执行失败 |
| `services/graph_extraction.py` | `GraphExtractionError` | `RuntimeError` | 知识图谱抽取失败 |
| `services/graph_merges.py` | `GraphMergeError` | `RuntimeError` | 图谱合并冲突 |
| `services/graph_qa.py` | `QaError` | `RuntimeError` | 图谱问答失败 |
| `services/graph_review.py` | `GraphReviewError` | `RuntimeError` | 图谱审阅失败 |
| `services/model_providers.py` | `ModelProviderError` | `RuntimeError` | 外部模型调用失败 |
| `services/insights.py` | `InsightError` | `RuntimeError` | 洞察生成失败 |
| `services/plugins.py` | `PluginError` | `RuntimeError` | 插件加载/调用失败 |
| `services/ontology.py` | `OntologyError` | `RuntimeError` | 本体操作失败 |
| `services/jobs.py` | `RetryableJobError` | `Exception` | 后台任务可重试失败 |
| `parsers/chatgpt_export.py` | `UnsupportedExportError` | `ValueError` | 不支持的聊天导出格式 |
| `parsers/generic_chat.py` | `UnsupportedChatExportError` | `ValueError` | 通用入口不支持 |
| `parsers/document.py` | `UnsupportedDocumentError` | `ValueError` | 文档解析不支持 |
| `parsers/calendar_ics.py` | `UnsupportedCalendarError` | `ValueError` | ICS 日历不支持 |
| `parsers/photo.py` | `UnsupportedPhotoError` | `ValueError` | 照片/OCR 不支持 |
| `parsers/streaming_chat.py` | `ChatExportError` | `ValueError` | 流式聊天导出错误 |

**约定**：业务异常在路由层被 `try/except` 捕获后提升为 `HTTPException(detail={...})`，并保留 `from original_exception` 链路；若不应泄露内部细节则使用 `from None`（参见 `api/routes/desktop_analysis.py` 与 `desktop_chats.py`）。

### 2. HTTP 错误响应规范

所有路由抛出的 `HTTPException.detail` **必须是字典且包含 `code` 与 `message` 两个键**。`main.py` 的全局 `http_error_handler` 会检查该结构：如果外层不是 dict 或缺少 `code`，就回退为 `"request_failed"`。实际对外一致返回：

```json
{"error": {"code": "auth_required", "message": "Sign in to access this resource."}}
```

已使用的错误 code 包括：`auth_required`、`invalid_access_token`、`account_deletion_pending`、`database_unavailable`、`rate_limited`、`validation_error`、`internal_error`、`imports_paused`、`desktop_auth_required`、`not_found`、`request_failed` 等。

### 3. 全局异常处理器链（位于 `main.py`）

按优先级注册顺序为：

1. `HTTPException` → 原样透传状态码，将 `detail` 包装成 `{"error": <detail>}`，透传额外 header。
2. `RequestValidationError`（Pydantic/FastAPI）→ 统一 `422`，展开为 `{"error":{"code":"validation_error","message":"Request validation failed.","issues":[...]}}`，每个 issue 含 `location`、`code`、`message`。
3. 兜底 `Exception` → 写日志 `logger.error("Unhandled request failure: %s")`，返回 `500` + `{"error":{"code":"internal_error","message":"The request could not be completed."}}`。

该三叉分支意味着：**业务逻辑层不得直接吞掉未处理异常**，否则客户端只得到统一的 `internal_error`，配合 metrics 中间件记录的 request_samples 可用于监控。

### 4. HTTP 中间件与速率限制

`main.py` 注册的 `observe_and_limit` 中间件在路由之前完成：

- Tauri 模式下校验 `x-lifeos-desktop` 头，失败返回 `401` + `desktop_auth_required`。
- 基于内存 deque 的路径级速率限制：登录 `/api/v1/auth/login`（10/300s）、注册按配置、导入 `/api/v1/sources/*/imports`（30/60s），超限时返回 `429` + `rate_limited` 及 `Retry-After` 头。
- imports_enabled 为假时，导入接口返回 `503` + `imports_paused`。
- 每次请求记录到 `application.state.request_samples`（最后 1000 条 `(time, latency_ms, status_code)`），供 `/api/v1/metrics` 消费。
- 中间件捕获 call_next 抛出的异常，记录一次 `500` 采样后再重新抛出，交由下游异常处理器继续处理。
- 所有 response 强制追加安全头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`。

### 5. 认证依赖的错误表达

`api/deps.py` 的三个断言集中在 `_authenticated_user`：

- 缺少 Bearer token → `401` + `auth_required` + `WWW-Authenticate: Bearer`。
- Token 解析后用户不存在 → `401` + `invalid_access_token`。
- 账户删除待清理期间访问 → `410` + `account_deletion_pending`（允许显式传入 `allow_deleting=True` 豁免注销接口）。

## 约定与约束

- **HTTP 错误 detail 必须是 `dict` 且含 `code`+`message`** —— 由 `main.py` 中 `http_error_handler` 的运行时结构校验强加；非 dict/detail 缺 `code` 会被改写为 `"request_failed"`。
- **所有未捕获异常最终归一为 `500 internal_error`** —— 由兜底 `exception_handler(Exception)` 保证，开发者不应依赖特定内部异常类型名透传到客户端。
- **领域异常不得跨越 API 边界** —— 仅在 service/parsers 之间传播，必须在路由层转换为 `HTTPException`，否则会被兜底处理器掩盖真实原因。
- **验证错误使用 Pydantic + RequestValidationError 路径** —— 路由参数/请求体验证失败统一走 422 path；需要 `422` 的业务参数才用 `HTTPException`（如时区非法、空选择等）。
- **数据库就绪检查通过 `GET /api/v1/health` 返回 503**（`api/routes/health.py`），而非抛出 500，使 K8s readiness probe 能区分不可用与崩溃。
- **Rust/Tauri 端无 Python 风格的领域错误枚举**；桌面相关错误通过 Windows 错误码、Python 子进程的 stdout/stderr 协议传递（见 `desktop/src-tauri/src/main.rs` 与 `smoke-sidecar.py`），不在本错误体系中建模。