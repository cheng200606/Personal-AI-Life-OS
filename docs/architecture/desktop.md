# Windows 桌面端架构与交付计划

**状态：** 规划中，尚未实现  
**日期：** 2026-11-25  
**范围：** Windows 10/11 x64 单人本地桌面应用；Web 端保留为开发、参考和可选托管客户端。

## 1. 结论

- 桌面端采用 **Tauri 2 外壳 + 现有 React/Vite 界面 + Python FastAPI sidecar（PyInstaller）+ SQLite/本地对象存储**。
- 不重写业务逻辑：现有 API、领域模型、worker、OCR、复盘、提醒、导出与删除链路继续复用；桌面外壳负责进程、文件、通知、托盘、更新和安装。
- 桌面版默认完全本地运行，不依赖 Docker；外部 AI 仍是可选的云端调用，本地模型留作后续。
- 当前机器已具备 Node 24 和 WebView2，但缺少 Rust 与 PyInstaller；D0 需要先补齐构建工具链。
- 这是新增交付形态，不是把 Web 端简单包一层浏览器：文件访问、通知、自动更新、安装器和数据目录都需要单独验收。

## 2. 目标与非目标

### 2.1 目标

1. 在干净 Windows 10/11 上安装即用，无需 Docker、Postgres 或命令行。
2. 离线完成导入、时间线、统一检索、周复盘、提醒、导出、备份、删除和恢复。
3. 与 Web 端共用一套 API 契约和 React 界面，避免两套产品逻辑。
4. 支持托盘常驻、开机启动、Windows 通知、单实例和直接写 Obsidian Vault。
5. 支持签名安装包、签名自动更新、升级前备份和迁移失败回滚。
6. 数据默认存放在用户目录，卸载不静默删除用户资料。

### 2.2 非目标

- 不把桌面端做成多用户或团队客户端。
- 不承诺离线调用外部 AI；本地模型后续单独评估。
- 不做静默文件监听或全盘扫描；文件访问必须由用户选择。
- 不做 Windows 移动端/UWP；移动捕获留在 PWA 计划。
- 不做自动上传诊断或遥测；日志只留在本机，用户可导出。

## 3. 方案选择

| 方案 | 复用现有代码 | 安装体积/内存 | Windows 集成 | 风险 | 结论 |
| --- | --- | --- | --- | --- | --- |
| **Tauri 2 + Python sidecar** | 高（React + FastAPI 全复用） | 中等；WebView2 复用系统运行时 | 托盘、通知、自动启动、更新、文件对话框齐全 | 需要 Rust 工具链；sidecar 打包与签名 | **推荐** |
| Electron + Python sidecar | 高 | 较大；自带 Chromium | 成熟 | 体积、内存、需安全加固 | 备选 |
| PyWebView + Python | 高 | 较小 | 基础窗口可用，托盘/更新/权限较弱 | 产品级更新和安全能力不足 | 仅原型 |
| WinUI/WPF + WebView2 | 中；界面需重写 | 中等 | 最原生 | 新 C# 技术栈、双端维护 | 不推荐 |

**决定：** Tauri 2 + Python sidecar。若 Rust/Tauri 在签名、WebView2 兼容或构建链上形成硬阻塞，再切 Electron；不把 PyWebView 作为发布形态。

## 4. 总体架构

```text
Tauri 2 shell (Rust)
  ├─ 窗口 / 托盘 / 单实例 / 深链接
  ├─ sidecar supervisor：启动、健康检查、崩溃重启、优雅退出
  ├─ Windows 集成：通知、开机启动、文件/目录选择、更新
  ├─ 文件访问代理：只把用户选择的路径交给 sidecar
  └─ 本地回环通道：随机端口 + 每次启动密钥
        └─ Python sidecar (PyInstaller one-folder)
             ├─ 现有 FastAPI 应用（/api/v1）
             ├─ SQLite + 本地对象存储
             ├─ 现有 worker 线程（OCR、复盘、描述、调度）
             ├─ Alembic 迁移（随包分发）
             └─ Tesseract（eng + chi_sim 语言包）
React/Vite 界面（与 Web 共用，构建为静态资源）
```

### 4.1 启动流程

1. Tauri 选择空闲回环端口，生成一次性桌面密钥。
2. 启动 sidecar，传入端口、数据目录、桌面配置；sidecar 只监听 `127.0.0.1`。
3. sidecar 运行迁移（升级前先备份），启动 worker，写入就绪状态。
4. Tauri 轮询 `/api/v1/ready`；成功后再显示主窗口，失败进入诊断页并提供日志与恢复入口。
5. 退出时先停止 worker 与 sidecar，再关闭窗口；异常退出由 supervisor 记录并重启或提示。

### 4.2 本地 API 边界

- 只监听回环地址；端口随机，避免固定端口冲突。
- 桌面密钥通过请求头或 Tauri 注入，作为 bearer 之外的第二道本地防线。
- CORS 只允许 Tauri 本地来源；CSP 禁止远程脚本与任意连接。
- 现有用户登录继续保留；token 存入 Windows 凭据管理器，不写 `localStorage`。
- 其他本机进程无法在没有凭据的情况下读取 API；日志不写正文。

## 5. 数据与生命周期

### 5.1 数据目录

```text
%LOCALAPPDATA%\PersonalAILifeOS\
  data\lifeos.db          SQLite，WAL 模式
  objects\                本地对象存储（原件/照片副本）
  logs\                   轮转日志，不含正文
  backups\                迁移前/每日/手动备份
  runtime.json            当前端口与启动元数据（不含长期密钥）
```

安装目录只读；不把数据库放在 Program Files。提供“打开数据目录”“导出备份”“恢复备份”入口。

### 5.2 迁移与备份

- 启动时执行 `alembic upgrade head`；升级前自动备份数据库与对象清单。
- 迁移失败：停止启动，保留现场，提供“从备份恢复”与“导出诊断”。
- 自动更新前再备份一次；更新失败回退旧安装包与数据库备份。
- 备份默认保留有限份数，用户可手动导出 ZIP；不自动上传云端。

### 5.3 文件访问

- Tauri 负责文件/目录选择；sidecar 不直接接受任意路径。
- 导入时由外壳读取文件并流式上传到本地 API，或发放一次性路径令牌；首版优先流式上传，减少路径权限。
- 目录同步/监听由外壳持有授权，调用 sidecar 导入接口；撤权或删除后立即停止监听。
- 直接写 Obsidian Vault 由外壳执行，冲突策略与 CLI 一致：保留、覆盖、另存。

## 6. Windows 集成

| 能力 | 首版 | 说明 |
| --- | --- | --- |
| 系统托盘 | 是 | 关闭窗口可最小化到托盘；退出需显式操作 |
| 开机启动 | 可选 | 用户显式开启；默认关闭 |
| 单实例 | 是 | 再次启动聚焦已有窗口 |
| 通知 | 是 | 到期提醒、复盘就绪；尊重专注助手；点击打开对应记录 |
| 深链接 | 可选 | `lifeos://review/<id>` 等；首版可后置 |
| 文件对话框 | 是 | 导入文件/目录、选择 Vault、选择备份位置 |
| 自动更新 | 是 | 签名清单；稳定/测试通道 |
| 卸载 | 是 | 默认保留用户数据；提供“同时删除数据”明确选项 |

## 7. 复用与改造清单

| 现有部分 | 桌面处理 |
| --- | --- |
| React/Vite 界面 | 复用；构建 `base: './'`；增加桌面运行时适配层 |
| FastAPI 路由与领域服务 | 复用；新增 `desktop` 环境配置 |
| SQLite/本地对象存储 | 直接使用；不要求 Postgres |
| Worker | 随 sidecar 启动；调度能力在 M6 加入 |
| Alembic | 随包分发；启动时执行 |
| OCR | 打包 Tesseract 与中英文语言包；缺失时显示可用状态 |
| 认证 | 保留本地账号；token 存 Windows 凭据管理器 |
| CORS/CSP | 增加 Tauri 本地来源；收紧连接目标 |
| 日志 | 改为数据目录轮转文件；控制台日志可关闭 |

需要新增的配置模式：`APP_ENV=desktop`，默认 SQLite、本地对象存储、worker 开启、关闭邀请码与生产 TLS 校验。

## 8. 打包与发布

- **Python sidecar：** PyInstaller one-folder，Python 3.12 x64；包含 `migrations/`、Tesseract 与语言包；启动入口只负责配置、迁移、uvicorn 与优雅退出。
- **前端：** Vite 生产构建，静态资源随 Tauri 打包。
- **安装包：** NSIS 按用户安装（无需管理员）；企业场景可另出 MSI；提供便携 ZIP 作为可选通道。
- **签名：** 安装包与更新清单使用代码签名证书；发布前验证 SmartScreen 与常见杀毒软件。
- **更新：** Tauri updater 签名清单；先备份再更新；支持暂停/回滚说明。
- **CI：** GitHub Actions `windows-latest` 构建 sidecar、前端、Tauri 安装包；运行 Python 测试、Web lint/build 与 sidecar 健康冒烟。
- **版本：** 应用版本与 sidecar 版本一起写入安装包和关于页；升级时校验兼容性。

## 9. 测试与验收

### 9.1 自动化

- Python/Web 现有测试全量通过。
- 桌面冒烟：启动 sidecar、`/ready`、关闭、异常重启。
- 安装包冒烟：干净 Windows 虚拟机安装、首次启动、导入、检索、复盘、提醒、导出、备份、删除。
- 升级冒烟：上一版本安装 → 新版本升级 → 数据保留、迁移成功、失败恢复。
- 安全冒烟：非回环地址不可访问、无桌面密钥被拒绝、日志无正文。

### 9.2 手工验收

- Windows 10 与 11、100%/150% DPI、无 WebView2 的旧系统提示。
- 托盘、开机启动、通知点击、单实例、文件对话框、Vault 写入冲突。
- 断网、代理、外部 AI 失败、Tesseract 缺失、磁盘空间不足。
- 杀毒软件与 SmartScreen 提示；安装/卸载/保留数据。

## 10. 交付阶段（D 轨道）

| 阶段 | 目标 | 主要交付 | 退出条件 |
| --- | --- | --- | --- |
| D0 可行性验证 | 证明 Tauri + sidecar 可打包运行 | Rust/Node/Python 构建链、sidecar、最小窗口、健康检查、未签名安装包 | 干净 Windows 可启动、导入一条合成资料、退出无残留 |
| D1 桌面 MVP | 现有流程离线可用 | 登录、导入、时间线、检索、复盘、提醒、导出、备份/恢复、日志、凭据存储 | 不装 Docker 完成主流程；数据重启保留 |
| D2 Windows 集成 | 让桌面“像桌面” | 托盘、通知、开机启动、单实例、文件代理、直接写 Vault；接入 M6 调度与提醒 | 到期提醒可点击回记录；文件夹授权可撤销 |
| D3 发布工程 | 可安全分发 | 代码签名、自动更新、NSIS/MSI、升级回滚、CI、支持矩阵、隐私说明 | 签名安装与升级通过；失败可恢复 |
| D4 可选增强 | 降低依赖 | 本地模型、Windows OCR 备选、ARM64、便携模式 | 按证据单独评估 |

## 11. 与 M6–M11 的关系

- **D0 与 M6 设计并行。** M6 的复盘计划与到期提醒需要先确定桌面通知与常驻方式，避免先做仅浏览器可用的实现。
- **D1 放在 M6 之后。** 这样桌面首版直接包含“定时复盘 + 到期提醒”，而不是再补一次。
- **D2 与 M7/M10 对齐。** M7 的日历/本地文件连接器和 M10 的直接 Vault 写入依赖桌面的文件代理与授权模型。
- **M8/M9 不受形态影响。** 检索、笔记、模型选择继续在 API/React 层实现，桌面自动复用。
- **M11 托管多用户保持独立。** 桌面不引入多用户；Web 托管仍是可选路径。
- Web 端继续保留：作为开发调试、跨设备和未来托管入口；桌面是单人本地的主分发形态。

## 12. 风险与回退

| 风险 | 处理 |
| --- | --- |
| Rust/WebView2/签名工具链不熟 | D0 先做最小验证；锁定版本；保留 Electron 备选 |
| sidecar 体积与启动慢 | one-folder 打包；启动页；延迟加载 OCR；测量冷启动 |
| 杀毒/SmartScreen 拦截 | 代码签名、稳定发布、少用自解压；提供校验和 |
| 本地端口被占用 | 随机端口 + 重试 + 清晰错误 |
| 本机其他进程访问 API | 回环绑定、桌面密钥、凭据认证、CSP |
| 迁移或更新失败 | 升级前备份；失败恢复；保留旧安装包 |
| Web 与桌面行为分叉 | 共用 UI + 运行时适配层；同一 API 契约；同一测试集 |
| Tesseract 语言包许可/体积 | 只打包 eng+chi_sim；保留第三方声明；缺失时可重试 |
| 用户误以为完全离线 AI | 界面明确外部 AI 需网络与同意；本地模型单列 |

## 13. D0 可直接执行的任务

1. 安装并锁定 Rust stable、Tauri CLI、PyInstaller；记录版本。
2. 新建 `desktop/`：`src-tauri/`、sidecar 构建脚本、最小 React 加载页。
3. sidecar 入口：读取端口/数据目录/桌面密钥，执行迁移，启动 uvicorn 与 worker，输出就绪信号。
4. Tauri supervisor：启动、健康检查、退出、异常重启、日志落盘。
5. 用 PyInstaller 打 one-folder sidecar，验证 SQLite、对象存储、OCR 与 `/api/v1/ready`。
6. 生成未签名 NSIS 安装包，在干净 Windows 10/11 验证启动、导入、退出、数据目录保留。
7. 记录冷启动时间、安装包体积、WebView2 版本、端口与杀毒提示，作为 D1 输入。

## 14. 相关文档

- [Web 产品与架构概览](../architecture/overview.md)
- [架构决策 0001：云端处理与本地选源](../architecture/decisions/0001-cloud-first.md)
- [架构决策 0002：Windows 桌面外壳](../architecture/decisions/0002-windows-desktop-shell.md)
- [最终产品差距与开发方案](../roadmap/final-product-gap.md)
- [部署指南](../operations/deployment.md)
- [隐私设计](../architecture/privacy.md)
