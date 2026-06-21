# CLAUDE.md

## 1. 项目定位

这是一个 **OpenAI 兼容协议的简化号池中转平台**,主用途是测试和验证多上游 API Key 的可用性、调度策略和故障转移行为。

补充说明:

- 灵感来源 **One API / New API**,但不做计费 / 配额 / 虚拟 key 转发,只做"号池调度 + 测试可视化"
- 是个人学习项目,但**按企业级目录约定写**:领域分层、依赖单向、模块自治,未来能直接套进团队工程
- 当前重点理解 LLM 网关、负载均衡、SSE 代理透传的内部机制,后期会扩展插件 / 多 Provider / 调用日志 / Docker 部署

Claude 在本项目中的角色:

```
学习引导者 + 架构解释者 + 谨慎执行者
```

> 历史:项目早期是"流式聊天学习项目",经历过 P0(FastAPI + asyncio + SSE)、P1(用户认证 + MySQL + 模型调用日志 + 会话摘要)。M1 重定位为号池测试平台,删除全部 DB / 摘要 / 日志代码,改内存 + json。M1.5 起目录按 `modules/<领域>/` 重组。

---

## 2. 模块化结构(目标形态)

按**领域分层**(DDD lite):每个领域一个独立子包,自带 `router / service / crud / schemas`,需要时加 `models.py`。横切关注点(配置、日志、中间件、安全)放 `core/`,原子存储能力放 `storage/`。

```
app/
├── main.py                       # FastAPI 入口、lifespan、路由注册
├── api/
│   └── deps.py                   # 跨领域依赖:get_current_user / get_admin_user
│
├── core/                         # 横切关注点
│   ├── config.py                 # settings + .env + SecretStr
│   ├── logging.py                # 日志格式 + request_id 注入
│   ├── middleware.py             # RequestIDMiddleware
│   ├── exceptions.py             # 全局异常处理
│   ├── security.py               # JWT + 密码哈希
│   ├── context.py                # request_id ContextVar
│   ├── database.py               # SQLite 连接管理 + 建表
│   └── crypto.py                 # API Key 加密/解密
│
├── storage/                      # 通用存储能力 (SQLite 持久化)
│   └── repos.py                  # UserRepo / SessionRepo / MessageRepo
│
├── modules/                      # 领域模块,每个目录自治
│   ├── auth/                     # 注册 / 登录 / me
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── crud.py
│   │   └── schemas.py
│   │
│   ├── sessions/                 # 会话元信息 CRUD
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── crud.py
│   │   └── schemas.py
│   │
│   ├── messages/                 # 消息存取 + 滑窗 trim
│   │   ├── service.py
│   │   ├── crud.py
│   │   └── schemas.py
│   │
│   ├── chat/                     # SSE 编排:sessions + messages + ai_providers
│   │   ├── router.py             # /api/chat/stream
│   │   ├── service.py            # prepare_stream / persist_assistant
│   │   ├── stream.py             # SSE 帧封装
│   │   └── schemas.py
│   │
    │   ├── channels/                 # 号池管理 + 调度
    │   │   ├── router.py             # /api/channels/models(公开) + /api/admin/channels/*(管理)
    │   │   ├── service.py
    │   │   ├── crud.py
    │   │   ├── scheduler.py          # 加权随机 + failover + 黑名单
    │   │   └── schemas.py
    │   │
    │   ├── api_keys/                 # API Key 管理
    │   │   ├── router.py             # /api/keys(用户) + /api/admin/keys(管理)
    │   │   ├── service.py            # 生成/验证/CRUD
    │   │   ├── crud.py
    │   │   └── schemas.py
│   │
│   ├── ai_providers/             # Provider 抽象(M2 起逐步落地)
│   │   ├── base.py               # Provider 抽象基类
│   │   ├── service.py            # dispatch_chat / dispatch_chat_stream
│   │   ├── fake.py
│   │   ├── openai_compat.py      # OpenAI 兼容协议
│   │   ├── newapi.py             # New-API 上游
│   │   └── schemas.py
│   │
│   ├── plugins/                  # 插件系统(M5)
│   │   ├── router.py             # /api/plugins
│   │   ├── service.py
│   │   ├── registry.py           # 注册中心
│   │   ├── executor.py           # 执行 + 沙箱
│   │   ├── plugin_types.py
│   │   ├── schemas.py
│   │   └── builtin/
│   │       ├── echo.py
│   │       ├── calculator.py
│   │       └── time_tool.py
│   │
│   ├── context/                  # 上下文构造(M6)
│   │   ├── service.py
│   │   ├── builder.py            # history + summary + memory 拼接
│   │   └── schemas.py
│   │
│   ├── memory/                   # 长期记忆(M6)
│   │   ├── router.py
│   │   ├── service.py
│   │   ├── crud.py
│   │   └── schemas.py
│   │
│   └── model_logs/               # 调用日志(M6)
│       ├── service.py
│       ├── crud.py
│       └── schemas.py
│
└── static/
    ├── pages/
    │   ├── chat/                 # 聊天测试页
    │   ├── channels_accounts/    # 号池账户管理
    │   ├── channels_keys/        # 号池密钥管理
    │   ├── channels_usage/       # 号池用量统计
    │   └── admin/                # 号池管理后台(M3)
    └── shared/                   # 公用 JS / CSS (sidebar 组件)
```

**依赖方向单向**(上层可调下层,反之禁止):

```
modules/*           → storage / core
modules/chat        → modules/sessions, modules/messages, modules/ai_providers, modules/context
modules/channels    → modules/ai_providers
modules/ai_providers → modules/channels (调度时拿 channel)
modules/api_keys    → storage (通过 crud)
api/deps            → modules/auth (拿 user)
```

横向跨模块只允许通过 `service.py` 暴露的函数,**不允许跨模块 import crud / models**。

---

## 3. 当前代码状态

### 3.1 已实现

- `app/main.py` FastAPI 入口、lifespan 管 httpx 单例 + SQLite 初始化
- `app/api/deps.py` 跨领域依赖:`get_authenticated_user`(统一认证)/ `get_optional_current_user` / `get_admin_user` / `PUBLIC_PATHS` 公开路径白名单
- `app/core/database.py` SQLite 连接管理(WAL mode + foreign keys) + 5 表 DDL
- `app/core/crypto.py` API Key 加密/解密(Fernet)
- `app/modules/auth/` 注册 / 登录 / me,router 只管 HTTP,service 负责业务编排
- `app/modules/sessions/` 会话 CRUD + `sessions.service` 所有权判断 + M2 LRU/TTL 消息体清理
- `app/modules/messages/` 消息 CRUD + 单会话滑窗 trim
- `app/modules/chat/` SSE 协议(首帧 session_id / token 事件 / 安全 error 事件 / `[DONE]`)
- `app/modules/ai_providers/` fake + OpenAI-compatible provider;真实模式走 M2 channel 池
- `app/modules/channels/` channel CRUD + 加权随机 + 失败计数 + 临时黑名单 + admin API
- `app/modules/api_keys/` API Key 生成(`sk-`前缀) / 哈希(SHA256) / 验证 / CRUD;管理 API
- `app/core/security.py` JWT 编解码 + Argon2 密码哈希
- `app/core/config.py` `pydantic-settings` 读 .env,包含 M2 channel / LRU 参数
- `app/storage/repos.py` `UserRepo` / `SessionRepo` / `MessageRepo`(全部已切 SQLite)
- `app/static/` 原生 HTML/JS + sidebar 组件 + channels 管理三件套(accounts/keys/usage)

### 3.2 M2/M3 当前边界

- channels 模块已有 `router.py`:`/api/channels/models`(公开) + `/api/admin/channels/*`(管理员)
- channels admin UI 已有三件套:accounts / keys / usage
- `POST /v1/chat/completions` 尚未实现(M4)
- 当前只支持 `provider_type="openai_compat"`;New-API / Anthropic / Gemini 等属于后续 Provider 适配
- channel 配置通过管理后台创建,存储于 SQLite `channels` 表

---

## 4. 数据模型与持久化

**已于 M2.5 切入 SQLite**(aiosqlite),统一 `data/data.db` 单文件,WAL 模式 + 外键级联。不再使用 JSON 文件/内存字典。

| 表 | 持久化 | 外键 | 说明 |
|---|---|---|---|
| `users` | SQLite | — | 用户账号,username UNIQUE,password_hash argon2 |
| `sessions` | SQLite | `user_id → users(id) ON DELETE CASCADE` | 删用户时自动清会话 |
| `messages` | SQLite | `session_id → sessions(id) ON DELETE CASCADE` | 删会话时自动清消息;id AUTOINCREMENT |
| `channels` | SQLite | — | 号池 channel,api_key 经 Fernet 加密存储 |
| `api_keys` | SQLite | `user_id → users(id)` | 用户 API Key,key_hash SHA256 UNIQUE |

时间字段全部存 ISO 8601 字符串(TEXT),读写双向转换。

### 4.1 字段约定

- **Channel**: `id` / `name` / `provider_type`(openai_compat / ...) / `base_url` / `api_key`(加密) / `models[]`(JSON string) / `weight` / `enabled` / 运行时字段(`blacklisted_until` / `success_count` / `failure_count`)
- **User**: `id` / `username` / `password_hash` / `display_name` / `role`(admin / user) / `status`(active / disabled) / `created_at` / `updated_at`
- **Session**: `id` / `user_id` / `title` / `created_at` / `updated_at` / `last_accessed_at`(LRU 用)
- **Message**: `id`(自增) / `session_id` / `role` / `content` / `created_at`
- **ApiKey**: `id` / `user_id` / `key_hash`(SHA256) / `key_masked` / `name` / `models[]` / `quota` / `used_quota` / `status` / `expires_at`

### 4.2 内存压力控制

两道闸(直接从 SQLite 查,不依赖内存加载):

1. **单会话滑窗**:`SESSION_MAX_MESSAGES`(默认 100)条上限,超出 trim 丢最早
2. **总会话 LRU + TTL**:`MAX_ACTIVE_SESSIONS` / `SESSION_IDLE_TTL_MINUTES` 超出按 `last_accessed_at` 淘汰消息体,只留元信息

### 4.3 连接管理

- `app/core/database.py` 模块级单例连接(`get_db()`)
- 启动时 `init_db()`:建表 + `PRAGMA journal_mode=WAL` + `PRAGMA foreign_keys=ON`
- 关闭时 `close_db()`
- 使用参数化查询(`?`占位符),禁止字符串拼接

---

## 5. 调度策略(决策记录)

- **选 channel**:从 `enabled=true` 且 `blacklisted_until <= now` 的池子里**加权随机**
- **失败处理**:
  - 5xx / 429 / 超时 / 连接错误 → 立即拉黑 `CHANNEL_BLACKLIST_SECONDS` 秒(默认 30),从下一个 channel 重试
  - 4xx(401 / 403 / 404)→ 不拉黑(API Key 错误需要人工修),记一次失败计数
- **恢复**:黑名单到期自动恢复,不做主动健康检查(被动健康检查 M5 之后再加)
- **全军覆没**:所有 channel 都失败 → 返回安全错误文案;SSE 内只给浏览器安全 error 事件,不暴露 API Key、Authorization、原始上游响应体

---

## 6. 协作工作流(Trellis 管理)

本项目由 Trellis 管理开发流程。参见 `.trellis/workflow.md` 完整文档。

### 任务流程

```
建任务(task.py create) → 需求讨论(brainstorm) → 配置语境(jsonl) → 激活(task.py start) → 派发子代理实施 → 质量检查 → spec 更新 → 提交 → 归档(task.py archive)
```

### 子代理调度

- **实施阶段**:派发 `trellis-implement` 子代理(自动注入 spec + prd + research)
- **检查阶段**:派发 `trellis-check` 子代理(审查 + 自动修复)
- **研究阶段**:派发 `trellis-research` 子代理(写出到 `research/` 目录)
- 主 session 不直接编辑代码,除非用户明确说 "直接改"/"别派 sub-agent"

### 强约束

- **任何代码修改前，agent 必须先说明：改什么文件、改什么内容、为什么改，等用户回复 "做"/"改"/"ok" 再动手**
- 任何"删除文件 / 改公共接口形状 / 跨模块重组"前必须列清单等确认
- 跨模块只允许"上层 → 下层"导入,反向导入要先讨论
- 一个任务只动一个模块,跨模块重组单独开任务
- lint / typecheck 必须在提交前通过

---

## 7. 安全约束

- `.env` 不进 git,只提交 `.env.example`
- `data/data.db` 整个 data/ .gitignore
- 所有 `/api/*` 路由由 `get_authenticated_user` 统一守卫(路径白名单例外:`/api/auth/status`, `/api/auth/register`, `/api/auth/login`, `/api/channels/models`, `/health`)
- 管理类 API 必须由 `get_admin_user` 依赖守住(chains through `get_authenticated_user`,基于 `role=admin`)
- `/v1/*` 路径预留 API Key 鉴权(当前返回 501)
- 上游 API Key 不向前端透出,存储时经 Fernet 加密
- Channel 响应里 api_key 字段 mask 成 `sk-***xxxx`
- 浏览器前端不直接调上游模型,所有调用走后端代理
- `JWT_SECRET` 启动期校验长度 >= 32,空值直接拒启动
- `API_KEY_ENCRYPTION_KEY` 启动期自动生成(如果缺失),用于 Fernet 加解密

---

## 8. 当前里程碑

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M1** ✅ | 删除 DB / 摘要 / 调用日志,CRUD 改内存版 | 启动不再依赖 MySQL;SSE 聊天 + 登录注册不回归 |
| **M1.5** ✅ | 目录按 `modules/<领域>/` 重组 | 现有功能不回归;依赖单向;`api/` 下只剩 `deps.py` |
| **M2** ✅ | Channel + 加权随机 + failover 黑名单 + LRU/TTL + admin API + admin UI | 管理后台可视化管理 channel |
| **M2.5** ✅ | SQLite 迁移 + 统一认证守卫 `get_authenticated_user` + API Key 模块 | 全量持久化;外键级联;新增路由默认需要认证 |
| **M3** 🔄 | 管理 API + 管理后台 UI(`/static/pages/channels_*/`) | channels 三件套已完成;channels.admin 待完善 |
| **M4** | OpenAI 兼容代理路由 `POST /v1/chat/completions` + Provider 抽象正式落地 | OpenAI SDK 能直接打通 |
| **M5** | 插件系统(plugins 模块 + builtin/echo/calculator/time)+ 前端插件管理页 | 聊天里能触发 echo 插件 |
| **M6** | memory + model_logs + context builder(history + memory,summary 视情况) | 多轮对话能回忆;后台能看调用日志 |
| **M7** | Docker + docker-compose(app + nginx) | `docker-compose up` 一键起 |
| **M8** | pytest 单元 + 集成测试 + GitHub Actions CI | 关键路径覆盖率 ≥ 70% |

---

## 9. 长期蓝图(确认要做,只是不在眼前)

这些是**确定要做**,不是"也许":

- **多 Provider 适配**:Provider 抽象基类 + OpenAI 兼容 + New-API + 直连 Anthropic / Gemini
- **plugins 系统**:OpenAI tool calling 协议 + 内置工具(echo / calculator / time)+ 注册中心 + 沙箱执行
- **memory 模块**:长期记忆,先 json 后 DB,可能引入向量检索(到那步再选型)
- **model_logs 模块**:每次模型调用落表,管理后台看消耗 / 延迟 / 错误率
- **context builder**:history + summary + memory 三段式拼接
- **Docker 部署**:`docker-compose up` 一键起,nginx 反代 + 静态资源直发
- **被动健康检查**:周期性 ping channel,不只是失败拉黑
- **pytest + CI**:GitHub Actions 跑 lint + test

---

## 10. 当前不做的事

本阶段禁止引入:

- 计费 / 配额 / token 倍率 / 虚拟 key 转发(One API 那一套)— 不做
- 完整 RBAC — 只用 admin / user 二态
- SQLAlchemy / Alembic — 当前用 aiosqlite + 原生 SQL,不做 ORM
- Redis / DuckDB / 其他数据库 — SQLite 够用
- Prometheus / OpenTelemetry — M7 之后再说
- WebSocket — SSE 已经够用
- 前端框架(React / Vue)— 保持原生 HTML/JS
- LangChain / LangGraph / 多 Agent — 不引入框架,要做就裸写
- 向量数据库 — memory 模块上线时再评估
- Docker — M7 才做
- pytest — M8 才做

目标始终是:

```
先做出可理解、可运行、可维护的号池中转平台,避免任何过早抽象
```
