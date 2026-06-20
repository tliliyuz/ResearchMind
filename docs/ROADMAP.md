# ROADMAP — 开发排期

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-20 |

> 本文档是 **开发排期、Phase 顺序、任务依赖关系** 的唯一真理源。相关定义禁止在其他文档中重复，应使用交叉引用链接到本文档对应章节。

> **编号规范**
>
> 本章子节编号格式为 `{章节号}.{序号}`，全部两级，序号连续。每个 Phase 内按「功能 → 测试 → 🚫 推迟项 → 索引」固定顺序排列。
>
> 每个子节标题标注 `[角色]` 标签，角色包括：后端 / 前端 / 数据库 / 测试 / 文档 / 运维 / 体验完善 / 管理后台 / 基础设施 / 高级功能。
>
> 🚫 推迟项统一编号，放在 `[测试]` 之后、`[索引]` 之前。
>
> ✅ **前端设计文档已完成**（FRONTEND.md / UIDESIGN.md / INFRASTRUCTURE_REUSE_FRONTEND.md），前端任务已纳入各 Phase 排期。


---

## 1. 总体时间线

**预计总工期**：5-7 周（180-250 小时，前后端并行开发）

```
Phase 1          Phase 2               Phase 3               Phase 4              Phase 5           Phase 6
骨架搭建          研究任务 + Pipeline     Pipeline 后半段        断点续跑 + 基础设施    打磨上线           迭代优化
+ 认证系统        前半段(Plan→Fetch)     (Rerank→Report)       加固                   + 管理后台        不设时限
3-4天             4-5天                 4-5天                 3-4天                 4-5天

  ├────────────────┼────────────────────┼────────────────────┼───────────────────┼───────────────┤
Week 1            Week 1-2             Week 2-3              Week 3-4            Week 4-5         Week 5+
[—]              [—]                  [—]                   [—]                 [—]              [—]
```

> **状态标记**：⏳ 待开始 | 🔲 进行中 | ✅ 已完成 | ❌ 已废弃
>
> ResearchMind 当前处于设计阶段，全部任务标记为 ⏳。

---
## 2. Phase 1：骨架搭建 + 认证系统（3-4 天）

**目标**：可运行的后端骨架，数据库表就绪，认证体系可用。

### 2.1 [后端] 项目初始化

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ✅ | 项目脚手架 | FastAPI 入口 `main.py` + `config.py` 配置单例 + 目录结构（api/services/models/schemas/core/pipeline/tasks/middleware） |
| ✅ | 依赖安装 | `requirements.txt`（fastapi / sqlalchemy[asyncio] / aiomysql / alembic / celery / redis / openai / httpx / pydantic / python-jose / passlib / python-dotenv） |
| ✅ | Git 初始化 | `.gitignore` + 分支策略 |
| ✅ | `.env` 配置模板 | `.env.example`：MySQL / Redis / LLM (DeepSeek) / Tavily / JWT / CORS 全部配置项 |

### 2.2 [数据库] 数据库表建表 + 迁移

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ✅ | Alembic 初始化 | `alembic init` + `env.py` 配置（`target_metadata` 指向 ResearchMind Model） |
| ✅ | `users` 表 | `id BIGINT PK` / `username VARCHAR(64) UNIQUE` / `password_hash VARCHAR(256)` / `role ENUM(user,admin)` / `status ENUM(active,disabled)` |
| ✅ | `refresh_tokens` 表 | `id BIGINT PK` / `user_id FK→users` / `token_hash VARCHAR(256)` (SHA-256) / `expires_at` / `revoked_at` / 复合索引 `(user_id, revoked_at, expires_at)` |
| ✅ | `research_tasks` 表 | `id UUID PK` / `user_id FK→users(RESTRICT)` / `topic` / `requirements JSON` / `status ENUM(7态)` / `current_phase ENUM(7阶段)` / `execution_context JSON` / 统计字段 / 错误字段 / 时间字段 |
| ✅ | `research_steps` 表 | `id UUID PK` / `task_id FK→tasks(CASCADE)` / `step_type ENUM(7类)` / `parent_step_id FK→steps(SET NULL)` / `status ENUM(6态)` / `input/output JSON` / 重试/错误/性能字段 |
| ✅ | `research_sources` 表 | `id INT PK AUTO_INCREMENT` / `task_id FK→tasks(CASCADE)` / `url` / `title` / `domain` / `fetch_status` / `UNIQUE(task_id, url(255))` |
| ✅ | `evidence_items` 表 | `id INT PK AUTO_INCREMENT` / `task_id FK→tasks(CASCADE)` / `source_id FK→sources(CASCADE)` / `step_id FK→steps(SET NULL)` / `content TEXT` / `relevance_score` / `used_in_sections JSON` |
| ✅ | `report_sections` 表 | `id INT PK AUTO_INCREMENT` / `task_id FK→tasks(CASCADE)` / `parent_section_id FK→sections(CASCADE)` / `heading` / `content MEDIUMTEXT` / `sort_order` |
| ✅ | `section_evidence` 表 | `section_id FK→sections(CASCADE)` / `evidence_id FK→evidence(CASCADE)` / `PRIMARY KEY (section_id, evidence_id)` |
| ✅ | 初始迁移脚本 | `alembic revision --autogenerate -m "init"` + `alembic upgrade head` |

> **表结构权威定义**：[DATABASE.md §2](DATABASE.md#2-表结构)。外键策略详见 [DATABASE.md §4](DATABASE.md#4-外键策略)。

### 2.3 [后端] 基础设施复用落地

> 依据 [INFRASTRUCTURE_REUSE.md](INFRASTRUCTURE_REUSE.md)，从 DocMind 复制以下基础设施模块并适配。

| 状态 | 任务 | 说明 | 复用方式 |
|:---|:---|:---|:---|
| ✅ | 异常体系 | `app/core/exceptions.py` — `AppException` 基类 + `code`/`message`/`detail` 三元组，31 个异常类 | 直接复制模板，替换错误码枚举（E1xxx/E2xxx/E3xxx/E9xxx），detail 扩展为 `dict\|str` |
| ✅ | LLM 客户端 | `app/core/llm.py` — DeepSeek SDK 封装（流式/非流式调用、错误分类、分级重试） | 直接复制，改模型默认值为 `deepseek-v4-pro`，新增 timeout/rate_limit/auth_error 重试策略 |
| ✅ | Token 估算 | `app/core/token_counter.py` — 中英文自适应算法（中文>30%→1.5，否则 4.0） | 直接复制函数，零改动 |
| ✅ | JWT 安全模块 | `app/core/security.py` — `hash_password` / `verify_password` / `create_access_token` / `decode_access_token` / `create_refresh_token` | 直接复制，微调 `users` 表字段映射 |
| ✅ | JWT 认证中间件 | `app/middleware/auth_middleware.py` — ASGI 中间件，验证 Bearer Token，写入 `request.state` | 直接复制，错误码 E5004→E1004，detail 改为结构化 JSON |
| ✅ | 依赖注入 | `app/dependencies.py` — `get_db`（异步会话 yield + commit/rollback）/ `get_current_user`（request.state + DB 状态校验）/ `require_admin` | 直接复制，`get_db` 使用 `async_session_factory` 创建会话 |
| ✅ | 权限中间件 | `app/core/permissions.py` — `require_task_accessible` / `require_task_owner` / `require_admin` 三层分离 | 直接复制模式，替换 Task 级权限检查逻辑 |
| ✅ | 时区策略 | `app/models/_types.py`（`UTCDateTime`）+ `app/core/database.py`（`SET time_zone='+00:00'`）+ 四层 UTC 统一 | 直接复制 `UTCDateTime` 与四层 UTC 策略（Phase 1 脚手架已提前完成） |
| ✅ | SSE 流式框架 | `app/core/sse.py` — 手动 `StreamingResponse` + 15s 心跳注释帧 | 保留 SSE 传输层框架，Phase 2-3 替换全部事件类型 |
| ✅ | Trace 追踪器 | `app/core/trace_recorder.py` — Per-stage 计时 + JSON 字段 + Pipeline 七阶段 | 直接复制类结构，改阶段名称为 Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render |
| ✅ | BM25 核心（轻量版） | `app/pipeline/bm25.py` — `BM25Okapi` + `jieba.lcut` 核心，72 行纯内存计算 | 不复用 DocMind 的 ~686 行版（含三级缓存），重写轻量版 |
| ✅ | 结构化日志 | `app/core/logging_config.py` — contextvars（`request_id_var`/`user_id_var`）+ JSONFormatter + RequestIDFilter + `setup_logging()` | 直接复制，零改动 |
| ✅ | Request ID 中间件 | `app/middleware/request_id_middleware.py` — 生成/透传 `X-Request-ID` + 注入 contextvars | 直接复制，零改动 |
| ✅ | Redis 客户端 | `app/core/redis_client.py` — 同步/异步双客户端 + Windows 兼容包装 | 直接复制，零改动（Phase 2 Celery + SSE Bridge 依赖） |
| ✅ | 通用工具 | `app/core/utils.py` — `escape_like()` SQL LIKE 转义 | 直接复制，零改动 |
| ✅ | 限流中间件 | `app/middleware/rate_limit_middleware.py` — Redis 固定窗口计数器 + Lua 原子脚本 | 直接复制，接口组映射调整：`chat`→`research`，移除 `upload`，保留 `login`/`default`（Phase 4 激活，代码提前就位） |

### 2.4 [后端] 认证系统

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ✅ | Auth Pydantic Schema | `RegisterRequest` / `LoginRequest` / `RefreshRequest` / `LogoutRequest` / `ChangePasswordRequest` / `TokenResponse` / `UserResponse` |
| ✅ | Auth Service | `register()` 用户名唯一性检查 + bcrypt 哈希 / `login()` 密码验证 + Token 对生成 / `refresh()` Rotation 刷新（旧 token 立即吊销 + E1009 泄露检测） / `logout()` 吊销当前 refresh_token / `change_password()` 改密后全量吊销 |
| ✅ | Auth API 端点 | `POST /api/auth/register` / `POST /api/auth/login` / `POST /api/auth/refresh` / `POST /api/auth/logout` / `PUT /api/auth/password` |
| ✅ | `current_user` 依赖注入 | JWT Bearer Token 解析 → 查 `users` 表 → 校验 `status=active` → 注入 `User` 对象 |
| ✅ | 全局异常处理器 | `RequestValidationError` → 422/E9003 + `AppException` → 对应 HTTP 码 + `Exception` → 500/E9001 (生产环境屏蔽堆栈) |

> **认证接口详设**：[API.md §2](API.md#2-认证接口)。错误码体系：[API.md §5](API.md#5-错误码表完整)。

### 2.5 [前端] 项目脚手架 + Auth + 布局框架

> **复用策略**：Phase 1 前端约 80% 代码可从 DocMind 直接复用或微调（工程配置 / Auth 体系 / 布局框架 / Design Token 系统），详见 [INFRASTRUCTURE_REUSE_FRONTEND.md](../INFRASTRUCTURE_REUSE_FRONTEND.md)。

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ✅ | 项目脚手架 | `package.json`（Vue 3 + Vite + Pinia + Element Plus + Axios + Font Awesome + markdown-it + highlight.js + Vitest）+ `vite.config.js`（`@/` alias + proxy `/api` → `localhost:8000`）+ `index.html`（title「ResearchMind」）+ 目录结构（`api/` / `stores/` / `router/` / `views/` / `components/` / `utils/` / `styles/`） | — |
| ✅ | Design Token 系统 | `styles/global.css` — `--rm-*` CSS 变量全量定义（品牌色 / 语义色 / 中性色 / 字体 / 间距 / 圆角 / 阴影 / 过渡 / Element Plus 覆盖）。从 DocMind 复制全部变量定义，改前缀 `--dm-` → `--rm-`，移除 `--dm-evidence-highlight-bg` / `--dm-orphan-*` 系列 | UIDESIGN.md §1 |
| ✅ | Axios 实例 + 拦截器 | `api/index.js` — Axios 实例（baseURL + 30s 超时）+ 请求拦截器（附 `Authorization: Bearer <access_token>`）+ 响应拦截器（401+E1003 → `authStore.refresh()` → 重放原请求 + `isRefreshing` 并发防抖 + `scheduleRefresh` 定时器）。从 DocMind 直接复制，Token 过期错误码 E5003→E1003（单行改动） | FRONTEND.md §1.3 |
| ✅ | Auth API 封装 | `api/auth.js` — `login()` / `register()` / `refresh()` / `logout()` / `changePassword()` 五个函数。从 DocMind 直接复制 | FRONTEND.md §3 |
| ✅ | AuthStore (Pinia) | `stores/auth.js` — `user` / `token` / `isAdmin` / `login()` / `logout()` / `refresh()` / `register()`。从 DocMind 直接复制 | FRONTEND.md §1.2 |
| ✅ | 路由骨架 + 守卫 | `router/index.js` — 路由表（§2.1 全部路由）+ 三级路由守卫（公开/需登录/需管理员）。从 DocMind 复制守卫逻辑，替换路由表 | FRONTEND.md §2 |
| ✅ | LoginPage | `views/LoginPage.vue` — 品牌区（Logo + 标题「ResearchMind」+ 副标题「可审计的结构化研究引擎」）+ Tab 切换（登录/注册）+ 表单（用户名+密码，图标前缀）+ 错误提示 + 提交按钮 loading + 底部互转链接。从 DocMind 直接复制，替换品牌区文案 | FRONTEND.md §3 |
| ✅ | AppLayout + Sidebar | `components/layout/AppLayout.vue` + `Sidebar.vue` — 双栏布局（Sidebar 260px/64px 收起 + 主内容区）+ 侧边栏（Logo + 新建研究按钮 + 历史任务列表 + 导航链接 + 用户栏头像/用户名 + 用户菜单卡片 + 展开/收起切换动画）。从 DocMind 复制布局骨架，替换侧边栏导航项（知识库→历史任务） | FRONTEND.md §4.6 |
| ✅ | 用户菜单卡片 + 修改密码对话框 | Sidebar 内嵌用户菜单（修改密码 / 管理后台[admin] / 退出登录）+ `el-dialog` 修改密码弹窗（420px，旧密码+新密码+确认新密码，含一致性校验）。从 DocMind 直接复制 | FRONTEND.md §4.6.4 / §4.7 |
| ✅ | App.vue 根组件 | `<router-view />` + 全局样式引入 | — |

### 2.6 🚫 本阶段不做的

| 推迟项 | 排期 | 原因 |
|:---|:---|:---|
| ResearchPage（创建态/运行态/完成态） | Phase 2-3 | Phase 1 先搭建骨架，核心业务页面在 Phase 2-3 实现 |
| HistoryPage | Phase 2 | 依赖研究任务列表 API（Phase 2 后端） |
| Admin 管理后台 | Phase 5 | 先完成用户侧核心链路 |
| Markdown 渲染器 | Phase 3 | 依赖报告渲染 API（Phase 3 后端） |

### 2.7 [测试] Phase 1 测试

| 状态 | 任务 | 测试类型 | 说明 |
|:---|:---|:---|:---|
| ⏳ | 密码哈希 & JWT 单元测试 | 单元测试 | `hash_password` / `verify_password` / `create_access_token` / `decode_access_token` / `create_refresh_token` |
| ⏳ | Auth Service 单元测试 | 单元测试 | `register`（用户名重复/正常注册/密码<6字符）/ `login`（密码错误/正常登录/用户禁用）/ `refresh`（正常刷新/Rotation/旧token重用→E1009）/ `logout` / `change_password` |
| ⏳ | Auth API 接口测试 | 接口测试 | POST `/api/auth/register` + `/api/auth/login` + `/api/auth/refresh` + `/api/auth/logout` + `PUT /api/auth/password` 正常流程 + 错误码（E1001/E1002/E1006-E1011） |
| ⏳ | Pydantic Schema 校验测试 | 单元测试 | `RegisterRequest` / `LoginRequest` 字段校验（用户名长度/密码长度） |
| ⏳ | 用户模型测试 | 单元测试 | `User` ORM 字段默认值、`relationship` 关联 |
| ⏳ | 异常处理器测试 | 单元测试 | `AppException` → HTTP 状态码映射 / `RequestValidationError` → 422/E9003 / 生产环境堆栈屏蔽 / 未知异常兜底 |
| ⏳ | 基础设施复用模块测试 | 单元测试 | Token 估计算法（中英文自适应）/ LLM 客户端 Mock 调用 / 时区策略（UTC tzinfo 读写一致性） |
| ⏳ | 前端 LoginPage 组件测试 | 组件测试 | 表单渲染 / Tab 切换（登录↔注册）/ 提交按钮 + loading / 错误提示 / 登录成功跳转 / 注册成功切回登录 |
| ⏳ | 前端 AppLayout 组件测试 | 组件测试 | 布局渲染 / Sidebar 存在性 / `<slot />` 内容区 |
| ⏳ | Refresh Token 接口测试 | 接口测试 | Token 刷新 / Rotation（旧 token 失效）/ 主动吊销（logout/改密）/ 泄露检测 E1009 / 过期 E1006 / 禁用用户 E1010 |
| ⏳ | 前端路由守卫测试 | 组件测试 | 未登录重定向到 `/login` / 已登录访问 `/login` 重定向 `/research` / 非 admin 访问 `/admin/*` 重定向 |
| ⏳ | 前端 AuthStore 测试 | 单元测试 | `login()` token 存储 / `logout()` token 清除 / `refresh()` 自动刷新 / `isAdmin` 计算属性 |
| ⏳ | 前端 Token 刷新测试 | 单元+组件 | Axios 拦截器请求/响应 / authStore Token 管理 / `scheduleRefresh` 定时器 / `isRefreshing` 并发防抖 / 刷新失败→跳转 `/login` |

---

## 3. Phase 2：研究任务管理 + Pipeline 前半段（4-5 天）

**目标**：用户可以创建研究任务，系统异步执行 Planning → Search → Fetch，SSE 实时推送进度。

### 3.1 [后端] 研究任务 CRUD + 状态机

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | 研究任务 Pydantic Schema | `ResearchCreateRequest`（`topic`≤500字符 + `requirements` 含 `task_type`/`depth`/`max_sources`/`language`）/ `ResearchTaskResponse`（含 `status`/`current_phase`/`progress`）/ `ResearchTaskListResponse`（分页） | — |
| ⏳ | 研究任务 Service | `create_task()` 校验 + 写入 `research_tasks` + 写入首个 `research_step` (planning, pending) → `commit()` → `task.delay(task_id)` 分发 Celery | 决策 #1 |
| ⏳ | 研究任务列表 API | `GET /api/research` — 当前用户任务列表，分页 + `status` 筛选，按 `created_at DESC` | 决策 #2 |
| ⏳ | 研究任务详情 API | `GET /api/research/{task_id}` — 任务状态 + `current_phase` + `progress` 快照 | 决策 #3 |
| ⏳ | 研究任务删除 API | `DELETE /api/research/{task_id}` — FK CASCADE 级联清理全部派生数据 | 决策 #4 |
| ⏳ | Task 状态机 | `TaskStateResolver` — 所有 Step 终态后统一推导 Task State（FATAL→FAILED / all COMPLETED→COMPLETED / 部分失败→Evidence Threshold 判定） | 决策 #5 |
| ⏳ | `require_task_accessible` 依赖注入 | Task 级权限：owner→允许 / admin→允许（审计）/ 其他→E2002 | 决策 #6 |

### 3.2 [后端] Celery 异步 Pipeline 编排

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Celery App 初始化 | `app/tasks/celery_app.py` — Redis Broker + Result Backend + `research_task` 队列 | — |
| ⏳ | Celery 任务入口 | `app/tasks/research_task.py` — `execute_research(task_id)` 主任务，调用 `PipelineOrchestrator` | — |
| ⏳ | Pipeline Orchestrator | `app/services/pipeline_orchestrator.py` — 阶段调度（Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render）、状态转换、Execution Context 更新、每个 Step 完成后原子写入 checkpoint | 决策 #7 |
| ⏳ | SSE Bridge | `app/pipeline/sse_bridge.py` — Pipeline 事件 → SSE 事件发射器，Redis Pub/Sub 桥接（Celery Worker → FastAPI → SSE Stream） | 决策 #8 |
| ⏳ | Celery 幂等锁 | Redis `SET idempotency_key:{task_id}:{step_type} EX 600 NX`，防止重复入队 | — |

### 3.3 [后端] Planning 阶段

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Planner 实现 | `app/pipeline/planner.py` — LLM 调用（deepseek-v4-pro，`deep_thinking=True`，`temperature=0.3`），注入 `task_type` 策略段落，输出 `SubQuestion[]`（3-5 个）+ `rationale` | 决策 #9 |
| ⏳ | Planner 输出校验 | Pydantic 校验：`sub_questions` 长度 3-5、每个 ≤200 字符、每个 ≥2 实体/关键词。不满足→重试（最多 3 次）→仍失败→E3101 | 决策 #10 |
| ⏳ | `task_type` 策略注入 | `comparison` → 对比矩阵拆解 / `explainer` → 研究方向聚类 / `analysis` → 因果链拆解 | 决策 #11 |
| ⏳ | Planning Step 状态流转 | `step.started` → `step.progress`(含 `sub_questions_generated`) → `step.completed`(含 sub_questions 摘要) + `phase.completed` | — |

> **Planning Prompt 模板**：[RESEARCH_PIPELINE.md §2.3](RESEARCH_PIPELINE.md#23-system-prompt)。`task_type` 策略：[RESEARCH_PIPELINE.md §2.4](RESEARCH_PIPELINE.md#24-task_type-驱动的拆解策略)。

### 3.4 [后端] Search 阶段

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Searcher 实现 | `app/pipeline/searcher.py` — 对每个 SubQuestion 调用 Tavily API（`search_depth=advanced`，`max_results=5`），跨子问题 URL 去重，总结果上限 25 | 决策 #12 |
| ⏳ | Search 失败策略 | 单个子问题 0 结果→SKIPPED / 单次 API 失败→重试 2 次（指数退避 1s/2s）→仍失败→SKIPPED / 全部子问题失败→E3102 | 决策 #13 |
| ⏳ | Search Step 状态流转 | 每个子问题独立 Step：`step.started`(含 `label: "搜索子问题 N: ..."`) → `step.completed`(含 `results_count`) / `step.skipped` | — |

> **Search 策略详设**：[RESEARCH_PIPELINE.md §3](RESEARCH_PIPELINE.md#3-search--多子问题搜索)。

### 3.5 [后端] Fetch 阶段

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Fetcher 实现 | `app/pipeline/fetcher.py` — URL 安全检查（协议白名单 http/https + IP 黑名单 SSRF 防护）→ HTTP GET（timeout=15s，User-Agent: ResearchMind/1.0）→ `trafilatura` 正文提取 → 内容截断（100KB） | 决策 #14 |
| ⏳ | Fetch 失败策略 | 超时→重试 1 次→仍失败→SKIPPED / HTTP 403/404/5xx→不重试直接 SKIPPED / DNS 失败→SKIPPED / 正文为空→SKIPPED | 决策 #15 |
| ⏳ | Fetch Step 状态流转 | 每个 URL 独立 Step：`step.started`(含 `url`) → `step.completed`(含 `content_length`) / `step.skipped`(含 `reason`) | — |

> **Fetch 安全约束**：[RESEARCH_PIPELINE.md §4.4](RESEARCH_PIPELINE.md#44-安全约束)。

### 3.6 [后端] SSE 事件实现

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | 16 种 SSE 事件类型实现 | `task.created` / `task.status.snapshot` / `phase.started` / `phase.completed` / `step.started` / `step.progress` / `step.completed` / `step.failed` / `step.skipped` / `task.progress` / `checkpoint.saved` / `task.warning` / `task.completed` / `task.failed` / `task.canceled` | 决策 #16 |
| ⏳ | `GET /api/research/{task_id}/stream` | SSE 连接端点，`text/event-stream`，15s 心跳 `: ping\n\n`，`seq` 序号有序保证 | 决策 #17 |
| ⏳ | SSE 重连恢复 | 客户端重连时立即推送 `task.status.snapshot`（含当前 Task State / Phase / 所有已完成 Step 摘要 / `progress`），后续恢复正常增量推送 | 决策 #18 |
| ⏳ | `GET /api/research/{task_id}/state` | REST 版状态快照（SSE `task.status.snapshot` 的等价物），供客户端轮询降级 | — |

> **SSE 事件协议**：[API.md §4](API.md#4-sse-事件协议)。事件映射：[RESEARCH_PIPELINE.md §9](RESEARCH_PIPELINE.md#9-pipeline-sse-事件映射)。

### 3.7 [前端] 研究任务创建 + 历史列表 + SSE 框架

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | ResearchPage 创建态 | `views/ResearchPage.vue` — 任务提交表单（`topic` textarea ≤500字符 + 字数统计 + `task_type` 三选一可选卡片 + 高级选项折叠区 `max_sources` slider / `language` select）+ 提交按钮 loading + 3 个快捷示例卡片（点击自动填入）。提交成功→切换到运行态→自动连接 SSE | FRONTEND.md §4.3 |
| ⏳ | 研究类型选择卡片组件 | `components/task/TypeCard.vue` — 三张可选卡片（comparison `fa-balance-scale` / explainer `fa-lightbulb` / analysis `fa-chart-line`），含标题+描述+示例，点击选中高亮（border-teal-600 + bg-teal-50），三选一不可多选 | FRONTEND.md §4.3.3 |
| ⏳ | 快捷示例卡片组件 | `components/task/ExampleCard.vue` — 3 个预设示例，hover teal-500/50 border，点击自动填入 topic + 选中对应 task_type | FRONTEND.md §4.3.5 |
| ⏳ | ResearchPage 状态切换 | 根据 `taskStore.current.status` 切换三种 UI：创建态（`null`）/ 运行态（`pending`/`running`）/ 完成态（`completed`/`partially_completed`/`failed`/`canceled`） | FRONTEND.md §4.2 |
| ⏳ | TaskStore (Pinia) | `stores/task.js` — `taskList` / `current` / `sseStatus`(5态：disconnected/connecting/connected/reconnecting/error) / `progress` / `create()` / `fetchList()` / `fetchDetail()` / `cancel()` / `retry()` / `connectSSE()` / `disconnect()` | FRONTEND.md §1.2 |
| ⏳ | Research API 封装 | `api/research.js` — `createTask()` / `getTaskList()` / `getTaskDetail()` / `deleteTask()` / `cancelTask()` / `retryTask()` / `getReport()` | — |
| ⏳ | SSE 解析工具 | `utils/sse.js` — `fetch` + `ReadableStream` + `response.body.getReader()` 逐块读取 + buffer 按 `\n\n` 分割 + 注释帧跳过（`: ping`）+ `event:`/`data:` 行解析 → 回调 dispatch。从 DocMind 复制解析框架（~80 行），替换全部 17 种事件处理器 | FRONTEND.md §8, INFRASTRUCTURE_REUSE_FRONTEND.md §4.1 |
| ⏳ | 格式化工具 | `utils/format.js` — `formatDate()` / `relativeTime()` / `formatNumber()` / `formatDuration()`（耗时格式化：<1s→ms，≥1s→s，≥60s→m+s）。从 DocMind 直接复制 | INFRASTRUCTURE_REUSE_FRONTEND.md §6.1 |
| ⏳ | HistoryPage | `views/HistoryPage.vue` — 表格（研究主题截取前 40 字符 + tooltip / task_type 标签 / 状态标签 / 来源数 / 证据数 / 创建时间 / 操作[查看/删除]）+ 状态筛选 `el-select` + 主题搜索 `el-input` + 分页 `el-pagination` + 空状态「暂无研究任务」+ 引导按钮 → `/research` | FRONTEND.md §5 |
| ⏳ | History API 封装 | `api/research.js` 中 `getTaskList()` — 分页 + `status` 筛选 + `search` 搜索 + `sort_by=created_at` + `order=desc` | — |
| ⏳ | Sidebar 历史任务列表 | Sidebar 内历史任务区域：调用 `taskStore.fetchList()` → 按时间分组（今天/昨天/近7天/更早）+ 状态图标（✅completed / ⚠️partially_completed / ❌failed / 🚫canceled / ⏳running / 🔄pending）+ 点击加载任务详情 + 高亮当前任务 | FRONTEND.md §4.6.1 |

### 3.8 🚫 本阶段不做的

| 推迟项 | 排期 | 原因 |
|:---|:---|:---|
| 断点续跑（Retry 从 Checkpoint 恢复） | Phase 4 | Phase 2 先跑通主链路，Checkpoint 机制在 Phase 4 与 Execution Context 一起实现 |
| Cancel 中断 | Phase 4 | 依赖 Execution Context + Worker 中断信号机制 |
| Rerank / Synthesis / Evidence Graph / Render | Phase 3 | Phase 2 聚焦 Pipeline 前半段 + SSE 框架 |
| 管理后台 | Phase 5 | 先完成用户侧核心链路 |
| ResearchPage 运行态（Pipeline 进度可视化） | Phase 3 | 依赖 Phase 3 后端全链路跑通 + 完整 SSE 事件流 |
| ResearchPage 完成态（报告查看） | Phase 3 | 依赖 Phase 3 后端 Report Render |
| `requirements` 扩展字段（`focus_areas`/`exclude_domains`/`time_range`） | v1.5 | MVP 仅支持核心 4 字段 |
| 搜索降级后端（SearXNG） | v1.5 | MVP 仅 Tavily |

### 3.9 [测试] Phase 2 测试

| 状态 | 任务 | 测试类型 | 说明 |
|:---|:---|:---|:---|
| ⏳ | 研究任务 CRUD API 接口测试 | 接口测试 | POST `/api/research` 正常创建 + topic 超长(E2005) + task_type 非法(E2006) + depth 非法(E2007) + requirements 缺失(E2008)；GET 列表（分页+状态筛选）；GET 详情（E2001/E2002）；DELETE（级联清理验证） |
| ⏳ | TaskStateResolver 测试 | 单元测试 | FATAL failure → FAILED / all COMPLETED → COMPLETED / partial with sufficient evidence → PARTIALLY_COMPLETED / partial with insufficient → E3103 / all SKIPPED → FAILED |
| ⏳ | Planner 单元测试 | 单元测试 | LLM 调用 Mock：正常拆解（3-5 SubQuestions）/ 输出校验失败重试 / 3 次重试耗尽→E3101 / task_type 策略注入验证（3 种 × Prompt 含策略段落） |
| ⏳ | Searcher 单元测试 | 单元测试 | Tavily API Mock：正常搜索 / 单子问题 0 结果→SKIPPED / API 失败重试→恢复 / 重试耗尽→SKIPPED / 全失败→E3102 / 跨子问题 URL 去重 / 总结果>25 截断 |
| ⏳ | Fetcher 单元测试 | 单元测试 | HTTP Mock：正常抓取+正文提取 / 超时重试→恢复 / 403→直接 SKIPPED / DNS 失败→SKIPPED / SSRF 防护（内网 IP 拒绝）/ 正文为空→SKIPPED |
| ⏳ | SSE 事件流测试 | 单元测试 | `StreamingResponse` 事件序列 / 16 种事件 type 格式校验 / 15s 心跳帧 / `seq` 递增 / 重连 snapshot 数据结构 |
| ⏳ | Celery 幂等锁测试 | 单元测试 | Redis `SET NX` 获取锁 / 已存在拒绝 / TTL 过期后重新获取 / 阶段完成后释放 |
| ⏳ | Pipeline 端到端集成测试（前半段） | 集成测试 | Planning→Search→Fetch 三阶段 Mock 全链路 + SSE 事件序列完整 + Fetch 结果持久化验证 |
| ⏳ | 前端 ResearchPage 创建态组件测试 | 组件测试 | 表单渲染 / topic 字数校验（>500字符拒绝）/ task_type 卡片选中高亮 / 高级选项折叠展开 / 提交 loading / 快捷示例卡片点击填入 / 提交成功切换到运行态 |
| ⏳ | 前端 TypeCard 组件测试 | 组件测试 | 三卡渲染 / 点击选中（border-teal-600 + bg-teal-50）/ 三选一互斥 / 再次点击取消 |
| ⏳ | 前端 HistoryPage 组件测试 | 组件测试 | 表格渲染 / 状态筛选 / 搜索防抖 / 分页 / 空状态 + 引导按钮 / 点击行加载任务 / 删除确认→行移除→空页回退 |
| ⏳ | 前端 SSE 解析工具测试 | 单元测试 | `sse.js` 各 event 类型解析 / 注释帧跳过 / buffer 分割 / 异常格式容错 / 多行 data 拼接 |
| ⏳ | 前端 TaskStore 测试 | 单元测试 | `create()` → `current` 更新 → SSE 自动连接 / `fetchList()` 分页 / `cancel()` → SSE 断开 / `sseStatus` 5 态流转 |

---

## 4. Phase 3：Pipeline 后半段 — 证据处理与报告生成（4-5 天）

**目标**：Rerank → Synthesis → Evidence Graph Build → Report Render 全链路跑通，产出结构化研究报告 JSON。

### 4.1 [后端] Rerank 阶段

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | BM25 粗筛（Stage 1） | `app/pipeline/reranker.py` — FetchedDoc[] 按 `\n\n` 段落切分（≤2000字符/段）→ jieba 分词 → BM25Okapi 对每个 SubQuestion 评分 → 每文档取 top-3 segments → 最多 45 候选 | 决策 #19 |
| ⏳ | LLM Rerank 精排（Stage 2） | DeepSeek API 调用：注入 `task_type` 加权维度（comparison→属性对齐度 / explainer→观点新颖度 / analysis→因果关联度），0-10 评分，输出 `Evidence[]`（top-K，K=min(max_sources, 候选数)） | 决策 #20 |
| ⏳ | Rerank Prompt 模板 | 相关性（40%）+ 信息量（30%）+ 权威性（15%）+ `task_type_dimension`（15%）四维评分 | 决策 #21 |
| ⏳ | Rerank 失败策略 | BM25 候选为空→E3105 / LLM Rerank 失败→重试 2 次→仍失败→E3105 / Evidence 数量<3→质量警告不阻断 | — |

> **Rerank 二段式架构**：[RESEARCH_PIPELINE.md §5](RESEARCH_PIPELINE.md#5-rerank--证据粗筛精排)。

### 4.2 [后端] Synthesis 阶段

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Synthesizer 实现 | `app/pipeline/synthesizer.py` — deepseek-v4-pro（`deep_thinking=True`，`temperature=0.3`，`max_tokens=5000`）：观点聚类 + 共识识别 + 冲突发现 + 信息缺口 | 决策 #22 |
| ⏳ | Synthesis Prompt 模板 | Evidence[] 按 `relevance_score` 降序排列，单条截断至 1500 字符，输出 `clusters[]` / `conflicts[]` / `knowledge_gaps[]` / `overall_assessment` | 决策 #23 |
| ⏳ | Synthesis 失败策略 | LLM 失败→重试 3 次→仍失败→E3104 (`recoverable=true`) / 输出 JSON 无效→重试（计入次数） / conflicts 为 null→不阻断 | — |

> **Synthesis Prompt**：[RESEARCH_PIPELINE.md §6.2](RESEARCH_PIPELINE.md#62-system-prompt)。

### 4.3 [后端] Evidence Graph Build

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Evidence Graph Builder | `app/pipeline/evidence_graph.py` — 纯程序化步骤（不调用 LLM）：导入 Evidence[] → 导入 SynthesisNotes.clusters → 写回 items[].cluster_theme + consensus_level → 导入 conflicts → 导入 knowledge_gaps → 聚合 sources[] → 按 relevance_score 降序重排 items[] | 决策 #24 |
| ⏳ | Evidence Graph 持久化 | 写入 `evidence_items` 表（`INSERT` only，幂等追加）+ `research_sources` 表 + 写回 `items[].used_in_sections`（Report Render 阶段填充） | — |
| ⏳ | Evidence Graph 失败策略 | 纯数据组装→失败说明上游数据结构问题→E3106 (`recoverable=false`) | — |

> **Evidence Graph 数据模型**：[RESEARCH_PIPELINE.md §7.3](RESEARCH_PIPELINE.md#73-数据模型)。

### 4.4 [后端] Report Render

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Renderer 实现 | `app/pipeline/renderer.py` — 按 `task_type` 选择模板（comparison_v1 / explainer_v1 / analysis_v1）→ deepseek-v4-pro（`deep_thinking=False`，`temperature=0.5`，`max_tokens=8000`）→ 渲染 Markdown 报告 + `[来源N]` 引用锚点 | 决策 #25 |
| ⏳ | 模板选择 | `comparison` → 概述→简介→对比矩阵→逐维度分析→总结 / `explainer` → 背景→按研究方向章节→争议与前沿→总结 / `analysis` → 现状→威胁分析→影响推演→应对策略→时间线 | 决策 #26 |
| ⏳ | 引用锚点后处理 | 正则提取 Section 中所有 `[来源N]` → 去重+排序 → 填充 `section.sources[]` → 写入 `section_evidence` 关联表（M:N）→ 写入 `report_sections` 表 | 决策 #27 |
| ⏳ | Report GET API | `GET /api/research/{task_id}/report` — 返回完整 Report JSON（`report.sections[]` + `evidence_graph` + `trace`） | — |
| ⏳ | Render 失败策略 | LLM 失败→重试 1 次→仍失败→E3107 (`recoverable=true`，可复用 Evidence Graph 重渲) / Section 数量<预期→不阻断 / 引用提取失败→标记 `citation_issues` | — |

> **Report Render 详设**：[RESEARCH_PIPELINE.md §8](RESEARCH_PIPELINE.md#8-report-render--报告渲染)。Report JSON 结构：[API.md §3.3](API.md#33-结果获取)。

### 4.5 [后端] Cancel 基础实现

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | Cancel API | `POST /api/research/{task_id}/cancel` — 仅 `pending`/`running` 可取消，设置 `status=canceled`，Worker 下一 Step 前检查并停止 |
| ⏳ | Cancel 状态校验 | 已终态（completed/failed/partially_completed/canceled）→E2003 |

### 4.6 [后端] 成本追踪

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | Cost Tracker | `app/core/cost_tracker.py` — 每 Step 完成时从 DeepSeek API `usage` 对象提取 `input_tokens`/`output_tokens` → 写入 `research_steps` |
| ⏳ | Task 级成本聚合 | `task.trace.total_tokens` + `task.trace.total_cost_usd` + `task.trace.breakdown`（按 Phase 分拆） |

> **成本追踪**：[RESEARCH_PIPELINE.md §11](RESEARCH_PIPELINE.md#11-成本追踪与-token-预算)。

### 4.7 [前端] 运行态进度可视化 + 完成态报告查看

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | ResearchPage 运行态 — Pipeline 进度条 | `components/task/PipelineProgress.vue` — 七阶段横向进度条（Planning→Search→Fetch→Rerank→Synthesis→Evidence Graph→Render），每阶段圆形节点（32px，3态：done teal-600 ✅ / current blue-600 脉冲动画 / pending slate-800），渐变进度条（teal→blue），阶段间箭头连接线 | FRONTEND.md §4.4.2, UIDESIGN.md §4.9 |
| ⏳ | ResearchPage 运行态 — 运行态头部 | 顶部状态栏：当前任务标题 + 状态标签（running 蓝色脉冲）+ 当前阶段 + 已用时计时器（mono 字体，`formatDuration`）+ 取消按钮（danger，`ElMessageBox.confirm` 二次确认） | FRONTEND.md §4.4.1 |
| ⏳ | ResearchPage 运行态 — Step 实时日志 | `components/task/StepLog.vue` — 可滚动日志面板（slate-950 暗色背景，rounded-2xl，shadow-2xl），SSE 事件驱动的日志条目实时追加（带时间戳 + 图标颜色编码 + 自动滚动到底部 + 手动上滚时 sticky「↓ 最新」按钮） | FRONTEND.md §4.4.3, UIDESIGN.md §4.10 |
| ⏳ | SSE 事件 → UI 状态映射 | `stores/task.js` 内 SSE 事件处理：`task.*` → 切换 UI 状态 / `phase.*` → 更新 PipelineProgress / `step.*` → 追加 StepLog 条目 / `task.completed` → 关闭 SSE → 自动调 `getReport()` → 切换到完成态 / `task.failed` → 切换到失败视图 | FRONTEND.md §8.4 |
| ⏳ | SSE 重连机制 | 意外断开→指数退避重连（1s/2s/4s/8s，最多 3 次）→ 重连成功后 `task.status.snapshot` 恢复完整进度 UI。用户主动取消任务时不重连 | FRONTEND.md §8.1 |
| ⏳ | ResearchPage 完成态 — 报告查看 | `views/ResearchPage.vue` 完成态三栏布局：章节导航（240px，`report.sections[].heading` 层级列表 + 当前高亮 + 引用数量 badge）+ 报告正文（Markdown 渲染 + `[来源N]` 可点击锚点）+ Evidence Graph 面板（320px 可折叠） | FRONTEND.md §4.5, UIDESIGN.md §4.12 |
| ⏳ | 章节导航组件 | `components/report/SectionNav.vue` — 固定 240px 左侧栏，`<ul>` 层级列表，当前阅读章节高亮（teal-50 bg + teal-600 left border），点击→报告正文平滑滚动到对应 heading anchor | FRONTEND.md §4.5.2 |
| ⏳ | Markdown 渲染器 | `utils/markdown.js` — `markdown-it` 配置（tables / linkify / 代码块行号）+ `highlight.js` 代码高亮（github-dark 主题）+ 安全 sanitize（`html: false`）+ 自定义 plugin：匹配 `[来源N]` 正则→渲染为 `<a class="citation-link" data-evidence-index="N">[来源N]</a>` + 代码块一键复制按钮。从 DocMind 复制渲染器，新增引用锚点解析 | FRONTEND.md §4.5.3, INFRASTRUCTURE_REUSE_FRONTEND.md §5.1 |
| ⏳ | Evidence Graph 面板 | `components/report/EvidencePanel.vue` — 报告底部可折叠面板，按 `index` 排序展示 Evidence 条目（`[来源N]` 编号 + 标题 + URL + 内容摘要 + `relevance_score` + 所属章节 badge），点击条目→高亮报告正文所有引用该 Evidence 的锚点（`.flash` 动画），按章节筛选，证据内联引用联动 | FRONTEND.md §4.5.4, UIDESIGN.md §4.12 |
| ⏳ | Trace 摘要面板 | `components/report/TracePanel.vue` — 报告底部可折叠面板（默认折叠），七阶段耗时列表（含进度条比例）+ 总耗时汇总 | FRONTEND.md §4.5.5 |
| ⏳ | 失败视图 | ResearchPage 完成态失败视图：居中卡片 + rose 图标 64px + `error_description` + 失败阶段 + `recoverable=true` 时显示「断点续跑」按钮 + `recoverable=false` 时显示「返回新建研究」按钮 | FRONTEND.md §4.5.6 |
| ⏳ | 取消视图 | ResearchPage 完成态取消视图：取消状态 + 已完成阶段摘要 +「返回新建研究」按钮 | FRONTEND.md §4.5.7 |
| ⏳ | ReportStore (Pinia) | `stores/report.js` — `report` / `loading` / `sections` / `evidence` / `trace` / `fetch()`（调 `GET /api/research/{task_id}/report`）/ `selectSection()` / `highlightEvidence()` | FRONTEND.md §1.2 |
| ⏳ | 报告加载态 | 章节导航骨架屏 + 正文区 spinning + Evidence Graph 面板骨架屏 | FRONTEND.md §7.3 |

### 4.8 🚫 本阶段不做的

| 推迟项 | 排期 | 原因 |
|:---|:---|:---|
| 断点续跑（Retry） | Phase 4 | Phase 3 先跑通全链路，Retry 依赖 Execution Context 完整性 |
| Recall 优化（多路检索 + RRF 融合） | v1.5 | MVP 仅 Tavily 单搜索源，v1.5 引入 SearXNG 后激活 RRF |
| 报告模板自定义（用户选择模板） | v2 | MVP 按 `task_type` 自动选择模板 |
| Evidence 置信度审计 | v1.5 | 三层审计（引用存在性→来源一致性→句级回溯）在 v1.5 激活 |
| 多报告模板渲染（同一 Graph→技术版+管理版） | v2 | v1.0 单模板渲染 |

### 4.9 [测试] Phase 3 测试

| 状态 | 任务 | 测试类型 | 说明 |
|:---|:---|:---|:---|
| ⏳ | BM25 粗筛测试 | 单元测试 | BM25Okapi 初始化 / jieba 分词 / 段落级评分 / top-3 选取 / 候选总数上限 45 / 空文档处理 |
| ⏳ | LLM Rerank 测试 | 单元测试 | DeepSeek API Mock：正常评分 / task_type 加权维度验证（3 种）/ 无效 JSON 重试 / 重试耗尽→E3105 / 分数范围 0-10 校验 |
| ⏳ | Synthesis 单元测试 | 单元测试 | DeepSeek API Mock：观点聚类 / 共识识别 / 冲突检测 / 信息缺口 / 无效 JSON 重试 / 重试耗尽→E3104 |
| ⏳ | Evidence Graph Build 测试 | 单元测试 | 数据导入完整性 / items 排序 / cluster 写回 / sources 聚合 / 空输入处理 / E3106 触发条件 |
| ⏳ | Report Render 测试 | 单元测试 | 模板选择（3 种 task_type）/ LLM 渲染 Mock / `[来源N]` 正则提取 / `sources[]` 去重排序 / 引用缺失标记 / E3107 |
| ⏳ | Report API 接口测试 | 接口测试 | `GET /api/research/{task_id}/report` 完整 JSON 结构校验（`report.sections[]` + `evidence_graph` + `trace`）+ E2001/E2002/E2003 |
| ⏳ | Cancel API 接口测试 | 接口测试 | `POST /api/research/{task_id}/cancel` 正常取消 + E2003（已终态）+ E2001/E2002 |
| ⏳ | 成本追踪测试 | 单元测试 | DeepSeek `usage` 对象解析 / Step 级 token 写入 / Task 级成本聚合 / `total_cost_usd` 计算 |
| ⏳ | Pipeline 端到端集成测试（全链路） | 集成测试 | 全 7 阶段 Mock 跑通（Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render）+ SSE 事件序列完整 + Report 产出验证 |
| ⏳ | 人工报告质量评估（第 1 轮） | 人工评估 | 3 task_type × 3 主题 = 9 题，4 维度评分（结构完整性/引用准确性/综合质量/可读性），建立基线 |
| ⏳ | 离线 Pipeline 评估 | 检索评估 | Search Recall / Fetch 成功率 / Rerank 相关性 量化指标脚本 |
| ⏳ | 前端 PipelineProgress 组件测试 | 组件测试 | 7 阶段节点渲染 / done/current/pending 三种视觉状态 / 蓝色脉冲动画 current 态 / 渐变进度条百分比 / 阶段间箭头连线 |
| ⏳ | 前端 StepLog 组件测试 | 组件测试 | SSE 事件→日志条目追加 / 图标颜色编码（✅蓝/⚠️黄/❌红/⏭️灰）/ 时间戳格式 / 自动滚动到底部 / 手动上滚 sticky「↓ 最新」按钮 |
| ⏳ | 前端 Markdown 渲染器测试 | 单元测试 | markdown-it 渲染 / 代码块高亮 / XSS 过滤 / `[来源N]` 锚点解析为 `<a>` 标签 / 代码块复制按钮 |
| ⏳ | 前端 SectionNav 组件测试 | 组件测试 | 章节层级列表渲染 / 当前章节高亮 / 点击→正文滚动 / 引用数量 badge |
| ⏳ | 前端 EvidencePanel 组件测试 | 组件测试 | Evidence 条目按 index 排序 / 信息展示完整性 / 点击条目→锚点高亮 `.flash` 动画 / 按章节筛选 / 折叠展开 |
| ⏳ | 前端 ResearchPage 状态切换集成测试 | 组件测试 | 创建态→提交→运行态→SSE `task.completed`→完成态完整流程 + 失败态 + 取消态 |
| ⏳ | 前端 SSE 重连测试 | 组件测试 | 模拟断连→自动重连→`task.status.snapshot` 恢复进度 UI / 重试耗尽→error 态 / 用户取消→不重连 |

### 4.10 [索引] 关键决策索引

| # | 决策 | 文档位置 |
|:---|:---|:---|
| 1 | 创建任务 → `commit()` → `task.delay()` 时序（避免竞态窗口） | ARCHITECTURE.md §3.3 |
| 2 | 任务列表：仅当前用户，按 `created_at DESC`，分页+status 筛选 | API.md §3.1 |
| 3 | 任务详情：`progress` 从 `execution_context.progress` 提取，前端不直接访问 `execution_context` | API.md §3.1 |
| 4 | 任务删除：FK CASCADE 级联清理全部派生数据 | DATABASE.md §4 |
| 5 | TaskStateResolver：禁止 Task 自身直接写入状态，统一由 Resolver 推导 | ARCHITECTURE.md §3.7 |
| 6 | 权限两层分离：`require_task_accessible`（资源归属）+ `require_admin`（系统角色） | ARCHITECTURE.md §4 |
| 7 | Pipeline Orchestrator 负责阶段调度 + Execution Context 原子更新 | ARCHITECTURE.md §3.3 |
| 8 | SSE Bridge：Redis Pub/Sub 桥接 Celery Worker ↔ FastAPI ↔ SSE Stream | RESEARCH_PIPELINE.md §9 |
| 9 | Planning：deepseek-v4-pro + `deep_thinking=True` + `temperature=0.3` | RESEARCH_PIPELINE.md §2.5 |
| 10 | Planner 输出校验：3-5 SubQuestions + ≤200 字符 + ≥2 实体 → 3 次重试 | RESEARCH_PIPELINE.md §2.6 |
| 11 | `task_type` 策略注入：Planning Prompt 运行时注入对应策略段落 | RESEARCH_PIPELINE.md §2.4 |
| 12 | Search：Tavily `advanced` + 5 results/sub_question + 去重后上限 25 | RESEARCH_PIPELINE.md §3.2 |
| 13 | Search 失败：单个 SKIPPED（不致命）/ 全部失败→E3102（致命） | RESEARCH_PIPELINE.md §3.4 |
| 14 | Fetch 安全：协议白名单 + IP 黑名单 SSRF 防护 + 15s 超时 | RESEARCH_PIPELINE.md §4.4 |
| 15 | Fetch 失败：403/404/DNS 不重试直接 SKIPPED / 超时重试 1 次 | RESEARCH_PIPELINE.md §4.5 |
| 16 | SSE 16 种事件类型：task.* / phase.* / step.* / checkpoint | API.md §4.1 |
| 17 | SSE 实现：手动 `StreamingResponse`（非 sse-starlette）+ 15s 心跳 | API.md §4 |
| 18 | SSE 重连恢复：`task.status.snapshot` 立即推送完整状态快照 | API.md §4.2 |
| 19 | BM25 Stage 1：纯内存计算 ~50ms，零 API 成本，45 候选上限 | RESEARCH_PIPELINE.md §5.3 |
| 20 | LLM Rerank Stage 2：DeepSeek API 打分 + `task_type` 加权维度 | RESEARCH_PIPELINE.md §5.4 |
| 21 | Rerank Prompt：四维评分（相关性 40% + 信息量 30% + 权威性 15% + task_type 维度 15%） | RESEARCH_PIPELINE.md §5.4 |
| 22 | Synthesis：deepseek-v4-pro + `deep_thinking=True` + `temperature=0.3` | RESEARCH_PIPELINE.md §6.4 |
| 23 | Synthesis 输入截断：最多 `max_sources` 条 + 单条 ≤1500 字符 | RESEARCH_PIPELINE.md §6.3 |
| 24 | Evidence Graph Build：纯程序化，不调用 LLM——核心认知资产不受 LLM 随机性影响 | RESEARCH_PIPELINE.md §7 |
| 25 | Render：`deep_thinking=False` + `temperature=0.5`，报告质量靠模板约束 | RESEARCH_PIPELINE.md §8.6 |
| 26 | 报告模板：3 种 task_type → 3 种 Section 组织方式 | RESEARCH_PIPELINE.md §8.2 |
| 27 | 引用锚点：`[来源N]` 正则提取 → 去重排序 → 填充 `section.sources[]` → 写 `section_evidence` | RESEARCH_PIPELINE.md §8.4 |

---

## 5. Phase 4：断点续跑 + 基础设施加固（3-4 天）

**目标**：失败可恢复、进度可追溯、系统可观测。

### 5.1 [后端] Execution Context + 断点续跑

| 状态 | 任务 | 说明 | 依赖决策 |
|:---|:---|:---|:---|
| ⏳ | Execution Context 完整实现 | 每个 Step 完成后原子更新 `execution_context`（`current_phase` / `last_completed_step_id` / `execution_pointer` / `progress`），与 Step 状态写入在同一事务内 | 决策 #28 |
| ⏳ | Checkpoint 保存 | Planning 完成后 / 每个 Fetch URL 成功后 / Synthesis 完成后保存 checkpoint | 决策 #29 |
| ⏳ | Retry API | `POST /api/research/{task_id}/retry` — 读取 `execution_context`，从 `last_completed_step_id` 的下一个 Step 恢复，复用已完成 Step 的 output，Evidence 只 INSERT 不 DELETE | 决策 #30 |
| ⏳ | Retry 前置校验 | `task.status` 必须为 `failed` / `partially_completed` / `canceled` 且 `recoverable=true` → 否则 E2003 | — |
| ⏳ | CAS 状态更新 | 所有 Task 状态更新使用 `UPDATE ... WHERE status = 'old_value'`，更新失败则重试 | 决策 #31 |
| ⏳ | Step 幂等执行 | Step 执行前检查 `status`：已是终态（`completed`/`failed`/`skipped`）则跳过执行 | — |

### 5.2 [后端] 基础设施加固

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | 结构化日志 | 关键节点埋点（请求入口 / Pipeline 阶段开始结束 / LLM 调用 / 异常），统一日志格式（`request_id` + `user_id` + `task_id` + `phase` + `duration_ms`），JSON 格式输出 |
| ⏳ | 全局异常处理完善 | 补充遗漏的异常映射（LLM timeout/rate_limit/auth_error → E3108/E3109/E3110/E3111）+ 未知异常兜底策略（生产环境屏蔽堆栈） |
| ⏳ | 限流中间件 | `app/middleware/rate_limit_middleware.py` — Redis 固定窗口计数器 + Lua 脚本原子性 + 降级放行策略（Redis 不可用时放行）。3 组阈值：创建任务 5/min/user、登录 10/min、全局默认 120/min |

### 5.3 [前端] Retry/Cancel UI

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | Retry UI | 失败视图 `recoverable=true` 时「断点续跑」按钮 → `ElMessageBox.confirm` 确认 → `POST /api/research/{task_id}/retry` → 成功(202)→自动切换到运行态→重连 SSE |
| ⏳ | Cancel UI 完善 | 运行态「取消研究」按钮 → `ElMessageBox.confirm('确定要取消当前研究吗？已完成的部分将保留。')` → `POST /api/research/{task_id}/cancel` → 成功→SSE 收到 `task.canceled`→切换到取消视图。失败（如已终态 E2003）→`ElMessage.error` 显示原因 |
| ⏳ | Sidebar 会话入口适配 | 历史任务区域展示空态（无任务时），点击「新建研究」按钮清空当前任务→切换到创建态，「历史任务」链接高亮路由 `/history` |

### 5.4 🚫 本阶段不做的

| 推迟项 | 排期 | 原因 |
|:---|:---|:---|
| 数据 TTL 自动清理（Celery Beat） | Phase 5 | Phase 4 先做核心恢复机制，定时清理与部署一起交付 |
| Loki + Grafana 部署 | Phase 6（可选） | 结构化日志已就绪，`jq` 命令行可做基本聚合分析 |
| Task 级 Rerun（全新 Execution Context） | v1.5 | 当前 Retry 复用原 context 继续执行。真正「全新 context」的 Task-level Rerun 排 v1.5 |
| 滑动窗口摘要压缩 | Phase 6 | ResearchMind 无长对话上下文需求（每次 Study 独立） |

### 5.5 [测试] Phase 4 测试

| 状态 | 任务 | 测试类型 | 说明 |
|:---|:---|:---|:---|
| ⏳ | Execution Context 原子更新测试 | 单元测试 | checkpoint 写入与 Step 状态在同一事务 / Worker 崩溃后从 checkpoint 恢复 / 恢复后复用已完成 Step output |
| ⏳ | Retry API 接口测试 | 接口测试 | `POST /api/research/{task_id}/retry` 正常断点续跑 + E2003（running 态拒绝）+ E2001/E2002 + 恢复后 Step 不重复执行 + Evidence 只追加 |
| ⏳ | CAS 状态更新测试 | 单元测试 | 并发 Worker 状态覆盖防护 / `UPDATE WHERE status='old_value'` 冲突后重试逻辑 |
| ⏳ | 结构化日志测试 | 单元测试 | JSONFormatter 输出 / RequestID 注入 / Pipeline 各阶段 duration_ms 记录 |
| ⏳ | 限流中间件测试 | 接口+单元 | IP 提取 / 路由规则 / 阈值获取 / 集成（超限返回 E9004 + Retry-After 头 + 降级放行） |
| ⏳ | 错误处理测试 | 单元测试 | E3108(LLM Timeout) / E3109(LLM Rate Limit) / E3110(LLM Auth) / E3111(LLM Unknown) 异常映射 + 生产环境堆栈屏蔽 + 未知异常兜底 |
| ⏳ | Pipeline 断点续跑集成测试 | 集成测试 | 模拟 Phase 3 Fetch 中途崩溃 → Retry 从 Fetch checkpoint 恢复 → 后续 Phase 正常完成 → 报告产出验证 |
| ⏳ | 前端 Retry/Cancel UI 组件测试 | 组件测试 | 失败视图 Retry 按钮→确认弹窗→API 调用→切换到运行态 / Cancel 按钮→确认弹窗→API 调用→取消视图 / E2003 状态冲突提示 |

### 5.6 [索引] 关键决策索引

| # | 决策 | 文档位置 |
|:---|:---|:---|
| 28 | Execution Context：每个 Step 完成后原子更新，与 Step 状态在同一事务 | ARCHITECTURE.md §3.3 |
| 29 | Checkpoint 保存时机：每 Phase 完成后 + 每个 Fetch URL 后 + Synthesis 后 | RESEARCH_PIPELINE.md §10.3 |
| 30 | Retry：从 `last_completed_step_id` 的下一个 Step 恢复，复用已完成 output | ARCHITECTURE.md §3.3 |
| 31 | CAS 状态更新：`WHERE status = 'old_value'`，并发 Worker 防覆盖 | ARCHITECTURE.md §5.7 |
| 32 | 限流阈值 Phase 5 最终确定：Phase 4 先实现中间件框架，压测后调整 | — |

---

## 6. Phase 5：打磨上线 + 管理后台（4-5 天）

**目标**：管理后台 + 部署就绪，可以上线。

### 6.1 [管理后台] 管理后台 API

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | Admin Pydantic Schema | `AdminStatsResponse`（7 统计维度：总任务数/运行中/完成/失败/用户数/Token 消耗/预估成本）/ `AdminTaskItem` / `AdminTaskListResponse` / `AdminUserItem` / `AdminUserListResponse` |
| ⏳ | Admin Service | `app/services/admin_service.py` — `get_stats()` / `list_all_tasks()`（筛选：status/user_id/搜索 + 分页）/ `list_all_users()`（筛选：role/status/搜索 + 分页） |
| ⏳ | Admin API 端点 | `app/api/admin.py` — `GET /api/admin/stats` / `GET /api/admin/tasks` / `GET /api/admin/tasks/{task_id}` / `DELETE /api/admin/tasks/{task_id}` / `GET /api/admin/users` / `GET /api/admin/users/{user_id}` / `PUT /api/admin/users/{user_id}/status` + `require_admin` 依赖注入 |

### 6.2 [高级功能] Trace 链路追踪

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | Trace 数据持久化 | 每 Step 完成后写入 `research_tasks.trace` JSON 列（各阶段 `duration_ms` + `input_tokens`/`output_tokens` + `model` + `status`） |
| ⏳ | Trace API | `GET /api/admin/traces`（分页+筛选：status/日期范围）+ `GET /api/admin/traces/{task_id}` |
| ⏳ | 统计增强接口 | `GET /api/admin/stats` 响应新增 `charts` 字段：研究量趋势（按天聚合）/ 响应时间分布（P50/P95/P99）/ Token 使用统计（按 task_type 分拆） |

### 6.3 [前端] Admin 管理后台 + ECharts 统计

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | AdminLayout | `components/layout/AdminLayout.vue` — 独立 Admin 侧边栏（240px）+ 主内容区。菜单项：📊 系统统计 / 📋 任务管理 / 👥 用户管理 / ← 返回研究。从 DocMind 直接复制布局骨架，替换 Admin 菜单项 | FRONTEND.md §6.1 |
| ⏳ | AdminStats 统计页 | `views/admin/StatsPage.vue` — 6 统计卡片（用户总数 / 任务总数 / 完成任务数 / 失败任务数 / 证据总数 / 来源总数）+ ECharts 图表（任务量趋势折线图 / 任务耗时分布柱状图 P50/P95/P99 / 研究类型分布饼图 comparison/explainer/analysis） | FRONTEND.md §6.2 |
| ⏳ | AdminTaskList 任务管理 | `views/admin/AdminTaskList.vue` — 跨用户全部研究任务表格（含 `username` 列，筛选：`user_id`/`status`/`task_type`/搜索，分页 + 操作[查看详情/取消/删除]）。删除二次确认 + `ElLoading` 全屏遮罩 + 本地 `filter()` 移除 + 空页回退 | FRONTEND.md §6.3 |
| ⏳ | AdminTaskDetail 任务详情 | `views/admin/AdminTaskDetail.vue` — 任务信息卡片 + Pipeline 阶段 + Step 列表 + Trace 摘要 | — |
| ⏳ | Admin API 封装 | `api/admin.js` — `getStats()` / `getAllTasks()` / `getTaskDetail()` / `deleteTask()` / `getAllUsers()` / `getUserDetail()` / `changeUserStatus()` / `resetUserPassword()` | — |
| ⏳ | AdminUserList 用户管理 | `views/admin/AdminUserList.vue` — 用户列表（表格：用户名/角色/状态/任务数/最后活跃/操作，筛选：角色/状态/搜索，分页 + 操作菜单[查看详情/禁用启用/重置密码]）。从 DocMind 直接复制，替换统计列（KB数/文档数/会话数→任务数/完成数/失败数） | FRONTEND.md §6.4, INFRASTRUCTURE_REUSE_FRONTEND.md §8.1 |
| ⏳ | AdminUserDetail 用户详情 | `views/admin/AdminUserDetail.vue` — 用户信息卡片 + 统计卡片（任务总数/完成数/失败数/证据数）+ 快捷操作（禁用/启用 + 重置密码）。从 DocMind 直接复制，替换统计维度 | FRONTEND.md §6.4 |
| ⏳ | ECharts 组合式函数 | `composables/useECharts.js` — 响应式 resize 监听（ResizeObserver）+ `dispose()` 清理 + 主题配置。从 DocMind 直接复制 | INFRASTRUCTURE_REUSE_FRONTEND.md §6.2 |
| ⏳ | 图表配置常量 | `constants/charts.js` — 颜色/样式/tooltip 配置（对齐 `--rm-*` Design Token）。从 DocMind 复制骨架，重写图表配置 | — |
| ⏳ | D3.js Evidence Graph 可视化 [可选] | Evidence Graph 节点关系力导向图（D3.js force simulation）：Evidence items → nodes / cluster → groups / conflicts → dashed edges。低优先级，Phase 5 时间允许则做 | — |

### 6.4 [运维] 部署就绪

| 状态 | 任务 | 说明 |
|:---|:---|:---|
| ⏳ | README.md 完善 | 项目简介 + 快速开始（Docker Compose）+ 文档索引 + 环境变量说明 |
| ⏳ | Dockerfile × 2 | `Dockerfile.backend`（FastAPI + Celery Worker）+ `Dockerfile.frontend`（Nginx + 静态资源） |
| ⏳ | docker-compose.yml | 4 服务编排（MySQL + Redis + Backend + Celery Worker）+ 数据卷持久化 + 网络隔离 |
| ⏳ | nginx.conf（前端） | 反向代理 + SSE buffering 关闭 + 静态资源 SPA fallback + `client_max_body_size` |
| ⏳ | 数据 TTL 清理 | Celery Beat 定时任务：`research_tasks` 30 天清理 / SSE 日志 7 天轮转 / 应用日志 14 天 logrotate |
| ⏳ | `.env.example` 更新 | 新增 `ENV` / `CORS_ORIGINS` / `RATE_LIMIT_*` 等生产配置项 |

### 6.5 🚫 本阶段不做的

| 推迟项 | 排期 | 原因 |
|:---|:---|:---|
| v1.5 需求字段（`focus_areas`/`exclude_domains`/`time_range`） | v1.5 | MVP 仅核心 4 字段 |
| 多报告模板渲染（技术版/学术版） | v1.5 | v1.0 按 `task_type` 自动选择单模板 |
| 审计日志（`audit_log` hook） | v1.5 | `require_task_accessible` 中已预留 hook 调用点 |
| 用户审计日志（`user_operations` 表） | v2 | v1.0 Admin 先做 CRUD + 角色管理 |
| 分级 LLM（Planning/Report 用 Opus，Search/Rerank 用 Haiku） | v2 | MVP 全链路 deepseek-v4-pro 单一模型 |

### 6.6 [测试] Phase 5 测试

| 状态 | 任务 | 测试类型 | 说明 |
|:---|:---|:---|:---|
| ⏳ | Admin 接口测试 | 接口+单元 | Service 层统计聚合 / API 层 CRUD + 权限矩阵（非 admin→E2009）/ 用户管理（禁用/启用） |
| ⏳ | Trace 接口测试 | 接口+单元 | Trace 列表（分页+筛选）/ Trace 详情（7 阶段数据完整性）/ task_id 不存在的 Trace |
| ⏳ | ECharts 统计接口测试 | 单元测试 | trend 聚合 / latency 分位数 / tokens 聚合 |
| ⏳ | 全量回归测试 | 回归测试 | 遍历完整测试集（单轮 + 断点续跑 + 3 种 task_type） |
| ⏳ | 压测 | 性能测试 | Locust 4 场景（基准/日常/峰值/极限），P50≤2min / P99≤4min。压测完成后据此调整限流阈值 |
| ⏳ | 最终人工报告质量评估 | 人工评估 | 第 2 轮 9 题 × 4 维度评分，对比 Phase 3 基线，验证全链路优化效果 |
| ⏳ | 前端 AdminStats 组件测试 | 组件测试 | 统计卡片数据渲染 / ECharts 图表渲染 / 空数据边界 / ResizeObserver 响应式 |
| ⏳ | 前端 AdminTaskList 组件测试 | 组件测试 | 表格渲染 / 筛选联动（重置 currentPage=1）/ 删除确认→loading→行移除→空页回退 / 分页 / 空状态 |
| ⏳ | 前端 AdminUserList 组件测试 | 组件测试 | 用户列表渲染 / 筛选（角色/状态/搜索）/ 操作菜单（禁用启用/resetPassword loading）/ 分页 |
| ⏳ | 前端 AdminUserDetail 组件测试 | 组件测试 | 信息卡片渲染 / 统计卡片 / 快捷操作（禁用/重置密码）/ 错误处理 |
| ⏳ | 前端 ECharts 图表组件测试 | 组件测试 | TrendChart + LatencyChart + PieChart = 含空数据边界（ResizeObserver mock + ECharts mock） |
| ⏳ | 全量回归测试 | 回归测试 | 遍历完整测试集（前端组件 + 后端接口 + Pipeline 集成 + 断点续跑 + 3 种 task_type） |
| ⏳ | 压测 | 性能测试 | Locust 4 场景（基准/日常/峰值/极限），P50≤2min / P99≤4min。压测完成后据此调整限流阈值 |

---

## 7. Phase 6：迭代优化（不设时限）

**目标**：v1.5 / v2.0 高级功能、架构级改造、持续优化。不阻塞上线，按需求优先级逐个实现。

### 7.1 [高级功能] v1.5 — 证据粒度升级与新需求字段

| 优先级 | 任务 | 来源 | 说明 |
|:---|:---|:---|:---|
| P0 | Paragraph → Evidence Spans | ROADMAP §1 | 段落内证据片段锚定，hover 预览原文。`evidence_graph.items[]` 已预留 span 级字段（`content`、`relevance_score`），Schema 升级不改变 Pipeline |
| P0 | `focus_areas` / `exclude_domains` / `time_range` 需求字段 | PRD §1.3 | `requirements` 扩展 3 字段，Search 阶段注入 `exclude_domains` + Fetch 阶段日期过滤 |
| P1 | SearXNG 搜索降级后端 | ARCHITECTURE §5.6 | 双路搜索（Tavily + SearXNG）→ RRF 融合（激活已复制的 `fusion.py`） |
| P1 | 多报告模板 | PRD §1.3 | 同一 Evidence Graph → 技术版 / 学术版两种报告模板 |
| P2 | 审计日志 | ARCHITECTURE §4.3 | `audit_log` hook 激活（`require_task_accessible` 中记录访问） |
| P2 | 句级 Evidence Auditor | INFRASTRUCTURE_REUSE §4.4 | 三层证据审计激活（引用存在性→来源一致性→句级证据回溯） |
| P3 | Task-level Rerun | — | 全新 Execution Context，不复用旧数据 |

### 7.2 [高级功能] v2.0 — Full Deep Research

| 优先级 | 任务 | 来源 | 说明 |
|:---|:---|:---|:---|
| P0 | 真 DAG 并行调度 | ARCHITECTURE §3.4 | `step_edges` 表（`from_step_id`/`to_step_id`/`dependency_type`），Search/Fetch 跨子问题并行执行 |
| P0 | Claim 级 Evidence Graph | ROADMAP §1 | 句子级事实核查，冲突检测，证据评分可解释——需新增 Claim Extractor 阶段 |
| P1 | 递归分解（Recursive Decomposition） | PRD §1.3 | Synthesis 阶段发现知识缺口→自动生成新的 SubQuestion→重新进入 Search→Fetch→Rerank 循环 |
| P1 | 分级 LLM | ARCHITECTURE §1 | Planning/Report 用 deepseek-v4-pro（强推理），Search/Rerank 用 deepseek-v4-flash（低成本） |
| P2 | Human-in-the-loop | PRD §1.3 | Planning 完成后支持用户调整 SubQuestions / 审核后继续执行 |
| P2 | 阶段级 Pause/Resume | API §3.4 | `POST /{task_id}/pause` / `POST /{task_id}/resume` |
| P3 | Agent Workflow Editor | PRD §1.3 | 可视化编排研究 Pipeline（拖拽式 DAG 编辑） |

### 7.3 [高级功能] 持续优化（不分版本）

| 优先级 | 任务 | 说明 |
|:---|:---|:---|
| P3 | reasoning_effort 前端可控 | 客户端选择思考深度（low/medium/high），后端映射到 DeepSeek `reasoning_effort` 参数 |

---

## 8. 依赖关系

```
Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4 ──→ Phase 5 ──→ Phase 6
  │            │            │            │            │            │
  ├─ 后端测试    ├─ 后端测试    ├─ 后端测试    ├─ 后端测试    ├─ 后端测试
  ├─ 前端测试    ├─ 前端测试    ├─ 前端测试    ├─ 前端测试    ├─ 前端测试     (不设时限)
  (基础)      (创建+列表)   (进度+报告)   (刷新+Retry)  (Admin+全量+压测)
```

### 8.1 准入规则

**每个 Phase 的测试必须在该 Phase 功能完成后立即执行，作为下一 Phase 的准入条件：**

- Phase N 功能完成 → 执行 Phase N 测试 → 全部通过 → 方可进入 Phase N+1
- 回归测试集随 Phase 迭代持续扩充，每次提交运行全量回归
- Phase 3 完成时建立基线报告质量评分（人工评估第 1 轮），Phase 5 完成时对比验证

---

## 9. 相关文档

- [产品需求文档](PRD.md)
- [架构设计文档](ARCHITECTURE.md)
- [研究管线设计文档](RESEARCH_PIPELINE.md)
- [接口文档](API.md)
- [数据库设计文档](DATABASE.md)
- [基础设施复用清单](INFRASTRUCTURE_REUSE.md)
- [开发指南](DEVELOPMENT.md)
- [变更日志](CHANGELOG.md)
