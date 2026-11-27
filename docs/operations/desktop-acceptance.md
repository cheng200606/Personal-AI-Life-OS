# Windows 桌面本地验收

适用于单人本机候选版。版本证据应记录安装包 SHA-256、Windows 版本与构建号、WebView2 版本、测试日期、各项结果与残留问题。

## 本机构建

在 Windows x64 安装 Node 24、Rust MSVC 工具链、VS C++ 构建工具、7-Zip 与 uv。构建使用 Python 3.12，安装后的应用不依赖系统 Python、Node、Docker 或 CLI。

```powershell
npm.cmd --prefix web ci
uv sync --locked --group desktop
uv run --frozen --group desktop pytest -q
./desktop/build-installer.ps1 -SevenZip "C:/Program Files/7-Zip/7z.exe"
uv run --frozen --group desktop python desktop/smoke-sidecar.py --full
./desktop/smoke-installer.ps1
Get-FileHash desktop/src-tauri/target/release/bundle/nsis/*.exe
```

完整 sidecar 冒烟验证启动认证、重启保留、退出、OCR、Windows 凭据管理器以及大聊天文件的实际选择与入库。工具链固定依赖见 `uv.lock`、`web/package-lock.json`、`desktop/src-tauri/Cargo.lock` 和 Windows CI。

## 系统验收

| 验收项 | 操作与通过条件 |
| --- | --- |
| 干净 Windows 10 x64 | 当前用户安装，无 Python、Node、Docker 或 CLI。确认 WebView2 缺失时的安装行为，再重启、验证首次使用与卸载后资料保留。 |
| 干净 Windows 11 x64 | 执行同样流程。在 100% 和 150% DPI 检查键盘、原生对话框与 Windows 通知。 |
| 升级 | 从上一候选版本升级。核对个人资料、来源白名单、模型凭据和检索。构造迁移失败后确认旧资料可恢复。 |
| 进程 | 关闭主窗口，在授权目录修改合成文件，确认继续同步。再次打开和启动第二实例时聚焦原窗口。启用、禁用 Windows 登录启动并实际重登。托盘退出后确认 sidecar 未残留。 |
| 选源与审核 | 验证 Markdown、Vault 与 500 MiB 聊天导出。单独授权提供方与来源，按来源编辑、确认、拒绝和批量预览草稿。更新导出时新增未选会话继续排除。 |
| 断网与预算 | 撤回同意、置零预算、模拟外部连接失败。核对调用次数、成本账目、本地可检索与任务重试。 |
| 删除与恢复 | 先备份、再移除源文件并确认删除，随后恢复旧备份。已删除正文和对象不得重新出现。OpenAI 兼容密钥应在 Windows 凭据管理器保存，并排除于 ZIP。 |
| Vault | 导入只读，隐藏目录、重解析点和 `LifeOS-Exports` 被排除。三种显式导出冲突策略保留预期文件。 |

签名、SmartScreen 和签名自动更新属于公开分发门禁。

## 本机候选验收记录

2026-11-26 在 Windows 11 x64 构建 26300、WebView2 158.0.4370.33 上验证。开发工具链为 Rust 1.100.0、Node 24.16.0、Python 3.12.14、PyInstaller 6.22.3、SQLite 3.53.1。

- 0.1.0 x64 NSIS，本机验证用未签名候选版。安装包 94,289,668 字节，SHA-256 为 `6888E94561CAD2AB5CDC9CF90B727BEF4023263D688A58E2A31B1FAB7E2A121C`。
- 静默安装、从安装目录启动 sidecar 和卸载通过。已安装 sidecar 完成 570,621,506 字节合成聊天预览和白名单入库。预览用时 1.56 秒，峰值工作集 197.9 MiB。OCR、Windows 凭据管理器及重启保留通过。
- WebView2 验证本机资料、快速记录、Ctrl+K 聚焦搜索、找到新记录。关闭测试外壳的进程后，sidecar 响应管道关闭并正常退出。
- Python 130 项、Edge 18 项、React 构建、Ruff 与 Cargo 检查通过。Windows 集成用例包含旧备份恢复时重放确认删除。
- 2026-11-26 干净 Windows 10/11 的安装、升级及系统交互矩阵仍待完成；当时当前 Codex 进程令牌未包含 Hyper-V Administrators，Hyper-V 管理查询被拒绝。用户随后配置了 Hyper-V；最新状态见下方 2026-11-27 记录。
- 迁移回归从旧版数据库开始，注入部分写入失败，确认恢复了旧数据及迁移版本。重试后升级到最新版本，业务数据仍保留。

## D5 干净系统验收进度（2026-11-27）

- 用户已配置本机 Hyper-V。`LifeOS-D5-Win10` 和 `LifeOS-D5-Win11` 是本次专用的第 2 代 x64 虚拟机；两块动态 VHDX 均位于 `D:\ProfessionalSoftware\Project\Personal-AI-Life-OS\desktop\build\hyperv`。虚拟机已配置 Secure Boot、动态内存和 Guest Service Interface；Win11 已配置 vTPM。安装镜像与无人值守应答介质也保存在同一 D 盘目录。
- 为覆盖实际版本升级，另行构建 0.1.1 x64 NSIS 候选版：94,296,265 字节，SHA-256 `E6B80C83DD901164D77FFB6F5918C15F1D3164C5CB727FA0E70019CC05438D29`。该构建通过 Tauri 配置覆盖版本号，仓库产品版本当时仍为 0.1.0（R1 已把仓库版本统一为 0.1.1，见发布记录）；上一候选 0.1.0 安装包保留在 `desktop/dist/verified-0.1.0/`，SHA-256 `6888E94561CAD2AB5CDC9CF90B727BEF4023263D688A58E2A31B1FAB7E2A121C`。
- 修正了 `test_four_question_types_return_facts_and_citations` 对固定 2026-11-20 笔记使用真实当前时钟造成的日期漂移，为该测试固定参考时钟。完整 Python 套件 131 项通过；该测试文件 Ruff 检查通过。
- **Windows 10：**Windows 10 Enterprise LTSC Evaluation x64，Build 19044。以当前用户安装 0.1.0，升级到 0.1.1 后再次启动，检索到升级前快速记录；静默升级退出码为 0。静默卸载退出码为 0，应用目录与两个应用进程均消失；`%LOCALAPPDATA%\PersonalAILifeOS\data\lifeos.db` 保留，SQLite integrity check 为 `ok`，数据库中仍有 `D5 Win10 pre-upgrade marker`。卸载后检查未发现 Python、Node、npm、Docker、`lifeos` 或 sidecar 命令；当时 WebView2 Runtime 为 158.0.4370.33。
- **Windows 11 首次启动与离线：**Windows 11 Enterprise LTSC Evaluation x64，Build 26100。干净首次启动时系统没有 WebView2 Runtime；应用启动后安装 Evergreen Runtime，版本 158.0.4370.45。创建本机资料、保存快速记录并用 Ctrl+K 搜索通过。断开 VM 网卡后，仍可创建并检索离线快速记录；恢复网络后首次显示请求超时，手动点击“重试”恢复工作区与本地记录。
- **500 MB 聊天导入：**在 Win11 使用 570,621,506 字节合成 JSON，预览 510 个会话；只勾选 Chat 42 并完成导入。搜索 `SELECTED-SYNTHETIC-EVIDENCE` 返回唯一的 Chat 42，搜索未选会话的 filler 文本无结果，验证只导入白名单内容。
- **Win11 记录版本升级：**先记录已安装 0.1.1，再静默卸载并确认用户数据库保留；安装 SHA-256 为 `6888E94561CAD2AB5CDC9CF90B727BEF4023263D688A58E2A31B1FAB7E2A121C` 的已验证 0.1.0 包，注册版本显示 0.1.0。在 0.1.0 中通过快速记录创建 `D5 Win11 pre-upgrade 0.1.0 20261127`，再用 SHA-256 为 `E6B80C83DD901164D77FFB6F5918C15F1D3164C5CB727FA0E70019CC05438D29` 的 0.1.1 安装包升级；退出码 0，注册版本为 0.1.1，启动后该笔记、Chat 42 和离线笔记均仍显示在时间线。安装结果 JSON 和升级后截图保存在忽略目录 `desktop/build/hyperv/win11-upgrade-result.json`、`desktop/build/hyperv/win11-upgrade-after.png`。
- **Win11 登录启动、单实例与托盘退出：**通过应用命令开启登录启动后，Run 注册值为当前用户安装路径加 `--background`；重启后主进程和 sidecar 在用户 Session 1 自动启动。再次通过应用命令关闭登录启动，Run 注册值移除；再重启后两个进程均不存在。测试任务启动第二实例后，原窗口变为 visible 且获得 focus，进程仍只有一个主程序和一个 sidecar。发送 Alt+F4 后主窗口隐藏，两个进程仍存活；从 Windows 隐藏图标区打开 LifeOS 菜单并选择“退出”后，主程序和 sidecar 均在 5 秒内结束。
- **Win11 授权目录同步：**通过应用内原生目录选择器授权 `C:\Users\lifeos-test\Documents\LifeOS-D5-AutoSync-20261127`。合成 Markdown 基线可搜索；`.hidden-test` 和 `LifeOS-Exports` 中的排除标记搜索无结果。Alt+F4 隐藏主窗口后修改 `background-sync.md`，8 秒后搜索到新标记，确认 sidecar 在托盘状态持续同步。暂停后修改产生的标记 8 秒后无结果；恢复后再修改的标记 8 秒后可搜索；撤回后再修改的标记 8 秒后无结果。应用和 sidecar 进程在隐藏及这些同步检查期间保持运行。Obsidian Vault 的独立只读导入、排除与导出冲突策略见下方验收记录。
- **Win11 到期提醒通知：**在复盘页启用“Windows 通知”，为专用合成提醒设置已到期时间并重新载入页面触发到期检查。Windows 11 原生通知中心显示“有 1 条提醒已到期”，完整桌面截图保存在忽略目录 `desktop/build/hyperv/win11-notification-e2e.png`；另以 Tauri 通知命令完成原生通知通道冒烟检查。验收后将合成提醒标记完成，并关闭 Windows 通知偏好，避免后续测试被测试数据打扰。
- **Win11 提供方同意、预算与失败账目：**设置页配置绑定 VM 回环地址 `127.0.0.1` 的合成 OpenAI 兼容服务，没有外部模型或 API 密钥。来源已授权但提供方未同意时，分析任务以 `model_consent_required` 结束，服务请求数为 0；同意提供方但月预算为 `$0` 时，以 `model_budget_exceeded` 结束，请求数仍为 0。将预算改为 `$5` 后，合成服务返回 503；任务按 3 次重试后以 `model_request_failed` 终止，预算页记 3 次调用、估算费用 `$0.006162`，无 token 计数。服务日志仅记路径、请求体字节数和预设响应模式，不保存请求正文。通过设置页撤回提供方同意后再次导入授权来源，任务再次以 `model_consent_required` 结束，回环服务请求数没有增加。
- **Win11 来源分析草稿审核：**回环服务返回 3 条有原文引用、置信度在 86–91% 的合成草稿。通过“待审”界面编辑一条并保存后确认其文本保留；单条确认与拒绝均从待审队列移除。另对同一来源的 3 条草稿打开“预览批量接受”，检查三条预览后一次接受；API 确认两条知识/经历写入本地确认记录，两条行动建议生成待办提醒，测试草稿队列清空。
- **Win11 150% DPI 与原生文件选择器：**设置 `LogPixels=144` 后重启，WebView2 报告 `devicePixelRatio=1.5`、CSS 视口宽 686 px、文档 `scrollWidth=671`，没有横向溢出；Ctrl+K 从捕获页进入搜索页并聚焦搜索框。升级/重启后本地笔记和 Chat 42 仍可检索。通过 WebView2 输入事件实际打开原生“打开”对话框，完整 1600×900 客户机截图中地址栏、导航栏、文件名输入、文件类型、打开和取消控件均可见；按 Esc 后对话框关闭。截图保存在忽略目录 `desktop/build/hyperv/win11-150dpi-search.png` 和 `desktop/build/hyperv/win11-picker-150dpi-final.png`。
- **Win11 删除确认与备份恢复：**删除合成来源文件后，在应用内确认移除；随后恢复较早的备份。恢复后删除日志仍在，源内容未重新进入检索，合成唯一标记搜索结果为 0，验证恢复时重放删除记录。
- **Win11 Obsidian Vault 导入与排除：**只读导入合成 Vault，`Visible.md` 的标记可检索；Vault 根目录隐藏 Markdown、隐藏目录、`.obsidian`、`LifeOS-Exports` 以及指向 Vault 外部的 junction 中的标记均无检索结果。
- **Win11 Vault 导出冲突策略：**对 `Visible-c0918985.md` 预置用户编辑标记。Keep 保留原文件并显示“未覆盖你的修改”；Copy 生成 `Visible-c0918985-1.md`，新文件含 LifeOS 导出内容而原文件仍含用户标记；Overwrite 将原文件替换为 LifeOS 导出内容，保留 Copy 产生的副本。三种策略均通过已安装候选版界面操作。
- **Win11 与 Win10 候选 sidecar 迁移失败恢复和重试：**在两个系统的隔离数据目录运行 0.1.1 候选 sidecar 与同一份合成旧版数据库；Win11 使用安装目录 sidecar，Win10 使用与候选安装包同源且 SHA-256 相同的完整 sidecar 目录包。先用冲突表触发迁移失败，两个系统均记录了回滚日志，SQLite integrity 为 `ok`，版本恢复到 `a1b7c9d3e504`，合成业务标记和原表结构保留，且未出现 `desktop_folders`。移除隔离数据库中的冲突表后，用同一 sidecar 重试；两系统均启动成功并升级至 `c8d73b1e0afd`，合成业务标记保留、`desktop_folders` 与草稿 `owner_id` 列存在，完整性仍为 `ok`。Win10/Win11 的 0.1.0 → 0.1.1 安装升级另已通过前述记录。
- **存储位置：**两台 Hyper-V 虚拟机的配置、检查点、基础 VHDX、活动 AVHDX、安装介质、合成数据和测试辅助文件均在 `D:\ProfessionalSoftware\Project\Personal-AI-Life-OS\desktop\build\hyperv`；本轮确认两台 VM 的磁盘与检查点路径均以 D 盘开头。
- **D5 结论：**本机桌面 MVP 的 Windows 10/11 候选验收通过。签名、SmartScreen 信誉与自动更新继续作为公开分发门禁，不属于本机单人 MVP 的未完成项。

## 发布产物归档（2026-11-27）

- `desktop/dist/verified-0.1.0/`：2026-11-26 验收的 0.1.0 安装包，94,289,668 字节，SHA-256 `6888E94561CAD2AB5CDC9CF90B727BEF4023263D688A58E2A31B1FAB7E2A121C`；本轮未改动。
- `desktop/dist/verified-0.1.1/pre-version-alignment/`：D5 验收使用的 0.1.1 安装包（构建时用 Tauri 配置覆盖版本，仓库产品版本当时仍为 0.1.0），94,296,265 字节，SHA-256 `E6B80C83DD901164D77FFB6F5918C15F1D3164C5CB727FA0E70019CC05438D29`。
- `desktop/dist/verified-0.1.1/pre-api-version-fix/`：R1 首次版本统一后构建、Web OpenAPI 版本仍为 0.1.0 的产物（F1 修复前），94,288,339 字节，SHA-256 `87AFA3ABFB2134E70B89557FAEDFACBB58B55581A24389E9EEF868D448EFF72C`。
- `desktop/dist/verified-0.1.1/version-aligned/`：R1 修复 F1（Web OpenAPI 版本）后重建的安装包，94,285,130 字节，SHA-256 `149FBC9F4C993268D58DC190406C88F5019B1156EE01F24772D006A6FC3F748C`；构建工具链、安装/卸载与 sidecar `--full` 冒烟结果见 [0.1.1 发布记录](releases/0.1.1.md)。
- 上述四个目录均位于被 `.gitignore` 排除的 `desktop/dist/`。安装包不是按字节可复现构建，产物身份以 SHA-256 区分；清理或重建时先保留既有归档。
