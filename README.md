![访问计数](https://count.getloli.com/@apiuse_platform?name=apiuse_platform&theme=miku&padding=7&offset=0&align=center&scale=0.3&pixelated=1&darkmode=auto)

# API Pool Test Platform

本项目最初参考 new-api 的多渠道号池设计，目标是实现统一的 AI 中转与账号调度能力。new-api 主要面向标准 OpenAI、Anthropic 及 OpenAI-compatible API Key 场景，优点是请求格式统一、调用方式清晰、生态兼容性强。

但在实际开发和使用过程中，很多 AI 账号并不具备标准 API Key 形式，或者虽然可以调用模型能力，却需要特殊的鉴权方式、请求结构、会话状态、token 刷新逻辑或响应解析方式。例如 GitHub 上的 CLIProxyAPI、kiro.rs、grok2api 等项目，分别针对 CLI/OAuth 账号、Kiro 凭据、Grok Web 账号等场景实现了专门的请求适配。

因此，本项目在传统 Channel Pool 的基础上进一步抽象出 Provider Adapter 层，将“账号调度”和“请求适配”解耦。号池层负责用户鉴权、模型映射、渠道选择、失败切换、状态管理；Provider Adapter 层负责不同账号类型的鉴权、请求转换、流式处理、错误归一化和响应兼容。

通过这种设计，平台不仅可以支持标准 OpenAI/Anthropic API Key，也具备扩展到更多非标准账号形态和 Provider 类型的能力，从而提高账号接入灵活性与系统扩展性。

灵感来源 One API / New API,但只做 **号池调度 + 测试可视化**,不做计费 / 配额 / 虚拟 key 转发。当前是个人学习项目,但按企业级目录约定写——领域分层、依赖单向、模块自治。



## 项目结构

```
apiuse_platform/
├── app/
│   ├── main.py                       # 入口、lifespan、路由注册、静态页挂载
│   ├── api/
│   │   └── deps.py                   # 跨领域依赖:get_authenticated_user / get_admin_user / verify_api_key_dep
│   ├── core/                         # 横切关注点
│   │   ├── config.py                 # settings + .env + SecretStr(含 JWT/ENCRYPTION_KEY 启动校验)
│   │   ├── context.py                # request_id ContextVar
│   │   ├── crypto.py                 # API Key 加密/解密(Fernet)
│   │   ├── database.py               # SQLite 连接管理 + WAL + 建表 + 旧 JSON 迁移
│   │   ├── exceptions.py             # 全局异常处理
│   │   ├── log_config.py             # 日志格式 + request_id 注入
│   │   ├── middleware.py             # RequestIDMiddleware
│   │   └── security.py               # JWT + Argon2 密码哈希
│   ├── storage/                      # 通用存储原子能力(全部走 SQLite)
│   │   └── repos.py                  # UserRepo / SessionRepo / MessageRepo
│   ├── modules/                      # 领域模块,每个目录自治
│   │   ├── auth/                     # 注册 / 登录 / me / status ✅
│   │   ├── sessions/                 # 会话元信息 CRUD + LRU/TTL 清理 ✅
│   │   ├── messages/                 # 消息存取 + 滑窗 trim ✅
│   │   ├── chat/                     # 浏览器 SSE 聊天(/api/chat/stream)+ 断连存档 ✅
│   │   ├── adapter/                  # Provider Adapter 抽象(fake + openai_compat)✅
│   │   ├── channels/                 # 号池 CRUD + 加权随机 + failover 黑名单 + admin API ✅
│   │   ├── api_keys/                 # API Key 生成/验证/CRUD + test-connectivity ✅
│   │   ├── relay/                    # POST /v1/chat/completions OpenAI 兼容中继 ✅
│   │   ├── usage/                    # token 用量统计(/api/usage/*)✅
│   │   ├── plugins/                  # 插件系统(规划中,目录已占位)
│   │   ├── context/                  # 上下文构造(规划中,目录已占位)
│   │   ├── memory/                   # 长期记忆(规划中,目录已占位)
│   │   └── model_logs/               # 调用日志(规划中,目录已占位)
│   └── static/
│       ├── shared/                   # 公用 JS / CSS(sidebar 组件 + base.css)
│       └── pages/
│           ├── chat/                 # 聊天测试页(index.html / script.js / style.css)
│           ├── auth/                 # 登录 / 注册页
│           ├── channels/             # /channels 入口(重定向到 /channels/accounts)
│           ├── channels_accounts/    # 号池账户管理
│           ├── channels_keys/        # 号池密钥管理
│           └── channels_usage/       # 号池用量统计
├── data/                             # 持久化目录(.gitignore,不提交)
│   ├── data.db                       # SQLite 主库(WAL + 外键级联)
│   ├── users.json                    # 旧 JSON,启动时幂等迁移进 SQLite(保留作恢复源)
│   ├── channels.json                 # 早期 M2 号池配置,M2.5 后代码不再读取(历史存档)
│   └── channels/                     # M2.5 迁移源(auth/*.json + keys/*.json,启动时幂等迁移,保留作恢复源)
├── .env.example
├── CLAUDE.md                         # 项目协作规范 + 里程碑
├── README.md
└── requirements.txt
```

## 安装与启动

### 1. 创建虚拟环境

```powershell
python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # macOS / Linux
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

### 3. 配置环境变量

```powershell
copy .env.example .env
```

编辑 `.env`,**两个密钥必须显式配置**,启动期会校验,空值直接拒启动:

- `JWT_SECRET`:JWT 签名密钥,长度需 >= 32 字符
  ```powershell
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- `ENCRYPTION_KEY`:Fernet 密钥,用于可逆加密存储上游 channel 的原始 API Key,支持后台按需查看
  ```powershell
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```

`.env` 已被 `.gitignore` 忽略,不要提交。`AI_BASE_URL` / `AI_API_KEY` 仅保留为旧单上游占位,当前真实调用走 channel 池,不再依赖单一上游。

### 4. 上游 channel 配置

真实模型调用走 **channel 池 + Provider Adapter**:从 `enabled=true` 且不在黑名单的 channel 里按 `weight` 加权随机选一个,失败按错误类型自动 failover 或临时拉黑。Channel 通过 **管理后台** 创建/编辑,直接落 SQLite(`data/data.db`),不再手写 JSON。

- 打开 <http://127.0.0.1:8080/channels/accounts> 可视化管理 channel(需 admin 账号)。
- `USE_FAKE_AI=true` 时走本地模拟 provider,无需任何上游,适合本地开发;`false` 时走真实 channel 池,池为空会自动降级到 fake 并打印警告。
- `data/channels/{auth,keys}/*.json` 是 M2.5 由 JSON 迁移到 SQLite 时的旧数据源,启动时**幂等迁移**(已有记录跳过),保留作数据恢复源,不影响日常运行。`data/channels.json` 是更早期 M2 的号池配置,M2.5 后代码已不再读取,仅作历史存档。

### 5. 启动服务

```powershell
uvicorn app.main:app --reload --port 8080
```

- 聊天页:<http://127.0.0.1:8080/>
- 登录 / 注册:<http://127.0.0.1:8080/login>
- 号池管理:<http://127.0.0.1:8080/channels>(重定向到 `/channels/accounts`)
- OpenAPI 文档:<http://127.0.0.1:8080/docs>
- 健康检查:<http://127.0.0.1:8080/health>

## 核心能力

### OpenAI 兼容中继端点

`POST /v1/chat/completions` —— 用 OpenAI SDK / curl 直接对接,行为与官方接口一致:

- **API Key 鉴权**:请求头 `Authorization: Bearer sk-xxxx`,Key 由用户在 `/channels/keys` 页生成,`sk-` 前缀,SHA256 哈希存储,支持配额(`quota` / `used_quota`)与撤销。
- **流式 / 非流式**:`stream=true` 返回 `text/event-stream` 的 chunk 事件,`stream=false` 返回标准 `ChatCompletionResponse`。
- **Token tracking**:每次调用落 `call_logs` 表,记录 model / stream / prompt / completion / total tokens,并累加到对应 API Key 的 `used_quota`;`/api/usage/*` 提供按日 / 按模型的用量统计。
- **Model-aware channel selection**:请求里的 `model` 会参与 channel 过滤,只从支持该模型的 channel 里挑(见 `channels.service.select_channel`)。
- **Failover**:上游 5xx / 429 / 超时 / 连接错误自动拉黑 `CHANNEL_BLACKLIST_SECONDS` 秒并切下一个 channel;4xx(401/403/404)只记失败计数不拉黑;全军覆没返回安全错误文案,不向前端透出 API Key、Authorization 或原始上游响应体。

### 浏览器 SSE 聊天

`GET /api/chat/stream` —— 内置测试页用的流式聊天接口,JWT 鉴权:

- 第一帧发 `session_id`,后续 `token` 事件流式输出,结束发 `[DONE]`。
- **断连存档**:客户端中途断开时,已产出的部分回复仍会落库(`chat` router 检测 `request.is_disconnected()`),刷新后能在历史里看到。
- **会话恢复**:前端用 `sessionStorage` 保存当前 `session_id`,刷新页面自动恢复对话上下文。

## 存储模型

当前持久化是 **SQLite**(aiosqlite 单例连接),`data/data.db` 单文件,WAL 模式 + 外键级联,不再使用 JSON / 内存字典作为主存储。

| 表 | 外键 | 说明 |
|---|---|---|
| `users` | — | 用户账号,`username` UNIQUE,`password_hash` Argon2 |
| `sessions` | `user_id → users(id) ON DELETE CASCADE` | 删用户自动清会话 |
| `messages` | `session_id → sessions(id) ON DELETE CASCADE` | 删会话自动清消息,`id` 自增 |
| `channels` | — | 号池 channel,`api_key` 经 Fernet 加密存储 |
| `api_keys` | `user_id → users(id)` | 用户 API Key,`key_hash` SHA256 UNIQUE |
| `call_logs` | `api_key_id → api_keys(id) ON DELETE CASCADE` | 每次中继调用的 token 用量记录 |

时间字段统一存 ISO 8601 字符串。启动时 `init_db()` 建表 + `PRAGMA journal_mode=WAL` + `PRAGMA foreign_keys=ON`,并从旧 JSON 文件幂等迁移历史数据。内存压力靠两道闸:单会话滑窗 `SESSION_MAX_MESSAGES`、总会话 LRU + TTL(`MAX_ACTIVE_SESSIONS` / `SESSION_IDLE_TTL_MINUTES`)。

> 更多约定(模块边界、依赖方向、调度策略、安全约束、里程碑)见 `CLAUDE.md`。



