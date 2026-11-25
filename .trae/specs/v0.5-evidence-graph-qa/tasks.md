# Tasks

> v0.5 包含全部能力，但必须按阶段交付。每个阶段独立验收，不建议一次性合并所有改动。

- [x] Task 1: 图谱数据模型与迁移
  - [x] SubTask 1.1: 新增 `GraphEntity`、`GraphRelation`、`GraphEvidence`、`EntityAlias`、`EntityMergeLog`、`OntologyType` 模型；所有记录带 `owner_id`，证据带来源、片段、定位符、可用状态与置信度
  - [x] SubTask 1.2: 新增 Alembic 迁移；建立所有者、类型、状态、时间、来源、实体/关系外键与必要索引
  - [x] SubTask 1.3: 新增 `tests/test_graph_model.py`，覆盖所有者隔离、证据链接、合并日志、失效状态与迁移
  - [x] 验证：`uv run alembic upgrade head`、`uv run alembic check`、`uv run pytest -q tests/test_graph_model.py` 通过

- [x] Task 2: 输入格式与来源级授权
  - [x] SubTask 2.1: 增加 Claude、Gemini 导出解析器；为 ZCode、DeepSeek harness、WorkBuddy 提供通用 JSON/JSONL 与 Markdown/文本解析，保留标题、正文、时间（若有）与来源定位
  - [x] SubTask 2.2: 增加 TXT 与文本型 PDF/DOCX 本地提取，保留页码/段落定位；扫描件返回“暂不支持”的明确提示
  - [x] SubTask 2.3: 增加来源级云端授权与撤回：未授权来源阻止抽取；撤回后标记证据不可用且不进入问答；删除来源按现有删除语义清理
  - [x] SubTask 2.4: 增加解析器/重复导入/授权阻断/撤回/删除关联测试
  - [x] 验证：Ruff、`uv run pytest -q`、Web 导入与授权界面手动验收通过

- [x] Task 3: 抽取流水线与预算
  - [x] SubTask 3.1: 新增手动选择条目的抽取 API 与 `ExtractionRun`：范围、模型、提供方、状态、计数、token、成本、耗时、错误码
  - [x] SubTask 3.2: 定义实体/关系/证据/置信度 JSON Schema；提示词要求只输出可引用证据；模型提议的新类型进入待审
  - [x] SubTask 3.3: 实现高置信度入库、低置信度待审、失败重试、幂等/重复抽取不重复计费、批量与缓存
  - [x] SubTask 3.4: 增加月度预算、80% 提醒、单次上限与多提供方路由；记录每次调用成本
  - [x] SubTask 3.5: 用假模型测试成功、失败、低置信度、重复抽取、预算提醒、未授权来源与超预算行为
  - [x] 验证：抽取测试通过；运行记录可查；未授权来源无云端调用

- [x] Task 4: 待审、实体合并与本体治理
  - [x] SubTask 4.1: 新增 `GraphReviewItem` API/UI：批准、拒绝、编辑、批量处理；导入完成后内联显示待审入口
  - [x] SubTask 4.2: 高置信度实体自动合并，保留别名与合并日志；支持撤销并恢复证据/关系
  - [x] SubTask 4.3: 自定义本体提议/批准/拒绝；记录来源、版本与创建者；批准后进入筛选与抽取提示
  - [x] SubTask 4.4: 测试合并、撤销、低置信度队列、自定义类型与错误合并恢复
  - [x] 验证：图谱/待审 API 测试与 Web 内联待审流程通过

- [x] Task 5: 证据图谱个人问答
  - [x] SubTask 5.1: 实现图谱 + 证据 + 时间线 + 复盘的检索服务；支持来源/项目/主题/时间范围，并记住上次范围
  - [x] SubTask 5.2: 定义答案 schema：结构化事实、引用、置信度、事实/推断/不确定标记、缺失信息、行动建议
  - [x] SubTask 5.3: 新增中文优先的 Ask 页面：Chat + 结构化卡片、追问、引用跳转、历史保存/导出/删除、范围切换
  - [x] SubTask 5.4: 排除撤回来源、删除条目与失效证据；无证据时明确拒绝编造；首屏目标 <30 秒
  - [x] SubTask 5.5: 测试四类问题、无证据、撤回来源、范围记忆、引用跳转与历史删除
  - [x] 验证：问答 API/页面测试通过；引用可回到原文

- [x] Task 6: 规则洞察
  - [x] SubTask 6.1: 实现目标延期/风险、承诺到期/未跟进、项目停滞、技能证据不足四条规则，输出触发条件、证据、置信度与建议
  - [x] SubTask 6.2: 新增规则 API 与图谱/问答页面洞察区；支持忽略误报与阈值配置
  - [x] SubTask 6.3: 为四条规则分别编写测试，覆盖触发、不触发、证据缺失与忽略
  - [x] 验证：规则测试通过；误报可忽略且不重复提示

- [x] Task 7: Agent 行动、审计与红线
  - [x] SubTask 7.1: 新增 `AgentAction`：类型、目标、前后值、证据、状态、审批、24 小时撤销、审计
  - [x] SubTask 7.2: 支持自动创建复盘草稿/提醒、任务/项目、目标进度/成长记录；Web 通知与一键撤销
  - [x] SubTask 7.3: 在工具层强制四条红线：对外发送/提交、改原始文件、花钱/不可逆交易、删除数据/改目标
  - [x] SubTask 7.4: 测试自动写入、24 小时撤销、越权拒绝、审计与预算不足
  - [x] 验证：高风险动作无法绕过审批；撤销恢复前后值

- [x] Task 8: 连接器与 Agent 插件 SDK
  - [x] SubTask 8.1: 定义连接器接口：预览、导入、删除、来源定位、权限声明；默认只读用户选择路径
  - [x] SubTask 8.2: 定义 Agent 工具接口：名称、参数 schema、权限、是否需要批准、审计字段
  - [x] SubTask 8.3: 插件清单安装/启用/停用/卸载 UI；未声明权限默认拒绝；插件失败隔离
  - [x] SubTask 8.4: 提供通用 JSON/Markdown 参考连接器与图谱检索参考 Agent 工具
  - [x] SubTask 8.5: 测试权限拒绝、参考插件、故障隔离与审计
  - [x] 验证：参考连接器可导入；参考 Agent 工具可被批准调用；越权被拒绝

- [x] Task 9: 中文优先界面与信息架构
  - [x] SubTask 9.1: 建立中文优先的导航：时间线、图谱、提问、复盘、项目与目标、待审、设置
  - [x] SubTask 9.2: 图谱页展示实体/关系/证据/置信度/状态；项目与目标页展示进度、任务、规则洞察
  - [x] SubTask 9.3: Ask 页、待审入口、来源授权、预算、模型提供方、本体自定义与插件设置
  - [x] SubTask 9.4: 键盘可访问、空态/失败态、窄屏布局与中文文案检查
  - [x] 验证：`npm run lint`、`npm run build` 与 Playwright 中文主流程通过

- [x] Task 10: 评测、预算与文档
  - [x] SubTask 10.1: 新增 30 条合成问答评测集与 `scripts/evaluate_graph_qa.py`，输出引用正确率、无据断言、P95 延迟与待审数量
  - [x] SubTask 10.2: 增加预算/用量页面或接口，验证 80% 提醒、超预算行为与缓存命中
  - [x] SubTask 10.3: 更新产品文档、架构、隐私、支持矩阵、README、路线图与迁移/回滚说明
  - [x] SubTask 10.4: 运行全量检查：Ruff、pytest、Alembic upgrade/check、Web lint/build、Playwright、评测脚本与 `git diff --check`
  - [x] 验证：引用正确率 ≥90%；无据断言 0；首屏 <30 秒；低置信度待审 ≤10 条/周；预算与红线测试通过

# Task Dependencies

- Task 2 依赖 Task 1
- Task 3 依赖 Task 1、Task 2
- Task 4 依赖 Task 1、Task 3
- Task 5 依赖 Task 1、Task 3、Task 4
- Task 6 依赖 Task 1、Task 3、Task 4
- Task 7 依赖 Task 1、Task 5
- Task 8 依赖 Task 1、Task 2、Task 7
- Task 9 依赖 Task 4、Task 5、Task 7、Task 8 的 API 契约
- Task 10 依赖 Task 5、Task 6、Task 7、Task 8
