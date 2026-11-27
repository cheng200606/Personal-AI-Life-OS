## 1. 使用的框架

本项目没有引入任何第三方日志库（pyproject.toml 依赖中不存在 loguru、structlog、sentry-sdk 等），日志全部通过 Python 标准库 `logging` + `logging.handlers.RotatingFileHandler` 实现。

## 2. 关键文件

- `src/personal_ai_life_os/main.py` — FastAPI 应用根 logger，模块级 `logger = logging.getLogger("personal_ai_life_os")`；在 lifespan / middleware 中记录启动、中间件异常和未处理的请求错误。
- `src/personal_ai_life_os/desktop.py` — Tauri sidecar 进程的唯一日志入口：调用 `logging.basicConfig(..., handlers=[RotatingFileHandler(log_dir / "sidecar.log", maxBytes=1_000_000, backupCount=3)], level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)`，将 sidecar 输出按 1 MB 轮转、最多保留 3 份到 `<data>/logs/sidecar.log`；使用模块级 `logger = logging.getLogger(__name__)` 记录迁移失败和侧车启动错误。
- 其余服务层与路由层（services/*、api/routes/*）直接 import `logging` 并采用 `logger = logging.getLogger(__name__)`。

## 3. 架构与约定

- **命名空间**：根日志器名为 `"personal_ai_life_os"`，子模块均使用 `__name__`（如 `personal_ai_life_os.services.scheduling`）。日志输出中的 `name` 字段可用于区分来源子模块。
- **级别策略**：所有业务位置仅出现 `info` / `warning` / `error` / `exception` 四级，没有 debug 级别的使用。Sidecar 进程将基础级别固定为 `INFO`。
- **消息风格**：统一使用带参数占位符（如 `"... failed (%s).", type(error).__name__`），而不是 f-string，使底层格式化器能决定是否格式化敏感内容。未发现结构化/JSON 字段或上下文绑定逻辑。
- **Sink 与输出**：FastAPI 自身通过 Uvicorn 输出 HTTP 访问日志（Uvicorn 默认控制台输出）；Sidecar 额外将 stderr/stdout 旁路写入本地 RotatingFileHandler。Web 模式（`app_env != "desktop"`）不显式配置文件 sink，因此日志走 Uvicorn 的标准 stdout，交由容器或宿主机管道收集。
- **禁用路径**：`desktop.py` 中创建 Uvicorn Config 时显式设置 `access_log=False`、`log_config=None`，避免 Uvicorn 与自定义 file handler 重复输出，并由应用自己的 logger 捕获迁移、恢复等关键流程。

## 4. 观察到的约束（描述性）

- 所有日志调用都使用 `logger.<level>(fmt, *args)` 的参数形式；无 `print()` 替代方案被用于生产路径。
- 已捕获异常的日志统一以 `%s` 注入 `type(error).__name__` 而非原始 traceback，控制日志体积且避免泄露敏感堆栈。
- 只有桌面 Sidecar 进程具备持久化日志文件，且由 `RotatingFileHandler` 强制执行 1MB / 3 副本轮转。
- 当前代码库没有集中化的日志配置工具类或可插拔 sink；若新增持久化日志点，需参考 `desktop.py` 中 `basicConfig(RotatingFileHandler(...))` 的形式进行。
- Uvicorn AccessLog 默认处于启用状态，除非通过 `DesktopServer(uvicorn.Config(..., access_log=False))` 关闭（Sidecar 正是这样做的）；在生产 Dockerfile 中应检查是否也禁用了 Uvicorn 默认日志以避免重复。

## 5. 缺失或尚未体现的部分

- 无结构化日志字段（trace_id、request_id、tenant/owner_id 等 context fields），也没有像 structlog 那样的 JSON formatter。
- 没有远程上报（Sentry、Datadog、CloudWatch）集成。
- 没有在 API 层为请求/响应打关联 ID，日志难以跨中间件、worker 线程串联单条请求生命周期。
- 未在测试中使用 `caplog` 对日志断言——`tests/` 目录下的用例主要断言返回体、存储结果和业务状态，未见对 `logger.*` 调用的断言。