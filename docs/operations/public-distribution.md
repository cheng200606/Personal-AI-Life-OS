# 公开分发 runbook

面向"把桌面安装包分发给他人"的场景。当前 0.1.1 为**未签名本机候选**，按仓库红线不得公开分发；本文描述获批公开分发前的外部资源决策、仓库内已就绪的签名/更新器工具链，以及真实签名发布的操作序列。发布门禁清单见 [release checklist](release-checklist.md)；本机候选验收见 [桌面本地验收](desktop-acceptance.md)。

## 1. 外部资源决策（仓库外，需维护者确认）

### 1.1 代码签名证书

| 路线 | 大致成本 | 说明 |
| --- | --- | --- |
| Azure Trusted Signing（微软） | 约 $9.99/月起 | 云端签名，微软证书带 SmartScreen 信誉基础；需身份验证，**需核实所在区域可用性** |
| OV/IV 代码签名证书（DigiCert/Sectigo/GlobalSign/SSL.com 等） | 约 $200–500/年 | 2023-06 起私钥强制硬件保护（USB token 或云签名服务），**不能导出 PFX**；实际用法是把证书装到本机证书存储后按 thumbprint 签名 |
| EV 代码签名证书 | 约 $300–700/年 | 即刻获得 SmartScreen 信誉基础；同样硬件保护 |
| 自签名/测试证书 | 免费 | **仅允许用于签名链路演练**，产物不得分发 |

以上价格为公开挂牌量级，以厂商当期报价为准。

### 1.2 SmartScreen 信誉

新证书的发行者信誉从零积累，初期下载仍可能出现"未知发布者"警告；信誉随安装量与时间改善，EV/Trusted Signing 证书起点更高但不保证零警告。发布后保留警告截图与安装量记录，作为信誉增长证据。

### 1.3 更新托管

任意静态 HTTPS 即可（GitHub Releases、私有 S3 兼容桶 + CDN）。需要长期保存：每个版本的 `setup.exe`、`.sig`、`latest.json` 三件套，域名与 TLS 由托管方提供，成本约 $0–5/月起。

## 2. 仓库内工具链（已就绪）

构建入口仍为 `desktop/build-installer.ps1`；**不设置下列环境变量时，构建流程与 0.1.1 本地候选逐字节一致**（CI 无需改动）。

| 环境变量 | 作用 |
| --- | --- |
| `LIFEOS_SIGN_THUMBPRINT` | 用本机证书存储中已安装的证书签名（token/云签名证书的推荐路线）；走 Tauri 原生 signtool，签名应用 exe、卸载器与安装器 |
| `LIFEOS_SIGN_PFX_PATH` / `LIFEOS_SIGN_PFX_PASSWORD` | PFX 文件路线（测试证书或旧证书）；经 `desktop/sign-release.ps1` shim（`signCommand`）签名同样的三组文件 |
| `LIFEOS_SIGN_TIMESTAMP_URL` | RFC 3161 时间戳服务器（默认 digicert） |
| `LIFEOS_SIGNTOOL_PATH` | 显式指定 signtool.exe（默认自动搜 PATH 与 Windows Kits） |
| `TAURI_SIGNING_PRIVATE_KEY`（及 `_PASSWORD`） | 启用 `bundle.createUpdaterArtifacts`，产物附加 `.sig` 更新签名（供 latest.json 使用） |

机制：`desktop/release-overlay.ps1` 在检测到上述变量时生成 Tauri 配置 overlay（写入被 git-ignore 的 `desktop/src-tauri/target/release-overlay.json`，证书身份不进仓库），并以 `--config` 附加给 `tauri build`。thumbprint 与 PFX 同时设置时优先 thumbprint。

更新密钥对生成（一次性，私钥入库外保存，例如密码管理器/云 KMS）：

```powershell
npx --prefix web tauri signer generate -w <私钥保存路径>
```

## 3. 真实签名发布操作序列

1. 完成本节前置：证书可用、更新密钥对已生成、更新托管地址已确定。
2. 设置环境变量后构建并冒烟：

```powershell
$env:LIFEOS_SIGN_THUMBPRINT = "<SHA-1 thumbprint>"
$env:TAURI_SIGNING_PRIVATE_KEY = "<更新私钥>"
./desktop/build-installer.ps1 -SevenZip "C:/Program Files/7-Zip/7z.exe"
./desktop/smoke-installer.ps1
Get-FileHash desktop/src-tauri/target/release/bundle/nsis/*.exe
Get-AuthenticodeSignature desktop/src-tauri/target/release/bundle/nsis/*.exe   # Status 应为 Valid
```

3. 归档签名产物（含 `.sig`）到 `desktop/dist/verified-<版本>/signed/`，在 `docs/operations/releases/<版本>.md` 记录哈希、证书主体、时间戳服务器与构建环境。
4. 按版本更新 `desktop/src-tauri/tauri.conf.json`（单一版本来源），运行 `tests/test_desktop_release.py` 确认四处版本一致。
5. 打附注 tag 并推送；上传 `setup.exe`、`.sig`、`latest.json` 到托管地址。
6. `latest.json` 格式（`signature` 为 `.sig` 文件内容）：

```json
{
  "version": "0.1.2",
  "notes": "0.1.2 发布说明",
  "pub_date": "2026-12-01T00:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "signature": "<.sig 文件内容>",
      "url": "https://<托管地址>/Personal AI Life OS_0.1.2_x64-setup.exe"
    }
  }
}
```

7. 建议先灰度：仅自己与少数测试设备核对升级路径后，再公开链接。

## 4. 升级路径与回滚

- 已实测 NSIS 0.1.0 → 0.1.1 静默升级保留用户数据（见 [桌面本地验收](desktop-acceptance.md)）。
- 回滚：把 `latest.json` 指回上一版本安装器地址并签名确认；已安装客户端不受影响，升级失败可按验收流程恢复备份。

## 5. 下一步（仓库内待办）

运行时自动更新尚未集成，当前产物只包含更新签名工件。集成步骤（需一次完整构建 + 冒烟验收）：

1. `desktop/src-tauri/Cargo.toml` 增加 `tauri-plugin-updater = "2"`；
2. `desktop/src-tauri/src/main.rs` 注册 updater 插件，指向 `latest.json` 端点（公钥由 `tauri signer generate` 的 `pubkey` 提供）；
3. 设置页增加"检查更新"入口与更新结果反馈；
4. 在干净 Win10/11 虚拟机验收"旧版本 → 新版本"的自动更新与校验失败路径（断网、签名不符）。

## 6. 红线与边界

- 未签名安装包不得公开分发；自签名产物仅限本机链路演练。
- 公开分发前按 [release checklist](release-checklist.md) 复核门禁；真实个人资料准入仍是独立决策。
- 本文的价格/区域信息为 2026-11 检索量级，执行前以厂商官网当期信息为准。
