# DEVELOPMENT — 开发指南

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-20 |

> 本文档为 ResearchMind 的开发环境搭建、项目结构、编码约定与常用命令参考。架构设计见 [ARCHITECTURE.md](ARCHITECTURE.md)，基础设施复用策略见 [INFRASTRUCTURE_REUSE.md](INFRASTRUCTURE_REUSE.md)。

---

## 1. 环境要求

| 组件 | 版本 | 说明 |
|:---|:---|:---|
| Python | 3.12+ | 后端 |
| MySQL | 8.0+ | 关系数据库 |
| Redis | 7.0+ | Celery Broker + Result Backend |

> **Windows 注意事项**：Celery Worker 在 Windows 上需使用 `--pool=solo`（Windows 不支持 fork）。Redis 在 Windows 上通过 WSL 或 Memurai 运行。

---

## 2. 项目结构（计划）

> 最后更新：2026-06-20（同步自 FRONTEND.md 及 ARCHITECTURE.md 设计）

```
ResearchMind/
├── README.md
├── CLAUDE.md                       # Claude Code 项目指引
├── .gitignore
│
├── docs/                           # 公用设计文档
│   ├── PRD.md                      # 产品需求文档
│   ├── ARCHITECTURE.md             # 架构设计文档
│   ├── RESEARCH_PIPELINE.md        # 研究管线的深度设计
│   ├── API.md                      # 接口文档
│   ├── DATABASE.md                 # 数据库设计文档
│   ├── INFRASTRUCTURE_REUSE.md     # 基础设施复用清单（后端）
│   ├── INFRASTRUCTURE_REUSE_FRONTEND.md  # 基础设施复用清单（前端）
│   ├── FRONTEND.md                 # 前端交互文档
│   ├── UIDESIGN.md                 # UI 设计规范
│   ├── ROADMAP.md                  # 开发排期
│   ├── DEVELOPMENT.md              # 开发指南（本文件）
│   ├── CHANGELOG.md                # 变更日志
│   └── decisions/                  # ADR 架构决策记录
│
├── .env                            # 环境变量（在根目录下，不提交）
├── .env.example                    # 环境变量模板
├── requirements.txt
├── alembic.ini
├── alembic/                        # 数据库迁移脚本
│   ├── env.py
│   └── versions/
├── pytest.ini
│
├── app/                            # 后端源码（根目录即为后端，无 backend/ 目录）
│   ├── main.py                     # FastAPI 入口
│   ├── config.py                   # 配置单例（pydantic-settings）
│   ├── dependencies.py             # 依赖注入（get_db, current_user）
│   │
│   ├── api/                        # 路由层（仅参数校验 + 调用 service）
│   │   ├── __init__.py
│   │   ├── auth.py                 # 认证接口（注册/登录/refresh/logout/修改密码）
│   │   └── research.py             # 研究任务接口（创建/列表/详情/取消/重试/SSE 流）
│   │
│   ├── services/                   # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── auth_service.py         # 注册/登录/refresh token 逻辑
│   │   ├── research_service.py     # 研究任务 CRUD + 状态管理
│   │   └── pipeline_orchestrator.py # Pipeline 编排器（7 阶段调度 + SSE 事件发射）
│   │
│   ├── models/                     # SQLAlchemy ORM 模型
│   │   ├── __init__.py
│   │   ├── user.py                 # 用户表
│   │   ├── research_task.py        # 研究任务表
│   │   ├── execution_context.py    # 执行上下文表（断点续跑）
│   │   ├── evidence.py             # 证据表（Evidence Graph）
│   │   ├── trace.py                # 链路追踪表
│   │   └── refresh_token.py        # Refresh Token 表
│   │
│   ├── schemas/                    # Pydantic 请求/响应 Schema
│   │   ├── __init__.py
│   │   ├── auth.py                 # RegisterRequest / LoginRequest / TokenResponse
│   │   ├── research.py             # ResearchCreate / ResearchResponse / TaskListResponse
│   │   ├── evidence.py             # EvidenceItem / EvidenceGraphResponse
│   │   └── trace.py                # TraceResponse / TraceSummary
│   │
│   ├── core/                       # 基础设施
│   │   ├── __init__.py
│   │   ├── database.py             # 数据库连接 & async session
│   │   ├── exceptions.py           # AppException 异常体系（code/message/detail）
│   │   ├── llm.py                  # DeepSeek SDK 封装（OpenAI 兼容）
│   │   ├── security.py             # JWT 生成/验证 + 密码哈希
│   │   ├── permissions.py          # require_task_accessible / require_admin
│   │   ├── cost_tracker.py         # Token 用量与成本追踪（中英文自适应算法）
│   │   ├── redis_client.py         # Redis 客户端（Celery broker + result backend）
│   │   ├── logging_config.py       # 日志配置
│   │   └── utils.py                # 共享工具函数
│   │
│   ├── pipeline/                   # Pipeline 各阶段实现
│   │   ├── __init__.py
│   │   ├── planner.py              # Phase 1: 研究主题拆解（子问题生成）
│   │   ├── searcher.py             # Phase 2: Tavily API 多源搜索
│   │   ├── fetcher.py              # Phase 3: 网页内容抓取与清洗
│   │   ├── reranker.py             # Phase 4: BM25 + LLM 两级重排序
│   │   ├── synthesizer.py          # Phase 5: LLM 跨源综合与章节生成
│   │   ├── evidence_graph.py       # Phase 6: 证据图谱构建（来源-主张-章节关联）
│   │   └── renderer.py             # Phase 7: Markdown 报告渲染 + 引用锚点
│   │
│   ├── tasks/                      # Celery 任务定义
│   │   ├── __init__.py
│   │   ├── celery_app.py           # Celery 配置（DB/Redis 集成）
│   │   └── research_tasks.py       # 研究任务异步执行（Worker 入口）
│   │
│   └── middleware/                 # 中间件
│       ├── __init__.py
│       ├── auth_middleware.py       # JWT 验证中间件
│       ├── rate_limit_middleware.py # 限流中间件
│       └── request_id_middleware.py # 请求 ID 追踪中间件
│
├── frontend/
│   ├── docs/                       # 前端设计文档
│   │   ├── FRONTEND.md             # 前端交互文档
│   │   └── UIDESIGN.md            # UI 设计规范
│   │
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js
│   ├── vitest.config.js
│   │
│   ├── src/
│   │   ├── App.vue                 # 根组件（路由感知布局切换）
│   │   ├── main.js                 # Vue 应用入口
│   │   │
│   │   ├── views/                  # 页面
│   │   │   ├── LoginPage.vue       # 登录/注册页
│   │   │   ├── ResearchPage.vue    # 研究页（核心）：创建态/运行态/完成态三态切换
│   │   │   ├── HistoryPage.vue     # 研究任务历史列表（分页、按状态筛选）
│   │   │   └── admin/
│   │   │       ├── AdminStats.vue      # 系统统计（数据总览 + ECharts 图表）
│   │   │       ├── AdminTaskList.vue   # 全部研究任务（跨用户），可查看/删除/取消
│   │   │       ├── AdminTaskDetail.vue # 任务详情（Pipeline 阶段 + Steps + Trace）
│   │   │       ├── AdminUserList.vue   # 用户管理列表（筛选+操作菜单）
│   │   │       └── AdminUserDetail.vue # 用户详情（统计+快捷操作）
│   │   │
│   │   ├── components/
│   │   │   ├── research/           # 研究页核心组件
│   │   │   │   ├── ResearchForm.vue     # 创建态：研究主题输入 + 研究类型卡片 + 高级选项
│   │   │   │   ├── PipelineProgress.vue # 运行态：7 阶段 Pipeline 进度条（Planning→Render）
│   │   │   │   ├── StepLogStream.vue    # 运行态：Step 实时 SSE 日志流（自动滚动）
│   │   │   │   ├── ReportViewer.vue     # 完成态：Markdown 报告正文渲染 + [来源N] 引用锚点
│   │   │   │   ├── ChapterNav.vue       # 完成态：章节导航侧栏（当前章节高亮 + 滚动联动）
│   │   │   │   ├── EvidenceGraph.vue    # 完成态：证据图谱面板（来源-主张-章节关联）
│   │   │   │   └── TraceSummary.vue     # 完成态：Pipeline 各阶段耗时摘要
│   │   │   ├── layout/             # 布局组件
│   │   │   │   ├── AppLayout.vue   # 布局容器（Sidebar + 主内容）
│   │   │   │   ├── Sidebar.vue     # 侧边栏（历史任务列表 + 导航）
│   │   │   │   └── AdminLayout.vue # Admin 布局（独立 Admin 侧边栏 + 内容区）
│   │   │   └── charts/             # ECharts 图表组件
│   │   │       ├── TrendChart.vue  # 任务量趋势图（折线图）
│   │   │       ├── LatencyChart.vue # 任务耗时分布图（柱状图）
│   │   │       └── TokenChart.vue  # Token 消耗图（堆叠柱状图）
│   │   │
│   │   ├── stores/                 # Pinia 状态管理
│   │   │   ├── auth.js             # 认证状态（user/token/isAdmin/login/logout/refresh）
│   │   │   ├── task.js             # 任务状态（taskList/current/sseStatus/progress/create/cancel/retry）
│   │   │   └── report.js           # 报告状态（report/loading/sections/evidence/trace）
│   │   │
│   │   ├── api/                    # HTTP 请求封装
│   │   │   ├── index.js            # Axios 实例 + 请求/响应拦截器（Token 附加/401 自动刷新）
│   │   │   ├── auth.js             # register / login / refresh / logout / changePassword
│   │   │   ├── research.js         # 研究任务 CRUD + SSE 连接管理
│   │   │   ├── admin.js            # Admin 统计/任务管理/用户管理 API
│   │   │   └── trace.js            # 链路追踪 API
│   │   │
│   │   ├── router/
│   │   │   └── index.js            # Vue Router + 路由守卫（认证/Admin 三级）
│   │   │
│   │   ├── composables/
│   │   │   └── useECharts.js       # ECharts 动态加载 composable（响应式 resize + dispose）
│   │   │
│   │   ├── constants/
│   │   │   └── charts.js           # ECharts 图表颜色/样式/tooltip 常量
│   │   │
│   │   ├── styles/
│   │   │   └── global.css          # 全局样式（Design Token --rm-* CSS 变量）
│   │   │
│   │   └── utils/
│   │       ├── sse.js              # SSE 事件解析（fetch + ReadableStream，17 种事件类型）
│   │       ├── markdown.js         # Markdown 渲染（markdown-it + highlight.js + [来源N] 锚点）
│   │       └── format.js           # 共享格式化工具（formatDateTime/formatFileSize/formatRelativeTime）
│   │
│   └── tests/                      # 前端测试（vitest + @vue/test-utils）
│       ├── setup.js                # 全局 Mock & 配置
│       ├── LoginPage.test.js
│       ├── ResearchPage.test.js
│       ├── HistoryPage.test.js
│       ├── ResearchForm.test.js
│       ├── PipelineProgress.test.js
│       ├── StepLogStream.test.js
│       ├── ReportViewer.test.js
│       ├── EvidenceGraph.test.js
│       ├── AppLayout.test.js
│       ├── AdminLayout.test.js
│       ├── Sidebar.test.js
│       ├── AdminStats.test.js
│       ├── AdminTaskList.test.js
│       ├── AdminTaskDetail.test.js
│       ├── AdminUserList.test.js
│       ├── AdminUserDetail.test.js
│       ├── Charts.test.js
│       ├── useECharts.test.js
│       ├── markdown.test.js
│       ├── sse.test.js
│       ├── authStore.test.js       # Auth Store 测试（JWT 解析/刷新/并发守卫）
│       ├── taskStore.test.js       # Task Store 测试（SSE 状态机/任务管理/进度追踪）
│       └── reportStore.test.js     # Report Store 测试（报告加载/章节导航/Evidence 联动）
│
├── tests/                          # 后端测试（pytest + httpx）
│   ├── __init__.py
│   ├── conftest.py                 # 共享 fixtures（mock DB, auth headers, async client）
│   ├── unit/                       # 单元测试（快速、模拟）
│   │   ├── api/                    # API 层测试
│   │   ├── services/               # Service 层测试
│   │   ├── pipeline/               # Pipeline 各阶段测试
│   │   └── core/                   # 核心模块测试
│   ├── integration/                # 集成测试
│   └── regression/                 # 回归测试（端到端）
│
├── Dockerfile
├── docker-compose.yml
└── nginx.conf
```

---

## 3. 快速开始

### 3.1 后端

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate    # Linux/macOS

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（见 §4）
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY、MYSQL_PASSWORD 等

# 数据库迁移
alembic upgrade head

# 启动 FastAPI
uvicorn app.main:app --reload --port 8000

# 启动 Celery Worker（另一终端）
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
# Windows: celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

### 3.2 Docker Compose（完整部署）

```bash
docker-compose up -d
# 启动 mysql + redis + backend + celery 四个服务
```

---

## 4. 环境变量

`.env` 文件位于**项目根目录**下。所有配置通过 `app/config.py` 的 `settings` 单例读取，**禁止硬编码**。

```bash
# ── 应用 ──
APP_NAME=ResearchMind
DEBUG=true
ENV=development

# ── MySQL ──
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=researchmind
MYSQL_PASSWORD=<your-password>
MYSQL_DATABASE=researchmind

# ── Redis / Celery ──
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# ── LLM (DeepSeek) ──
LLM_API_KEY=<your-deepseek-api-key>
LLM_MODEL=deepseek-v4-pro          # MVP 单一模型
# LLM_PLANNING_MODEL=deepseek-v4-pro # [v2] 分级模型
# LLM_FLASH_MODEL=deepseek-v4-flash   # [v2] 轻量模型

# ── 搜索 ──
TAVILY_API_KEY=<your-tavily-api-key>

# ── JWT ──
JWT_SECRET_KEY=<generate-random-secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
REFRESH_TOKEN_SECRET_KEY=<generate-another-random-secret>

# ── CORS ──
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

---

## 5. 依赖

### 5.1 后端（requirements.txt）

```
# Web 框架
fastapi==0.115.*
uvicorn[standard]==0.34.*

# 数据库
sqlalchemy[asyncio]==2.0.*
aiomysql==0.2.*
alembic==1.14.*

# 异步任务
celery==5.4.*
redis==5.2.*

# LLM
openai==1.*

# HTTP 客户端
httpx==0.28.*

# 数据校验
pydantic==2.10.*
pydantic-settings==2.7.*

# 认证
python-jose[cryptography]==3.3.*
passlib[bcrypt]==1.7.*

# 工具
python-multipart==0.0.18
python-dotenv==1.0.*

# 测试
pytest==8.3.*
pytest-asyncio==0.24.*
pytest-cov==6.0.*
httpx==0.28.*
```

---

## 6. 数据库与时区配置

### 6.1 MySQL 连接时区

所有 DATETIME 列存储 UTC 时间。连接串强制 `time_zone='+00:00'`：

```python
# app/config.py
@property
def database_url(self) -> str:
    return (
        f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
        f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        f"?charset=utf8mb4&init_command=SET time_zone='%2B00:00'"
    )
```

### 6.2 四层 UTC 统一

| 层级 | 机制 |
|:---|:---|
| MySQL | 连接串 `SET time_zone='+00:00'` + 服务器 `default_time_zone='+00:00'` |
| 后端 (ORM) | SQLAlchemy `DateTime(timezone=True)` 确保读写带 UTC tzinfo |
| API | Pydantic 将 aware datetime 序列化为 ISO 8601 `+00:00` |
| 前端 | `new Date(isoString)` 自动转换为本地时区显示 |

### 6.3 代码中时间处理

```python
from datetime import datetime, timezone

# ✅ 正确：始终使用 timezone-aware
now = datetime.now(timezone.utc)

# ❌ 禁止：naive datetime
now = datetime.utcnow()  # 已弃用且不带 tzinfo
```

详见 [ARCHITECTURE.md §6](ARCHITECTURE.md#6-部署与运维) 和 [DATABASE.md §0](DATABASE.md#0-时区约定)。

---

## 7. 常用命令速查

| 操作 | 命令 |
|:---|:---|
| 启动后端 | `uvicorn app.main:app --reload --port 8000` |
| 启动 Celery Worker | `celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4` |
| Windows Celery | `celery -A app.tasks.celery_app worker --loglevel=info --pool=solo` |
| 数据库迁移 | `alembic upgrade head` |
| 生成迁移脚本 | `alembic revision --autogenerate -m "描述"` |
| 运行测试 | `pytest tests/ -v` |
| 测试 + 覆盖率 | `pytest tests/ -v --cov=app --cov-report=html` |
| Docker 启动 | `docker-compose up -d` |
| Docker 停止 | `docker-compose down` |

---

## 8. 编码约定

### 8.1 文档驱动开发（最高优先级）

所有代码实现必须严格遵循对应的设计文档。**若文档缺失或存在冲突，必须先与开发者确认；严禁自行猜测或绕过约束。**

| 场景 | 权威文档 |
|:---|:---|
| 后端接口 | [API.md](API.md) — 路由、响应格式 `{code,message,detail}`、错误码、SSE 事件结构、权限矩阵 |
| 数据库 | [DATABASE.md](DATABASE.md) — 表结构、索引、外键级联策略 |
| Pipeline 各阶段 | [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md) — Prompt 模板、算法策略、SSE 事件映射 |
| 架构决策 | [ARCHITECTURE.md](ARCHITECTURE.md) — 技术选型、状态机、权限模型、非功能需求 |
| 产品需求 | [PRD.md](PRD.md) — MVP 范围、任务类型、验收标准 |
| 排期 | [ROADMAP.md](ROADMAP.md) — 阶段顺序、任务依赖 |
| 基础设施复用 | [INFRASTRUCTURE_REUSE.md](INFRASTRUCTURE_REUSE.md) — 从 DocMind 复用的模块及适配说明 |

> **实现偏差必须上报**：当代码因技术限制无法完全对齐设计文档时，**必须**在 [CHANGELOG.md](CHANGELOG.md) 中记录偏差及原因，并在对应设计文档中标注 `[Deviation]` 标记。**禁止**反向修改文档来迁就代码。

### 8.2 文档归属矩阵

每种技术事实只在权威文档中定义一次；其他文档通过交叉引用链接，**禁止复制**。

```markdown
> **权威定义**：[API.md §5.3](API.md#53-研究执行错误e3xxx)
```

### 8.3 后端约定

#### 导入路径

- **必须**使用 `from app.xxx` 绝对路径；**禁止** `from ..core` 相对导入。
- **禁止**在函数或方法内部使用局部导入。例外：① 解决循环导入；② 可选依赖（体积大或可能未安装的库）。标准库和 `requirements.txt` 中的依赖必须始终在文件顶部导入。

#### API / Service 分离

- `api/` 仅处理**参数校验 + 调用 service**；所有业务逻辑必须位于 `services/`。
- 所有请求/响应**必须**定义 Pydantic Schema；禁止裸用 `dict`。

#### 异步 IO

- 所有 IO 操作使用 `async/await`。
- 数据库会话通过 `get_db()` 依赖注入。

#### 配置

- 环境变量必须从 `config.py` 的 `settings` 单例中读取；**禁止**硬编码。

#### 数据库

- 所有 `*_id` 字段必须声明 `sa.ForeignKey(...)`，级联策略与 [DATABASE.md](DATABASE.md) 保持一致。
- `default=0` 等 Python 默认值必须同步 `server_default=sa.text('0')`。
- 所有 Schema 变更必须通过 **Alembic** 迁移脚本；禁止手动修改数据库。

#### 幂等性与 CAS

- **所有 Step 执行必须幂等**：执行前检查 `status`，若已是终态则跳过。
- **所有 Task 状态更新必须 CAS**：`UPDATE ... WHERE status = 'old_value'`。
- **Evidence 只追加不覆盖**：`INSERT` only，重试不会删除已有 evidence。
- **Task-level Retry 创建新 Execution Context**：不修改原始失败的 context。

#### 异常体系

- 业务异常需继承 `AppException`（`code`/`message`/`detail` 三元组）。
- `code` 字段**统一为字符串类型**：成功时为 `"0"`，错误时为 `"E2001"` 等；前端不要做整数类型判断。
- 全局注册 `RequestValidationError`（映射至 422/E9003）和 `Exception`（映射至 500/E9001）的异常处理器。
- 错误码体系：E1xxx 认证、E2xxx 任务、E3xxx 执行（含 `recoverable`/`retry_after_ms`/`last_checkpoint`）、E9xxx 系统。

详见 [API.md §5](API.md#5-错误码体系) 和 [ARCHITECTURE.md §5.5](ARCHITECTURE.md#55-failure-model失败分类学)。

#### 时区规范

- **禁止**使用 `datetime.utcnow()`；必须统一使用 `datetime.now(timezone.utc)`。
- ORM 中使用 `DateTime(timezone=True)`。

详见 §6.2 和 [DATABASE.md §0](DATABASE.md#0-时区约定)。

#### JWT 解析

- 从 payload 提取字段时必须进行 `KeyError/ValueError` 防护，返回 401 而非 500。

#### Celery 任务

- 优先使用 `db.get(Model, pk)` 而非 `select().where()`。
- 每个阶段在重载记录后检查业务状态（如 `CANCELING`），以支持并发中断。
- Service 层在调用 `task.delay()` 分发异步任务前，必须显式 `await db.commit()`——`get_db()` 的自动提交发生在路由返回之后，与 Celery Worker 消费之间存在竞态窗口。
- 当 service 函数与 Celery task 同名时，task 导入必须加 `_task` 后缀别名。

#### 权限分离

权限分为两层，**禁止混用**：

| 层级 | 语义 | 函数 |
|:---|:---|:---|
| Task Access | "用户能否访问这个研究任务" | `require_task_accessible` |
| System Permissions | "用户是否有系统级管理权限" | `require_admin` |

详见 [ARCHITECTURE.md §4](ARCHITECTURE.md#4-权限模型)。

#### Token 估算

- 必须使用**中英文自适应算法**（中文占比 > 30% 时比率为 1.5，否则为 4.0）；**禁止**使用全局固定比率。

---

## 9. 相关文档

- [架构设计文档](ARCHITECTURE.md)
- [基础设施复用清单](INFRASTRUCTURE_REUSE.md)
- [产品需求文档](PRD.md)
- [接口文档](API.md)
- [数据库设计文档](DATABASE.md)
- [研究管线设计文档](RESEARCH_PIPELINE.md)
- [开发排期](ROADMAP.md)
- [变更日志](CHANGELOG.md)
