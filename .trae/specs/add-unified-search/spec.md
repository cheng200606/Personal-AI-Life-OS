# 统一检索能力 Spec

## Why

项目已完成单人本地 MVP 的导入、照片 OCR、周复盘、提醒、导出与删除链路，但检索仍只覆盖时间线条目，且仅有有界 `LIKE` 匹配。已确认的周复盘和提醒无法被找回，随着本人持续导入资料，定位过去的决定或承诺只能手动翻页。文档已把「跨原始和派生笔记的增强检索」列为 PRD P1 候选，本轮交付其中最小、可验证的一步：统一检索与结果分组。

选择该范围而不是其他 P1 项的理由：定时复盘需要至少两名用户连续两周的送达证据，当前单人范围不具备；新连接器需要明确的同类资料来源证据；可配置多提供方已由 `OPENAI_BASE_URL`/模型配置覆盖；增强检索的缺口在 README、架构概览与支持矩阵中均有明确记录，且不需要新增数据库迁移或外部依赖。

## What Changes

- 新增 `GET /api/v1/search`：按所有者校验，返回时间线、周复盘、提醒三组命中结果。
- 统一查询规则：忽略大小写子串匹配，查询词去空白后 1–200 字符；每组默认 10 条、最多 20 条；返回每组总数。
- 可见性沿用时间线规则：排除已删除、非当前版本、来源处于 `deleting` 的记录；复盘排除 `invalidated`；提醒按现有可读状态返回。
- 确定性排序：标题命中先于正文命中；时间线按发生时间倒序、无日期在后；复盘按周期结束倒序；提醒按到期时间升序、无到期在后；ID 作为最终稳定排序。
- Web 新增「Search」页面：分组展示结果、片段、日期/状态，支持跳转到时间线条目、复盘卡和提醒；覆盖键盘焦点、加载、空态、无结果与失败提示。
- 新增合成双语检索评测：至少 20 条中英文查询，测量前 5 条命中率与 1 万条时间线加复盘/提醒的查询 P95，目标 ≤500 毫秒；不达标时本轮不引入全文索引，只记录为下一轮输入。
- 更新支持矩阵、架构概览、里程碑与迭代记录。
- 不新增数据库迁移、第三方依赖、外部模型调用，也不记录查询词或结果正文到日志/指标。
- **BREAKING**：无。

## Impact

- Affected specs: 检索与发现、周复盘读取、提醒读取、Web 导航。
- Affected code: `src/personal_ai_life_os/api/routes/search.py`（新增）、`src/personal_ai_life_os/api/routes/__init__.py`、`src/personal_ai_life_os/main.py`、`src/personal_ai_life_os/api/schemas.py`、`web/src/App.tsx`、`web/e2e/workflow.spec.ts`、`tests/test_search.py`（新增）、`scripts/evaluate_search.py`（新增）、`docs/operations/support-matrix.md`、`docs/architecture/overview.md`、`docs/roadmap/milestones.md`、`docs/roadmap/next-iteration.md`、`README.md`。

## ADDED Requirements

### Requirement: 统一检索接口

系统 SHALL 提供受鉴权的统一检索接口，按时间线条目、周复盘和提醒分组返回命中结果，且所有结果仅来自当前登录用户。

#### Scenario: 跨三类资料命中
- **WHEN** 已登录用户提交查询词 `synthetic`
- **THEN** 响应包含 `timeline`、`reviews`、`reminders` 三组；每组包含 `total` 与命中数组；仅包含该用户可读的记录。

#### Scenario: 所有者隔离
- **WHEN** 用户 A 查询用户 B 导入的内容
- **THEN** 响应中不出现用户 B 的任何记录，且不泄露其数量或标题。

#### Scenario: 已删除与已失效数据
- **WHEN** 某时间线条目的来源已删除、条目非当前版本，或某复盘已标记 `invalidated`
- **THEN** 该记录不出现在检索结果中。

#### Scenario: 查询校验与上限
- **WHEN** 查询词为空、全为空白或超过 200 字符
- **THEN** 接口返回 422；查询有效时每组最多返回 20 条，默认 10 条。

### Requirement: 确定性排序与结果片段

系统 SHALL 以可复现的规则排序结果，并为每条结果生成不超过 200 字符的片段。

#### Scenario: 标题优先
- **WHEN** 同一组内一条记录的标题命中查询词，另一条仅正文命中
- **THEN** 标题命中的记录排在前面；其余按各组既定时间规则倒序/升序排列，ID 作为最终稳定排序。

#### Scenario: 片段边界
- **WHEN** 命中位置位于长正文中
- **THEN** 片段围绕首次命中截取并限制在 200 字符内，响应不返回完整正文。

### Requirement: Web 统一检索入口

Web 客户端 SHALL 提供「Search」导航与页面，展示三组结果并支持跳转到对应记录。

#### Scenario: 时间线条目跳转
- **WHEN** 用户点击时间线组中的结果
- **THEN** 客户端切换到 Timeline 页，按该结果的来源筛选并滚动到对应条目。

#### Scenario: 复盘与提醒跳转
- **WHEN** 用户点击复盘组结果
- **THEN** 客户端切换到 Weekly review 页并定位到对应复盘卡；点击提醒结果时进入 Weekly review 页并显示该提醒。

#### Scenario: 键盘与失败状态
- **WHEN** 用户仅使用键盘操作，或接口返回错误
- **THEN** 搜索输入、提交和结果链接均可聚焦并触发；错误以可读提示展示，不丢失已输入的查询词。

### Requirement: 检索评测与性能边界

系统 SHALL 提供可重复的合成评测，记录命中率与查询延迟。

#### Scenario: 双语合成评测
- **WHEN** 运行评测脚本
- **THEN** 脚本执行至少 20 条中英文注入查询，输出前 5 条命中率、P95 延迟、数据规模与运行环境；1 万条时间线加复盘/提醒的 P95 目标为 ≤500 毫秒。

#### Scenario: 未达标处理
- **WHEN** P95 超过 500 毫秒
- **THEN** 本轮不引入全文或向量索引，记录测量结果与下一轮索引方案；验收以已交付的统一检索和可复现数据为准。

## MODIFIED Requirements

无。

## REMOVED Requirements

无。
