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
- 干净 Windows 10/11 的安装、升级及系统交互矩阵仍待完成。Hyper-V 服务运行，Lenovo 已加入 Hyper-V Administrators，现有 Codex 进程的 Windows 登录令牌尚无该组，Hyper-V 管理查询被拒绝。
- 迁移回归从旧版数据库开始，注入部分写入失败，确认恢复了旧数据及迁移版本。重试后升级到最新版本，业务数据仍保留。
