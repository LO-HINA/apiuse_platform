# API Pool Test Platform

OpenAI 兼容协议的简化号池中转平台,用于测试和验证多上游 API Key 的可用性、调度策略与故障转移行为。

灵感来源 One API / New API,但只做 **号池调度 + 测试可视化**,不做计费 / 配额 / 虚拟 key 转发。当前是个人学习项目,但按企业级目录约定写——领域分层、依赖单向、模块自治。

## 当前进度

**M1.5 已完成(2026-05-29)**:目录按 `modules/<领域>/` 重组,依赖单向,功能与 M1 对齐。

| 里程碑 | 状态 | 内容 |
|---|---|---|
| M1 | 完成 | 删除 DB / 摘要 / 调用日志,CRUD 改内存 + json |
| **M1.5** | **完成** | 目录按领域重组,`api/` 下只剩 `deps.py` |
| M2 | 下一步 | Channel 号池 + 加权随机 + failover + LRU/TTL |
| M3 | 未开始 | 管理 API + 后台 UI |
| M4 | 未开始 | OpenAI 兼容代理路由 `POST /v1/chat/completions` |
| M5 | 未开始 | 插件系统(echo / calculator / time) |
| M6 | 未开始 | memory + model_logs + context builder |
| M7 / M8 | 未开始 | Docker / pytest + CI |

完整里程碑见 `CLAUDE.md` § 8。

## 已实现

- FastAPI 入口 + lifespan(httpx 单例 + `users.json` 启动加载)
- JWT 认证(Argon2 + `get_current_user` / `get_optional_current_user` / `get_admin_user`)
- 会话 CRUD + 消息存取 + 滑窗 trim(`SESSION_MAX_MESSAGES`)
- SSE 流式聊天(首帧 session_id / token 事件 / error 事件 / `[DONE]`)
- AI Provider 抽象骨架(fake + openai_compat)
- 全局异常处理 + RequestID 中间件 + 结构化日志
- 原生 HTML/JS 前端 + EventSource 接收流式 token

## 技术栈

- Python 3.10+
- FastAPI + uvicorn
- pydantic / pydantic-settings
- httpx(异步上游调用)
- argon2-cffi + PyJWT(鉴权)
- 原生 HTML / CSS / JavaScript

## 项目结构

```
apiuse_platform/
├── app/
│   ├── main.py                       # 入口、lifespan、路由注册
│   ├── api/
│   │   └── deps.py                   # 跨领域依赖:get_current_user / get_admin_user
│   ├── core/                         # 横切关注点
│   │   ├── config.py                 # settings + .env + SecretStr
│   │   ├── logging.py                # 日志格式 + request_id 注入
│   │   ├── middleware.py             # RequestIDMiddleware
│   │   ├── exceptions.py             # 全局异常处理
│   │   ├── security.py               # JWT + Argon2
│   │   └── context.py                # request_id ContextVar
│   ├── storage/                      # 通用存储原子能力
│   │   └── repos.py                  # SessionRepo / MessageRepo / UserRepo
│   ├── modules/                      # 领域模块,每个目录自治
│   │   ├── auth/                     # 注册 / 登录 / me ✅
│   │   ├── sessions/                 # 会话元信息 CRUD ✅
│   │   ├── messages/                 # 消息存取 + 滑窗 trim ✅
│   │   ├── chat/                     # SSE 编排 ✅
│   │   ├── ai_providers/             # Provider 抽象(fake + openai_compat)✅
│   │   ├── channels/                 # 号池(M2,目录已占位)
│   │   ├── plugins/                  # 插件系统(M5,目录已占位)
│   │   ├── context/                  # 上下文构造(M6)
│   │   ├── memory/                   # 长期记忆(M6)
│   │   └── model_logs/               # 调用日志(M6)
│   └── static/
│       └── pages/
│           └── chat/                 # 聊天测试页(index.html / script.js / style.css)
├── data/                             # 持久化目录(.gitignore)
│   └── users.json                    # 用户表
├── .env.example
├── CLAUDE.md                         # 项目协作规范 + 里程碑
├── README.md
└── requirements.txt
```

依赖方向单向(上层 → 下层,反向禁止):

```
modules/*           → storage / core
modules/chat        → modules/sessions, modules/messages, modules/ai_providers
modules/channels    → modules/ai_providers           (M2 起)
modules/ai_providers → modules/channels              (调度时拿 channel,M2 起)
api/deps            → modules/auth
```

跨模块只能走 `service.py` 暴露的函数,**不允许跨模块 import crud / models**。

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

编辑 `.env`,**至少必须配置 `JWT_SECRET`**(空值或 < 32 字符会被启动期校验拒绝):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把输出粘到 `JWT_SECRET=...`。

`USE_FAKE_AI=true` 时聊天走本地模拟,无需上游;切 `false` 才需要真 `AI_BASE_URL` / `AI_API_KEY`。

### 4. 启动服务

```powershell
uvicorn app.main:app --reload
```

- 聊天页:<http://127.0.0.1:8000/>
- OpenAPI 文档:<http://127.0.0.1:8000/docs>
- 健康检查:<http://127.0.0.1:8000/health>

## 接口列表(当前版本)

### 鉴权 `/api/auth`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/register` | 注册,成功直接返回 token |
| POST | `/api/auth/login` | 用户名 + 密码登录,失败统一 401 |
| GET | `/api/auth/me` | 当前登录用户信息 |

### 会话 `/api/sessions`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/sessions` | 列出当前用户最近 50 条会话 |
| POST | `/api/sessions` | 新建会话(匿名也允许,user_id=None) |
| GET | `/api/sessions/{session_id}` | 获取会话详情 + 消息列表 |
| DELETE | `/api/sessions/{session_id}` | 幂等删除,不归你 / 不存在都返回 success=False |

### 聊天 `/api/chat`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/chat/stream?message=...&session_id=...` | SSE 流式聊天(核心) |

匿名(不带 Authorization)也能用 `/api/chat/stream`,但 session 不绑定 user_id。

## SSE 流式协议

```
data: {"session_id": "..."}      ← 第一帧,前端拿到后挂上
data: {"token": "你"}
data: {"token": "好"}
data: [DONE]
```

异常时:

```
data: {"error": "上游连接失败"}
data: [DONE]
```

客户端断开会被 `request.is_disconnected()` 检出,服务端不会再写 `[DONE]`(连接已没)。

## 数据持久化

| 数据 | 存储 | 重启行为 |
|---|---|---|
| User | `data/users.json` | 保留 |
| Channel(M2) | `data/channels.json` | 保留 |
| Session | 仅内存 | 清空 |
| Message | 仅内存 | 清空 |

切 DB 触发条件、内存压力控制(滑窗 + LRU + TTL)详见 `CLAUDE.md` § 4。

## 安全约束

- `.env` / `data/` 不进 git(含 API Key 和密码哈希)
- `JWT_SECRET` 启动期校验长度 ≥ 32,空值或过短直接拒启动
- 上游 API Key 不向前端透出,响应里 mask 成 `sk-***xxxx`
- 浏览器前端不直接调上游模型,所有调用走后端代理
- 管理类 API 由 `get_admin_user` 守住(基于 `role=admin`)

## 协作工作流

任何修改前必须:

```
Explain → Plan → Wait Confirm → Build → Build Summary
```

删文件 / 改公共接口 / 跨模块重组前必须列清单等确认。详见 `CLAUDE.md` § 6。

## 当前不做的事

M1 - M5 阶段不引入:数据库、计费 / 配额、完整 RBAC、Prometheus、WebSocket、前端框架、LangChain、向量数据库、Docker、pytest。详见 `CLAUDE.md` § 10。
