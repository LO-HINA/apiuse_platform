# API Pool Test Platform

OpenAI 兼容协议的简化号池中转平台,用于测试和验证多上游 API Key 的可用性、调度策略与故障转移行为。

灵感来源 One API / New API,但只做 **号池调度 + 测试可视化**,不做计费 / 配额 / 虚拟 key 转发。当前是个人学习项目,但按企业级目录约定写——领域分层、依赖单向、模块自治。

## 当前进度

**M2 后端核心已进入(2026-06-08)

| 里程碑 | 状态 | 内容 |
|---|---|---|
| M1 | 完成 | 删除 DB / 摘要 / 调用日志,CRUD 改内存 + json |
| **M1.5** | **完成** | 目录按领域重组,`api/` 下只剩 `deps.py` |
| **M2** | **后端核心已落地** | Channel 号池 + 加权随机 + failover + LRU/TTL |
| M3 | 未开始 | 管理 API + 后台 UI |
| M4 | 未开始 | OpenAI 兼容代理路由 `POST /v1/chat/completions` |
| M5 | 未开始 | 插件系统(echo / calculator / time) |
| M6 | 未开始 | memory + model_logs + context builder |
| M7 / M8 | 未开始 | Docker / pytest + CI |

完整里程碑见 `CLAUDE.md` § 8。

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
│   │   ├── channels/                 # 号池 JSON + 调度 + 黑名单 ✅
│   │   ├── plugins/                  # 插件系统(M5,目录已占位)
│   │   ├── context/                  # 上下文构造(M6)
│   │   ├── memory/                   # 长期记忆(M6)
│   │   └── model_logs/               # 调用日志(M6)
│   └── static/
│       └── pages/
│           └── chat/                 # 聊天测试页(index.html / script.js / style.css)
├── data/                             # 持久化目录(.gitignore)
│   ├── users.json                    # 用户表
│   └── channels.json                 # 号池配置(本机敏感文件,不提交)
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

编辑 `.env`,**至少必须配置 `JWT_SECRET`**(空值或 < 32 字符会被启动期校验拒绝):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把输出粘到 `JWT_SECRET=...`。

`USE_FAKE_AI=true` 时聊天走本地模拟,无需上游。切 `false` 时走 M2 channel 池,需要创建 `data/channels.json`:

```json
[
  {
    "id": "openai-main",
    "name": "OpenAI Main",
    "provider_type": "openai_compat",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-请替换成本机真实key",
    "models": ["gpt-4o-mini"],
    "weight": 10,
    "enabled": true
  },
  {
    "id": "backup-proxy",
    "name": "Backup Proxy",
    "provider_type": "openai_compat",
    "base_url": "https://your-proxy.example.com/v1",
    "api_key": "sk-请替换成本机真实key",
    "models": ["gpt-4o-mini"],
    "weight": 3,
    "enabled": true
  }
]
```

`data/` 已被 `.gitignore` 忽略,不要提交真实 API Key。`AI_BASE_URL` / `AI_API_KEY` 只保留为旧配置占位,M2 真实调用不再依赖单一上游。

### 4. 启动服务

```powershell
uvicorn app.main:app --reload
```

- 聊天页:<http://127.0.0.1:8000/>
- OpenAPI 文档:<http://127.0.0.1:8000/docs>
- 健康检查:<http://127.0.0.1:8000/health>




