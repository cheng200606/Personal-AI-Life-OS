# Tasks

- [x] Task 1: 实现统一检索接口与后端回归
  - [x] SubTask 1.1: 在 `api/schemas.py` 增加检索响应模型（时间线、复盘、提醒三组，含 `total`、片段、时间与状态字段）
  - [x] SubTask 1.2: 新增 `api/routes/search.py`，实现 `GET /api/v1/search`：所有者校验、`q` 1–200 字符、忽略大小写子串匹配、标题优先排序、稳定 ID 兜底、每组默认 10/最多 20、每组总数与 ≤200 字符片段
  - [x] SubTask 1.3: 复用时间线可见性规则（排除已删除、非当前、来源 `deleting`），排除 `invalidated` 复盘；提醒按可读状态返回；在 `main.py` 注册路由
  - [x] SubTask 1.4: 新增 `tests/test_search.py`，覆盖跨组命中、所有者隔离、删除/失效排除、空值与超长校验、标题优先、片段边界、组内上限与总数
  - [x] 验证：`uv run pytest -q tests/test_search.py` 与 `uv run ruff check .` 通过

- [x] Task 2: 增加 Web「Search」页面与结果跳转
  - [x] SubTask 2.1: 在侧边栏加入 Search 导航与页面，提供带标签的搜索框、Enter/按钮提交、加载态、空态、无结果与错误提示，失败时保留查询词
  - [x] SubTask 2.2: 分组展示时间线、复盘、提醒结果，显示片段、日期/状态与每组总数
  - [x] SubTask 2.3: 时间线结果切换到 Timeline、按来源筛选并滚动到条目；复盘结果切换到 Weekly review 并定位复盘卡；提醒结果进入 Weekly review 并显示对应提醒
  - [x] 验证：`npm run lint` 与 `npm run build` 在 `web/` 通过

- [x] Task 3: 增加合成双语检索评测
  - [x] SubTask 3.1: 新增 `scripts/evaluate_search.py`，生成至少 20 条中英文注入查询与预期记录，构造 1 万条时间线及复盘/提醒数据，支持 SQLite 与 `LIFEOS_BENCHMARK_POSTGRES_URL`
  - [x] SubTask 3.2: 输出前 5 条命中率、查询 P95、数据规模、运行环境与是否达标；超过 500 毫秒时仅记录结果，不引入全文索引
  - [x] 验证：本地 SQLite 与 PostgreSQL（如可用）各运行一次并保存输出

- [x] Task 4: 浏览器验收、文档与全量检查
  - [x] SubTask 4.1: 扩展 `web/e2e/workflow.spec.ts`，覆盖键盘进入搜索、三类结果展示、时间线跳转与无结果/错误态
  - [x] SubTask 4.2: 更新 `docs/operations/support-matrix.md`、`docs/architecture/overview.md`、`docs/roadmap/milestones.md`、`docs/roadmap/next-iteration.md`、`README.md`，说明统一检索范围、限制与评测结果
  - [x] SubTask 4.3: 运行 `uv run ruff check .`、`uv run pytest -q`、`uv run python scripts/evaluate_reviews.py`、`npm run lint`、`npm run build`、`npm run test:e2e` 与检索评测，记录实际结果
  - [x] 验证：全部命令通过；检索 P95 ≤500 毫秒或已记录未达标原因；文档链接与 `git diff --check` 通过

# Task Dependencies

- Task 2 依赖 Task 1（接口与响应模型）
- Task 3 依赖 Task 1（接口行为）
- Task 4 依赖 Task 2 与 Task 3
