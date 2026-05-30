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
│   └── context.py                # request_id ContextVar
│
├── storage/                      # 通用存储原子能力,不属于任何领域
│   ├── repos.py                  # SessionRepo / MessageRepo / UserRepo
│   └── json_store.py             # 原子写盘工具(后续 channels/plugins 复用)
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
│   ├── channels/                 # 号池(M2)
│   │   ├── router.py             # /api/admin/channels/*
│   │   ├── service.py
│   │   ├── crud.py
│   │   ├── scheduler.py          # 加权随机 + failover + 黑名单
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
    │   ├── admin/                # 号池管理后台(M3)
    │   └── plugins/              # 插件管理(M5)
    └── shared/                   # 公用 JS / CSS
```

**依赖方向单向**(上层可调下层,反之禁止):

```
modules/*           → storage / core
modules/chat        → modules/sessions, modules/messages, modules/ai_providers, modules/context
modules/channels    → modules/ai_providers
modules/ai_providers → modules/channels (调度时拿 channel)
api/deps            → modules/auth (拿 user)
```

横向跨模块只允许通过 `service.py` 暴露的函数,**不允许跨模块 import crud / models**。

---

## 3. 当前代码状态

### 3.1 保留(已实现)

- `app/main.py` FastAPI 入口、lifespan 管 httpx 单例 + `users.json` 启动加载
- `app/api/chat.py` SSE 协议(首帧 session_id / token 事件 / error 事件 / `[DONE]`)
- `app/api/auth.py` + `app/api/deps.py` JWT 认证 + Argon2 + `get_current_user` / `get_optional_current_user` / `get_admin_user`
- `app/core/security.py` JWT 编解码 + 密码哈希
- `app/core/config.py` `pydantic-settings` 读 .env
- `app/services/ai_service.py` `dispatch_chat` / `dispatch_chat_stream` 的 fake/real 双实现
- `app/storage/repos.py` `SessionRepo` / `MessageRepo` / `UserRepo`(json 持久化)
- `app/static/` 原生 HTML/JS + EventSource 聊天页

### 3.2 当前结构 → 目标结构(M1.5 重组映射)

| 现在 | 目标 |
|---|---|
| `app/api/auth.py` | `app/modules/auth/router.py` |
| `app/api/chat.py`(混了 sessions / chat 两类路由) | 拆分到 `modules/sessions/router.py` + `modules/chat/router.py` |
| `app/services/chat_service.py` | `modules/chat/service.py` |
| `app/services/ai_service.py` | `modules/ai_providers/service.py` + `fake.py` + `openai_compat.py` |
| `app/crud/{session,message,user}.py` | `modules/{sessions,messages,auth}/crud.py` |
| `app/schemas/{auth,chat}.py` | 各模块自带 `schemas.py` |
| `app/storage/repos.py` | 保留(原子存储能力,不属任何领域) |

### 3.3 还没实现

见 § 8 里程碑。

---

## 4. 数据模型与持久化

| 数据 | 持久化 | 重启行为 | 切 DB 时机 |
|---|---|---|---|
| Channel(号池条目) | `data/channels.json` | 保留 | 短期不切 |
| User | `data/users.json` | 保留 | 短期不切 |
| Plugin 配置 | `data/plugins.json` | 保留 | 短期不切 |
| Session(会话元信息) | 仅内存 | 清空 | M6 上线时随 memory/model_logs 一起评估 |
| Message | 仅内存 | 清空 | 同上 |
| Memory(长期记忆) | 内存 + json(M6) | 保留 | 规模大或要做向量检索时切 DB |
| Model Call Log | 内存环形缓冲 + json 周期落盘(M6) | 部分丢失 | 上量时切 DB |

### 4.1 字段约定

- **Channel**: `id` / `name` / `provider_type`(openai_compat / newapi / ...) / `base_url` / `api_key` / `models[]` / `weight` / `enabled` / 运行时字段(`blacklisted_until` / `success_count` / `failure_count`)
- **User**: `id` / `username` / `password_hash` / `role`(admin / user) / `created_at`
- **Session**: `id` / `user_id`(可空 = 匿名) / `title` / `created_at` / `updated_at` / `last_accessed_at`(LRU 用)
- **Message**: `id`(自增) / `session_id` / `role` / `content` / `created_at`

### 4.2 内存压力控制(全内存路线的核心)

号池本身不存对话,内存压力来自前端聊天 UI 的 sessions/messages。两道闸:

1. **单会话滑窗**:`SESSION_MAX_MESSAGES`(默认 100)条上限,超出 trim 丢最早(已实现)
2. **总会话 LRU + TTL**(M2 引入):
   - `MAX_ACTIVE_SESSIONS`(默认 1000)超出按 `last_accessed_at` 淘汰整个会话的消息体,只留元信息
   - `SESSION_IDLE_TTL_MINUTES`(默认 60)闲置超时同样清消息体留元信息
   - 用户翻列表能看到 session 元信息,但点进去消息为空 → 测试平台可接受

**当前不做 summary 压缩**:本平台目标是验证号池调度,不是对话连贯性产品,trim + LRU 已够;summary 要多调一次 AI 反而增加成本。等 M6 memory 模块落地时再统一回看。

### 4.3 长期切 DB 的边界

短期(M1 - M5)全 json + 内存。出现以下信号之一**才考虑**为该模块切回 SQLAlchemy + Alembic,**只切受影响的模块**,不全家桶迁移:

- `model_logs` 单文件 > 50MB(查询变慢)
- `memory` 需要按 user 维度做相似度检索(json 撑不住)
- `channels` 数量 > 50 + 多管理员并发写(json 锁竞争)

当前 `crud.*` 函数签名就是为这一刻铺路:实现可换,接口不动。

---

## 5. 调度策略(决策记录)

- **选 channel**:从 `enabled=true` 且 `blacklisted_until <= now` 的池子里**加权随机**
- **失败处理**:
  - 5xx / 超时 / 连接错误 → 立即拉黑 `CHANNEL_BLACKLIST_SECONDS` 秒(默认 30),从下一个 channel 重试
  - 4xx(401 / 403 / 404)→ 不拉黑(API Key 错误需要人工修),记一次失败计数
- **恢复**:黑名单到期自动恢复,不做主动健康检查(被动健康检查 M5 之后再加)
- **全军覆没**:所有 channel 都失败 → 返回 503,响应体附带当前黑名单状态供前端展示

---

## 6. 协作工作流(强约束)

任何修改前必须先:

```
Explain → Plan → Wait Confirm → Build → Build Summary
```

未经确认禁止直接修改。

**新增硬规则**:

- 任何"删除文件 / 改公共接口形状 / 跨模块重组"前必须列清单等确认
- 跨模块只允许"上层 → 下层"导入,反向导入要先讨论
- 一个任务只动一个模块,跨模块重组单独开任务

---

## 7. 安全约束

- `.env` 不进 git,只提交 `.env.example`
- `data/` 整个 .gitignore:含上游 API Key (`channels.json`) 和密码哈希 (`users.json`)
- 管理类 API 必须由 `get_admin_user` 依赖守住(基于 `role=admin`)
- 上游 API Key 不向前端透出,响应里一律 mask 成 `sk-***xxxx`
- 浏览器前端不直接调上游模型,所有调用走后端代理
- `JWT_SECRET` 启动期校验长度 >= 32,空值直接拒启动
- 插件执行(M5)默认沙箱:超时 + 不允许任意文件系统访问

---

## 8. 当前里程碑

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M1** ✅ | 删除 DB / 摘要 / 调用日志,CRUD 改内存版 | 启动不再依赖 MySQL;SSE 聊天 + 登录注册不回归 |
| **M1.5** | 目录按 `modules/<领域>/` 重组 | 现有功能不回归;依赖单向;`api/` 下只剩 `deps.py` |
| **M2** | Channel + `channels.json` + 加权随机 + failover 黑名单 + LRU/TTL 内存控制 | 配 2+ channel 流量分发;故意写错 key 自动切;空闲会话被清 |
| **M3** | 管理 API + 管理后台 UI(`/static/pages/admin/`) | 管理员可视化增删改 channel + 看统计面板 |
| **M4** | OpenAI 兼容代理路由 `POST /v1/chat/completions` + Provider 抽象正式落地(`openai_compat.py` / `newapi.py`) | OpenAI SDK 能直接打通 |
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

本阶段(M1 - M5)禁止引入:

- 任何数据库(SQLite / Redis / DuckDB)— 等明确撞到 § 4.3 边界再切
- 计费 / 配额 / token 倍率 / 虚拟 key 转发(One API 那一套)— 不做
- 完整 RBAC — 只用 admin / user 二态
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
