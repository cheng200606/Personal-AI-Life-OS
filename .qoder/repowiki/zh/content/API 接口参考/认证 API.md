# 认证 API

<cite>
**本文引用的文件 **
- [src/personal_ai_life_os/api/routes/auth.py](file://src/personal_ai_life_os/api/routes/auth.py)
- [src/personal_ai_life_os/api/schemas.py](file://src/personal_ai_life_os/api/schemas.py)
- [src/personal_ai_life_os/security.py](file://src/personal_ai_life_os/security.py)
- [src/personal_ai_life_os/models.py](file://src/personal_ai_life_os/models.py)
- [src/personal_ai_life_os/config.py](file://src/personal_ai_life_os/config.py)
- [src/personal_ai_life_os/api/deps.py](file://src/personal_ai_life_os/api/deps.py)
- [src/personal_ai_life_os/main.py](file://src/personal_ai_life_os/main.py)
</cite>

## 目录
1. [引言](#引言)
2. [项目结构与定位](#项目结构与定位)
3. [认证端点总览](#认证端点总览)
4. [请求与响应模型](#请求与响应模型)
5. [详细接口说明](#详细接口说明)
6. [令牌机制与安全设计](#令牌机制与安全设计)
7. [桌面模式 x-lifeos-desktop 认证](#桌面模式-x-lifeos-desktop-认证)
8. [错误处理与排错建议](#错误处理与排错建议)
9. [安全与性能注意事项](#安全与性能注意事项)
10. [依赖关系与扩展点](#依赖关系与扩展点)
11. [结论](#结论)

## 引言
本文档聚焦 Personal AI Life OS 的认证相关 API，覆盖账户注册、登录、令牌返回格式、访问令牌的验证流程以及桌面模式的特殊认证方式。需要特别说明的是：当前后端代码中未实现独立的“刷新令牌”端点；访问令牌有效期结束后，客户端应重新通过 `/api/v1/auth/login` 获取新的令牌。文档会明确标注这一现状，避免产生误解。

## 项目结构与定位
认证功能由 FastAPI 路由模块提供，位于 `src/personal_ai_life_os/api/routes/auth.py`，并以统一前缀 `/api/v1/auth` 暴露给外部调用方。鉴权依赖共享认证依赖函数，密码哈希和 JWT 实现位于专用安全模块中。配置项包含访问令牌密钥、过期时间、注册模式和速率限制参数。整体架构遵循以下分层：
- API 路由层：定义注册、登录、描述信息等端点。
- 请求/响应模型层：基于 Pydantic 校验字段并输出稳定结构。
- 领域模型层：用户实体、时间戳及数据库字段约束。
- 安全层：密码哈希、JWT 编码与解码。
- 应用中间件层：桌面模式认证、通用安全防护、CORS 配置与基础速率限制逻辑。

```mermaid
graph TB
    Client["客户端<br/>浏览器、桌面客户端或脚本"] --> Router["认证路由<br/>/auth/register /auth/login /auth/me"]
    Router --> Schemas["请求响应模型<br/>RegisterRequest/LoginRequest/TokenResponse"]
    Router --> Security["安全模块<br/>hash_password/create_access_token"]
    Router --> Session["数据库会话<br/>查询/写入用户记录"]
    Session --> Model["User 数据模型"]
    Config["Settings 配置<br/>access_token_ttl_hours"] --> Security
    Middleware["中间件<br/>desktop/x-lifeos-desktop/限速/CSP"] --> Router
```

**图示来源**
- [src/personal_ai_life_os/api/routes/auth.py:1-210](file://src/personal_ai_life_os/api/routes/auth.py#L1-L210)
- [src/personal_ai_life_os/security.py:1-54](file://src/personal_ai_life_os/security.py#L1-L54)
- [src/personal_ai_life_os/config.py:1-132](file://src/personal_ai_life_os/config.py#L1-L132)
- [src/personal_ai_life_os/main.py:150-230](file://src/personal_ai_life_os/main.py#L150-L230)

**章节来源**
- [src/personal_ai_life_os/api/routes/auth.py:1-60](file://src/personal_ai_life_os/api/routes/auth.py#L1-L60)
- [src/personal_ai_life_os/main.py:150-230](file://src/personal_ai_life_os/main.py#L150-L230)

## 认证端点总览
| 方法 | 路径 | 用途 | 是否需要凭据 | 返回值 |
|---|---|---|---|---|
| POST | `/api/v1/auth/register` | 创建新用户并立即返回访问令牌 | 否 | `TokenResponse`，HTTP 201 |
| POST | `/api/v1/auth/login` | 使用邮箱和密码登录 | 否 | `TokenResponse` |
| GET | `/api/v1/auth/me` | 获取当前用户信息 | 是，Bearer Token | `UserResponse` |
| GET | `/api/v1/auth/model-disclosure` | 获取 AI 模型提供者披露信息 | 否 | 结构化配置摘要 |
| PUT | `/api/v1/auth/ai-consent` | 设置是否同意外部模型使用 | 是，Bearer Token | `UserResponse` |
| GET | `/api/v1/auth/desktop-profile` | 桌面模式中获取本地配置文件令牌 | 否（受桌面模式控制） | `TokenResponse` |
| POST | `/api/v1/auth/desktop-profile` | 初始化或删除后恢复桌面本地配置 | 否（受桌面模式控制） | `TokenResponse` |

需要注意的是，项目中不存在 `/api/v1/auth/refresh` 端点。访问令牌过期后，必须再次调用登录接口重新获取。

**章节来源**
- [src/personal_ai_life_os/api/routes/auth.py:15-195](file://src/personal_ai_life_os/api/routes/auth.py#L15-L195)
- [src/personal_ai_life_os/api/schemas.py:31-68](file://src/personal_ai_life_os/api/schemas.py#L31-L68)

## 请求与响应模型
### RegisterRequest
| 字段 | 类型 | 必填 | 默认值 | 规则 |
|---|---|---:|---:|---|
| email | 字符串 | 是 | — | 长度 5–320，经过标准化和基础邮箱格式校验 |
| password | 字符串 | 是 | — | 最小 12，最大 256 |
| timezone | 字符串 | 否 | UTC | 长度不超过 64，服务端会验证 IANA 时区 |
| invite_code | 字符串 | 否 | 空 | 邀请码注册模式下必填，用于防注册滥用 |

当注册模式为 `invitation` 时，`invite_code` 必须匹配服务端配置的邀请码；当注册模式为 `closed` 时，直接拒绝所有注册。

### LoginRequest
| 字段 | 类型 | 必填 | 默认值 | 规则 |
|---|---|---:|---:|---|
| email | 字符串 | 是 | — | 使用与注册相同的规范化邮箱校验 |
| password | 字符串 | 是 | — | 明文传输，由服务器验证其对应的哈希值 |

### UserResponse
| 字段 | 类型 | 含义 |
|---|---|---|
| id | 字符串 | 用户唯一标识 |
| email | 字符串 | 邮箱 |
| timezone | 字符串 | 用户时区 |
| ai_consent_at | 可空时间戳 | 同意对外部模型提供数据的时刻 |
| ai_consent_provider | 可空字符串 | 同意的模型提供者 ID |
| ai_consent_disclosure_version | 可空字符串 | 披露版本 |
| created_at | 时间戳 | 账户创建时间 |

### TokenResponse
| 字段 | 类型 | 含义 |
|---|---|---|
| access_token | 字符串 | JWT 访问令牌 |
| token_type | 字符串 | 固定值为 bearer |
| expires_in | 整数 | 以秒为单位的访问令牌过期时长 |
| user | 对象 | 当前用户信息，对应 UserResponse |

**章节来源**
- [src/personal_ai_life_os/api/schemas.py:31-68](file://src/personal_ai_life_os/api/schemas.py#L31-L68)
- [src/personal_ai_life_os/security.py:23-54](file://src/personal_ai_life_os/security.py#L23-L54)

## 详细接口说明

### POST /api/v1/auth/register
在开放注册或邀请注册模式下，该接口创建用户并返回访问令牌。

#### 行为流程
```mermaid
flowchart TD
    Start(["接收注册请求"]) --> ModeCheck["检查注册模式<br/>closed / invitation / open"]
    ModeCheck --> TimezoneValidate["验证时区是否为有效 IANA 名称"]
    TimezoneValidate --> EmailExists{"邮箱是否已存在"}
    EmailExists -->|是| Error409["返回 409：账户已存在"]
    EmailExists -->|否| HashPassword["对密码进行安全哈希"]
    HashPassword --> SaveUser["保存用户记录到数据库"]
    SaveUser --> CommitOK{"提交是否成功"}
    CommitOK -->|失败且仍发现冲突| Error409
    CommitOK -->|其他异常| RollbackAndRethrow["回滚事务并抛出异常"]
    CommitOK -->|成功| GenerateToken["生成访问令牌和用户响应"]
    GenerateToken --> Return201["返回 201 Created 和 TokenResponse"]
```

**图示来源**
- [src/personal_ai_life_os/api/routes/auth.py:61-140](file://src/personal_ai_life_os/api/routes/auth.py#L61-L140)
- [src/personal_ai_life_os/models.py:60-84](file://src/personal_ai_life_os/models.py#L60-L84)

#### 请求示例
```json
{
  "email": "alice@example.com",
  "password": "StrongP@ssw0rdExample",
  "timezone": "Asia/Shanghai"
}
```
若启用邀请码注册，则附加：
```json
{
  "email": "bob@example.com",
  "password": "StrongP@ssw0rdExample",
  "timezone": "UTC",
  "invite_code": "从管理员处获得的邀请码"
}
```

#### 成功响应示例
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 43200,
  "user": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "email": "alice@example.com",
    "timezone": "Asia/Shanghai",
    "ai_consent_at": null,
    "ai_consent_provider": null,
    "ai_consent_disclosure_version": null,
    "created_at": "2026-11-27T10:00:00+00:00"
  }
}
```
HTTP 状态码为 **201 Created**。

#### 错误处理
| HTTP 状态 | 错误场景 | 典型 detail | 客户端建议 |
|---|---|---|---|
| 403 | 注册被关闭 | `code` 为 registration_closed | 联系管理员开启注册或通过邀请注册 |
| 403 | 邀请码无效或缺失 | `code` 为 invalid_invitation | 检查邀请码是否正确 |
| 422 | 时区不是有效 IANA 名称 | code 指向无效时区 | 修改为 IANA 标准时区，例如 Asia/Shanghai |
| 409 | 邮箱已存在 | code 为 account_exists | 尝试登录或使用其他邮箱 |
| 422 | 邮箱格式不符合规范 | 由字段校验器报错 | 检查邮箱大小写、域名分隔符和空格 |
| 其他异常 | 事务失败或服务端错误 | 通用异常 | 重试并查看服务日志 |

**章节来源**
- [src/personal_ai_life_os/api/routes/auth.py:61-140](file://src/personal_ai_life_os/api/routes/auth.py#L61-L140)
- [src/personal_ai_life_os/models.py:60-84](file://src/personal_ai_life_os/models.py#L60-L84)
- [src/personal_ai_life_os/api/schemas.py:31-48](file://src/personal_ai_life_os/api/schemas.py#L31-L48)

### POST /api/v1/auth/login
登录成功后返回访问令牌。桌面环境中该端点会返回 404，因为桌面环境应优先使用本机桌面配置流程或直接使用 Bearer Token 访问其他接口。

#### 行为流程
```mermaid
flowchart TD
    Begin["接收登录请求"] --> EnvCheck["判断是否为桌面环境"]
    EnvCheck -->|是| NotFound["返回 404 Not found"]
    EnvCheck -->|否| FindUser["按邮箱查找用户"]
    FindUser --> ValidUser{"找到用户且密码正确"}
    ValidUser -->|否| AuthFailed["返回 401，WWW-Authenticate: Bearer"]
    ValidUser -->|是| IssueToken["返回 access_token 和用户信息"]
```

**图示来源**
- [src/personal_ai_life_os/api/routes/auth.py:141-172](file://src/personal_ai_life_os/api/routes/auth.py#L141-L172)

#### 请求示例
```json
{
  "email": "alice@example.com",
  "password": "StrongP@ssw0rdExample"
}
```

#### 成功响应示例
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 43200,
  "user": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "email": "alice@example.com",
    "timezone": "UTC",
    "ai_consent_at": null,
    "ai_consent_provider": null,
    "ai_consent_disclosure_version": null,
    "created_at": "2026-11-27T10:00:00+00:00"
  }
}
```

#### 失败响应示例
```json
{
  "code": "invalid_credentials",
  "message": "Email or password is incorrect."
}
```
HTTP 状态码为 **401 Unauthorized**，并包含 `WWW-Authenticate: Bearer` 响应头。

#### 关于“刷新令牌”的澄清
当前后端没有 `/api/v1/auth/refresh` 端点。访问令牌会在 `expires_in` 指定的秒数后失效。过期后的正确处理方式是重新调用登录接口。若客户端需要在无交互场景中维持长期会话，应由服务器端扩展实现显式的 refresh token 机制；该项目尚未实现该能力。

**章节来源**
- [src/personal_ai_life_os/api/routes/auth.py:141-172](file://src/personal_ai_life_os/api/routes/auth.py#L141-L172)
- [src/personal_ai_life_os/api/schemas.py:56-68](file://src/personal_ai_life_os/api/schemas.py#L56-L68)

### GET /api/v1/auth/me
用于读取当前已认证用户的详情。该端点依赖于 Bearer Token 鉴权。

#### 请求要求
- 在 Authorization 头中包含 Bearer Token：
  ```
  Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
  ```

#### 成功响应示例
```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "email": "alice@example.com",
  "timezone": "UTC",
  "ai_consent_at": "2026-11-27T10:05:00+00:00",
  "ai_consent_provider": "openai",
  "ai_consent_disclosure_version": "openai-chat-completions-v1",
  "created_at": "2026-11-27T10:00:00+00:00"
}
```

#### 常见失败场景
| 状态码 | 含义 | detail |
|---|---|---|
| 401 | 缺少授权头或授权头为空 | `code` 为 auth_required |
| 401 | 访问令牌无效或已过期 | `code` 为 invalid_access_token |
| 410 | 账户正在删除清理过程中，禁止访问 | `code` 为 account_deletion_pending |

**章节来源**
- [src/personal_ai_life_os/api/routes/auth.py:174-179](file://src/personal_ai_life_os/api/routes/auth.py#L174-L179)
- [src/personal_ai_life_os/api/deps.py:18-55](file://src/personal_ai_life_os/api/deps.py#L18-L55)

## 令牌机制与安全设计

### JWT 访问令牌
系统使用 HS256 算法签名 JWT，并由 Settings 中的配置决定签发者、受众和过期时长。

| 声明 | 含义 |
|---|---|
| sub | 用户 ID |
| iat | 令牌签发时间 |
| exp | 令牌过期时间，基于 `access_token_ttl_hours` 计算 |
| iss | 固定签发者 `personal-ai-life-os` |
| aud | 固定受众 `personal-ai-life-os-api` |
| typ | 固定类型 `access` |

#### 主要特征
- 使用 `pwdlib.PasswordHash.recommended()` 进行密码哈希与验证。
- 解析访问令牌时强制要求 `sub`、`exp`、`iat`、`iss`、`aud` 五个必需声明。
- 如果类型不是 `access`，也视为无效令牌。
- 客户端应把返回的 `access_token` 放入 `Authorization: Bearer <token>`。

#### 过期与刷新策略
| 情况 | 推荐处理方式 |
|---|---|
| 登录成功 | 保存 `access_token` 和 `expires_in` |
| 调用资源接口收到 401 且 code 为 invalid_access_token | 提示用户重新登录，或直接调用 login 刷新令牌 |
| 需要自动续期 | 当前后端不支持 refresh token，应由前端增加重试逻辑后重新登录 |

```mermaid
sequenceDiagram
    participant Client as "客户端"
    participant API as "FastAPI 路由"
    participant Deps as "get_current_user"
    participant Security as "decode_access_token"
    participant DB as "用户表"

    Client->>API: 携带 Authorization: Bearer
    API->>Deps: 解析当前用户
    Deps->>Security: 解码并验证令牌
    Security-->>Deps: 返回用户 ID 或 None
    alt 令牌有效
        Deps->>DB: 查询用户实体
        DB-->>Deps: 返回用户
        Deps-->>API: 返回已认证用户
        API-->>Client: 业务响应
    else 令牌缺失或无效
        Deps-->>API: 401 与 WWW-Authenticate: Bearer
        API-->>Client: 认证错误
    end
```

**图示来源**
- [src/personal_ai_life_os/security.py:23-54](file://src/personal_ai_life_os/security.py#L23-L54)
- [src/personal_ai_life_os/api/deps.py:18-55](file://src/personal_ai_life_os/api/deps.py#L18-L55)
- [src/personal_ai_life_os/models.py:60-84](file://src/personal_ai_life_os/models.py#L60-L84)

**章节来源**
- [src/personal_ai_life_os/security.py:1-54](file://src/personal_ai_life_os/security.py#L1-L54)
- [src/personal_ai_life_os/config.py:20-40](file://src/personal_ai_life_os/config.py#L20-L40)
- [src/personal_ai_life_os/api/deps.py:18-55](file://src/personal_ai_life_os/api/deps.py#L18-L55)

### 密码哈希与存储
- 密码不在数据库中明文存储。
- 使用通用的推荐密码哈希方案，便于升级后端哈希算法而不破坏已有数据。
- 验证失败时会屏蔽具体异常细节，避免泄露底层哈希实现差异。

**章节来源**
- [src/personal_ai_life_os/security.py:7-21](file://src/personal_ai_life_os/security.py#L7-L21)
- [src/personal_ai_life_os/models.py:60-84](file://src/personal_ai_life_os/models.py#L60-L84)

## 桌面模式 x-lifeos-desktop 认证
桌面模式使用独立的路径和环境检查机制。核心入口如下：
- 桌面配置接口 `/api/v1/auth/desktop-profile` 仅在服务 `app_env == "desktop"` 时可用。
- 普通 `/api/v1/auth/login` 在桌面环境中返回 404，不应作为桌面主身份通道。
- 全局中间件支持 `x-lifeos-desktop` 请求头来保护桌面专属接口：缺少或错误的桌面密钥会返回 401，错误码为 `desktop_auth_required`。

#### 桌面模式行为
```mermaid
sequenceDiagram
    participant Desktop as "Life OS 桌面进程"
    participant Server as "FastAPI 中间件"
    participant AuthRoute as "认证路由"

    Desktop->>Server: 请求带 X-LifeOS-Desktop: <密钥>
    Server->>Server: 比对桌面密钥
    alt 密钥不正确或缺失
        Server-->>Desktop: 401 desktop_auth_required
    else 密钥正确且为桌面环境
        Desktop->>AuthRoute: GET /api/v1/auth/desktop-profile
        AuthRoute-->>Desktop: TokenResponse
    end
```

**图示来源**
- [src/personal_ai_life_os/main.py:150-190](file://src/personal_ai_life_os/main.py#L150-L190)
- [src/personal_ai_life_os/api/routes/auth.py:27-59](file://src/personal_ai_life_os/api/routes/auth.py#L27-L59)

#### 请求与响应示例
- 桌面请求需添加 `X-LifeOS-Desktop` 请求头；该头部由内部桌面运行时注入或验证，不向普通 Web 客户端公开密钥内容。
- 成功时返回与注册/登录相同的 `TokenResponse`，可用于后续 Bearer Token 调用。

**章节来源**
- [src/personal_ai_life_os/main.py:150-230](file://src/personal_ai_life_os/main.py#L150-L230)
- [src/personal_ai_life_os/api/routes/auth.py:15-59](file://src/personal_ai_life_os/api/routes/auth.py#L15-L59)

## 错误处理与排错建议

### 认证相关常用状态码与错误码
| 状态码 | 错误码或场景 | 含义 | 客户端操作 |
|---:|---|---|---|
| 201 | register 成功 | 账户创建成功并返回令牌 | 缓存 `access_token` |
| 401 | invalid_credentials | 邮箱或密码错误 | 提示用户重试，避免暴力猜测 |
| 401 | auth_required | 缺少授权头 | 补充 Authorization 头 |
| 401 | invalid_access_token | 令牌无效或过期 | 让用户重新登录或刷新上下文 |
| 403 | registration_closed | 注册关闭 | 不可再注册，请联系管理员 |
| 403 | invalid_invitation | 邀请码无效 | 检查邀请码来源 |
| 404 | desktop-only | 非桌面环境调用桌面接口 | 在桌面应用内使用 |
| 404 | login in desktop | 桌面环境禁用常规登录 | 改用桌面 profile 或直接使用已获令牌 |
| 409 | account_exists | 邮箱重复 | 更换邮箱或登录 |
| 410 | account_deletion_pending | 账户已申请删除 | 等待清理完成或取消删除流程 |
| 422 | invalid_timezone | 无效 IANA 时区 | 改为合法时区 |
| 422 | 邮箱格式错误 | Pydantic 校验失败 | 修正邮箱格式 |
| 429 | rate_limited | 被限流 | 遵守 Retry-After 延迟重试 |
| 503 | imports_paused | 导入功能被暂停 | 稍后再试 |

### 常见问题排查
- **用户名已存在**：注册时出现 409 `account_exists`。请确认邮箱是否正确；如果是同一账户反复注册导致并发冲突，服务器会回滚并再次检查后返回 409。
- **凭据无效**：登录时出现 401 `invalid_credentials`。请检查邮箱和大小写，以及是否误用不同环境的测试账号。
- **令牌过期**：调用受保护接口出现 401 `invalid_access_token`。请检查 `expires_in` 是否已过去，并重新执行登录流程。
- **桌面模式无法访问**：出现 `desktop_auth_required`。请确认运行在桌面环境，并且请求包含正确的 `X-LifeOS-Desktop` 头部。
- **频繁注册被限流**：出现 429 `rate_limited`。请降低注册频率，尊重 `Retry-After` 响应头。

**章节来源**
- [src/personal_ai_life_os/api/routes/auth.py:61-179](file://src/personal_ai_life_os/api/routes/auth.py#L61-L179)
- [src/personal_ai_life_os/api/deps.py:24-55](file://src/personal_ai_life_os/api/deps.py#L24-L55)
- [src/personal_ai_life_os/main.py:170-220](file://src/personal_ai_life_os/main.py#L170-L220)

## 安全与性能注意事项

### 安全措施
- 使用强随机 JWT 密钥，生产环境要求密钥至少 32 位，不能保留开发默认值。
- 使用推荐的密码哈希库对用户密码进行哈希和验证。
- 访问令牌具有严格声明校验、签发者和受众校验，并可限制类型仅为 `access`。
- 服务端中间件强制设置基础安全响应头，包括反点击劫持、引用源策略和内容安全策略。
- 桌面模式密钥比较采用常量时间比较，降低时序侧信道风险。

### 速率限制配置
| 接口或动作 | 内置默认限制 | 窗口 | 可配置项 |
|---|---:|---:|---|
| POST /api/v1/auth/login | 每秒或累计限制由中间件维护 | 300 秒 | 使用通用事件计数队列，登录端点硬编码为每 IP 10 次左右限制 |
| POST /api/v1/auth/register | `registration_rate_limit` | 3600 秒 | 可通过 Settings 配置 |
| POST /sources/**/imports | 固定 30 次 | 60 秒 | 可配合 `imports_enabled` 开关暂停导入 |

生产部署还应额外使用反向代理或网关进一步限制认证接口的暴力破解攻击，并启用 HTTPS、HTTPS 证书校验、防火墙和网络审计。

**章节来源**
- [src/personal_ai_life_os/config.py:20-40](file://src/personal_ai_life_os/config.py#L20-L40)
- [src/personal_ai_life_os/config.py:95-132](file://src/personal_ai_life_os/config.py#L95-L132)
- [src/personal_ai_life_os/main.py:150-220](file://src/personal_ai_life_os/main.py#L150-L220)

## 依赖关系与扩展点

```mermaid
graph LR
    Main["main.py<br/>应用启动、中间件、速率限制"] --> AuthRouter["routes/auth.py<br/>注册/登录/描述/AI 同意"]
    AuthRouter --> Schemas["schemas.py<br/>RegisterRequest/LoginRequest/TokenResponse"]
    AuthRouter --> Security["security.py<br/>hash_password/jwt.encode"]
    AuthRouter --> Models["models.py<br/>User"]
    AuthRouter --> Settings["config.py<br/>Settings"]
    ProtectedEndpoints["其他认证接口<br/>GET /me /AI consent"] --> Deps["deps.py<br/>get_current_user"]
    Deps --> Security
```

**图示来源**
- [src/personal_ai_life_os/main.py:150-230](file://src/personal_ai_life_os/main.py#L150-L230)
- [src/personal_ai_life_os/api/routes/auth.py:15-195](file://src/personal_ai_life_os/api/routes/auth.py#L15-L195)
- [src/personal_ai_life_os/api/schemas.py:31-68](file://src/personal_ai_life_os/api/schemas.py#L31-L68)
- [src/personal_ai_life_os/security.py:1-54](file://src/personal_ai_life_os/security.py#L1-L54)
- [src/personal_ai_life_os/models.py:60-84](file://src/personal_ai_life_os/models.py#L60-L84)
- [src/personal_ai_life_os/api/deps.py:18-55](file://src/personal_ai_life_os/api/deps.py#L18-L55)

## 结论
Personal AI Life OS 的认证体系以邮箱加密码注册与登录为基础，返回符合 RFC 风格的 Bearer Token，并通过统一的 `get_current_user` 依赖验证其他接口访问权限。系统提供了良好的密码哈希、JWT 结构和生产安全检查，同时支持桌面模式的专用认证流程。由于当前没有刷新令牌端点，客户端应在访问令牌过期后重新登录。实际集成时建议结合网络层的限流、HTTPS、反向代理防护和日志审计，以获得更完善的认证安全体验。