# CHANGELOG — 变更日志

> 本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/) 格式。
>
> 版本号使用 [语义化版本](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`。
>
> 分类：`Added`（新增）、`Changed`（变更）、`Deprecated`（弃用）、`Removed`（移除）、`Fixed`（修复）、`Security`（安全修复）。

---

## [Unreleased]

> Phase 1 骨架搭建完成（后端 §2.1-2.4 + 前端 §2.5 ✅，测试 §2.7 待执行）。
> Phase 2.3.1 研究任务 CRUD + 状态机完成（ROADMAP §3.1 ✅）。
> Phase 2.3.2 Celery 异步 Pipeline 编排基础设施完成（ROADMAP §3.2 ✅）。

### Added
- **Phase 2.3.2 Celery 异步 Pipeline 编排（ROADMAP §3.2）**——7 个源文件 + Celery 分发激活：
  - `app/pipeline/sse_bridge.py` — SSE Bridge（~300 行）：Redis Pub/Sub 桥接 Celery Worker ↔ FastAPI ↔ SSE Stream。发布层 `SSEBridge` 类（同步 publish + seq 序号单调递增）+ 订阅层 `sse_event_stream()` 异步生成器（连接时推送 `task.status.snapshot`，循环获取 Redis 消息 yield SSE 格式事件，`stream_with_heartbeat` 包裹）。17 种 SSE 事件类型常量（`EVENT_TASK_CREATED` 等）。跨平台 Pub/Sub（Linux 原生 `redis.asyncio` / Windows `_SyncPubSubWrapper` 线程池包装）
  - `app/services/pipeline_orchestrator.py` — Pipeline Orchestrator（~450 行）：`PipelineOrchestrator` 类，七阶段串行调度。每 Phase：创建 ResearchStep → 幂等锁检查（`acquire_step_lock_async`）→ 更新 step status→running → 发送 SSE 事件（`phase.started` / `step.started`）→ 调用 Phase handler → 更新 output + status→completed → 原子更新 `execution_context` → 发送 SSE 事件（`step.completed` / `phase.completed` / `task.progress` / `checkpoint.saved`）→ `TaskStateResolver` 检查提前终止 → 释放锁。含 `build_default_phase_handlers()` 注册表（planning/search/fetch → Phase 2 stub，rerank/synthesis/evidence_graph/render → Phase 3 待实现自动跳过）。`TaskFatalException` 不可恢复错误
  - `app/tasks/research_task.py` — Celery 任务入口（~110 行）：`@celery_app.task` 装饰的 `execute_research_task(task_id)`，`asyncio.run()` 包裹 async 逻辑。幂等检查（非 pending 状态跳过）+ 实例化 SSEBridge / TraceRecorder / Orchestrator → `orchestrator.run()` → commit。`_emergency_fail()` 兜底写入失败状态
  - `app/pipeline/planner.py` — Planning Phase stub（~40 行）：`run_planning()` 函数签名 + 返回 stub output（等待 §3.3 替换为 LLM 调用 + 输出校验 + task_type 策略注入）
  - `app/pipeline/searcher.py` — Search Phase stub（~40 行）：`run_search()` 函数签名 + 返回 stub output（等待 §3.4 替换为 Tavily API 调用 + 去重 + 失败重试）
  - `app/pipeline/fetcher.py` — Fetch Phase stub（~40 行）：`run_fetch()` 函数签名 + 返回 stub output（等待 §3.5 替换为 HTTP GET + trafilatura 提取 + SSRF 防护）

### Changed
- `app/services/research_service.py` — 移除 Celery 分发逻辑（commit+delay 移至 API 层），`create_task()` 仅做 flush，更新 docstring
- `app/api/research.py` — 新增 `execute_research_task.delay()` 调用（`create_task()` 返回后、响应返回前），新增 Celery 导入
- `app/tasks/celery_app.py` — 已完成（Phase 2 早期）：Celery app + Redis broker/backend + Windows SelectorEventLoopPolicy + research_task 队列
- `app/tasks/lock.py` — 已完成（Phase 2 早期）：Redis SET NX 幂等锁（同步+异步双接口）

- **Phase 2.3.1 研究任务 CRUD + 状态机（ROADMAP §3.1）**——6 个源文件 + 3 个测试文件 + 94 个新测试：
  - `app/schemas/research.py` — Pydantic Schema 层（~110 行）：`ResearchCreateRequest`（topic 1-500 chars + requirements 三层校验）/ `ResearchTaskResponse`（含 progress 快照 + error 字段）/ `ResearchTaskListItem`（列表项精简字段）/ `ResearchTaskListResponse`（分页 + total）/ `ProgressSchema`（completed_steps / total_steps / progress 0.0-1.0）
  - `app/services/research_service.py` — Service 层（~200 行）：`create_task()`（校验 → 写入 ResearchTask + 首个 planning ResearchStep → flush，Celery 分发预留注释点）/ `get_task_list()`（当前用户分页列表，created_at DESC，可选 status 筛选，page_size 上限 100）/ `get_task_detail()`（execution_context.progress 优先，fallback 到统计列）/ `delete_task()`（bulk DELETE `sa_delete` 绕过 ORM 关系处理，由 FK CASCADE 清理派生数据）
  - `app/api/research.py` — API 端点（~85 行）：`POST /api/research`（201 + task_id）/ `GET /api/research`（分页列表 + status 筛选）/ `GET /api/research/{task_id}`（详情，`Depends(require_task_accessible)`）/ `DELETE /api/research/{task_id}`（删除，级联验证）
  - `app/core/task_state_resolver.py` — TaskStateResolver（~100 行）：FATAL 步骤错误码集（E3101/E3105/E3106/E3110）→ 立即 FAILED / 全部 non-skipped COMPLETED → COMPLETED / 部分完成 → Evidence Threshold 判定（`min_evidence = max(5, ceil(max_sources * 0.4))`）/ 空步骤列表 → 保持原状态
  - 测试覆盖：`tests/unit/schemas/test_research.py`（21 用例：合法/边界/非法 topic·task_type·depth·max_sources·progress）/ `tests/unit/services/test_research_service.py`（27 用例：创建成功+三种 task_type+分页+筛选+详情含 error·含 progress·含 execution_context+删除级联+仅删除指定任务）/ `tests/unit/api/test_research.py`（27 用例：创建 201+验证+列表+分页+筛选+详情 E2001+E2002+admin 审计+删除+级联验证+未登录 401+422）/ `tests/unit/core/test_task_state_resolver.py`（19 用例：COMPLETED+FATAL+PARTIALLY_COMPLETED+E3103 degradable+空步骤+未终态）

### Changed
- `app/dependencies.py` — 新增 `require_task_accessible` 依赖注入（owner→允许 / admin→审计 / 其他→E2002），新增 import `TaskAccessDeniedException` / `TaskNotFoundException` / `ResearchTask`
- `app/main.py` — 注册 research router（`app.include_router(research.router, prefix="/api/research")`）
- `app/models/research_task.py` — 全部 4 个 relationship 添加 `passive_deletes=True`（steps / sources / evidence_items / report_sections），配合 FK CASCADE 避免 ORM DELETE 时先 SET NULL 子表
- `app/models/research_step.py` — `evidence_items` relationship 添加 `passive_deletes=True`
- `tests/conftest.py` — 新增 `@event.listens_for(engine.sync_engine, "connect")` 设置 `PRAGMA foreign_keys = ON`（SQLite 默认关闭 FK 约束，需每个连接启用）；新增 `event` 导入

### Removed
- **删除 INFRASTRUCTURE_REUSE.md 和 INFRASTRUCTURE_REUSE_FRONTEND.md**（施工快照文档）。所有信息已物化到代码或设计文档：
  - 后端 9 个"直接复制"文件已落地（含本次补齐的 `fusion.py` / `sentence_matcher.py` / `evidence_auditor.py`）+ 4 个"需改造适配"文件锚点已写入 RESEARCH_PIPELINE.md
  - 前端 9 个"直接复制"文件已落地（含本次补齐的 `format.js` / `markdown.js` / `useECharts.js`）+ FRONTEND.md 新增 §1.4 共享工具模块
  - 设计文档补 10 个模块锚点（RESEARCH_PIPELINE.md 5 处 + FRONTEND.md 3 处 + §1.4）
  - CLAUDE.md / DEVELOPMENT.md / ROADMAP.md / README.md / TESTING_STRATEGY.md / UIDESIGN.md 的交叉引用全部更新

### Fixed
- **S-01**: `research_tasks` 新增 `trace` JSON 列（Pipeline 七阶段 Trace 数据），对齐 trace_recorder.py 产出
- **S-02**: `get_current_user()` 改为复用 `get_db()` session，消除每请求双 DB 连接问题；User 关联 `lazy` 改为 `noload` 避免不必要数据加载
- **S-03**: `logout()` 新增 `user_id` 一致性校验，防止用户 A 吊销用户 B 的 refresh_token
- **S-04**: `router/index.js` 导出 `authGuard` 函数；`routerGuards.test.js` 改为 import 真实守卫逻辑，不再复制生产代码
- **S-05**: `LoginPage.vue` 密码框 `autocomplete` 属性随模式切换（登录 `current-password` / 注册 `new-password`）
- **N-01**: `RequestIDMiddleware` 从 `BaseHTTPMiddleware` 改为纯 ASGI 中间件，与 AuthMiddleware 统一实现模式
- **N-02**: `utcnow()` 重命名为 `utc_now()`，避免与 Python 3.12 弃用的 `datetime.utcnow()` 混淆；保留 `utcnow` 兼容别名
- **N-04**: `Sidebar.vue` / `AdminLayout.vue` 硬编码颜色和尺寸改为 Design Token（`--rm-danger` / `--rm-danger-border` / `--rm-space-*`）
- **N-09**: `index.html` Font Awesome CDN 链接添加 SRI `integrity` + `crossorigin` 属性
- `research_steps` / `research_sources` / `evidence_items` / `report_sections` 新增 `updated_at` 列（ORM `onupdate` 自动维护）
- `DATABASE.md` §2.2-§2.6 同步更新表结构文档
- 测试弱断言修复：`test_auth.py` access_token 验证 JWT 结构 + expires_in 精确断言、`test_user.py` 使用 `IntegrityError` 替代裸 `Exception`、`test_llm.py` 提取共享 `mock_llm_client` fixture

### Added
- **测试基础设施与策略文档（ROADMAP §2.7）**：
  - `docs/TESTING_STRATEGY.md`（v2.0）— 10 章节测试策略纲领：§1 核心质量挑战（Pipeline 7×7×6 状态空间）+ 测试金字塔（含压测层）+ 8 条核心原则 / §2 后端三层 + 前端三层分层 / §3 基础设施（pytest.ini 配置 + SQLite 内存库隔离 + Mock 策略矩阵 + 环境变量隔离）/ §4 后端策略（关键路径 100% 覆盖四模块 + 异常体系 31+ 类三维度验证 + 安全模块 7 函数成对测试 + Auth Service 6 函数全分支含泄露检测 E1009 + LLM 重试策略 5 场景 + Pipeline 9 阶段验证要点 + Trace Recorder + 6 个辅助模块覆盖要点，各节含精简模式示例）/ §5 前端策略（Store 并发防抖 / API 拦截器 / 组件表单校验与 SSE 事件驱动 / 路由守卫）/ §6 GitHub Actions CI/CD（MySQL + Redis service containers + Codecov）+ Pre-commit Hook / §7 分 Phase 覆盖率目标（Phase 1: 后端 ≥85% 行覆盖/≥80% 分支、前端 ≥75% 行覆盖/≥70% 分支，关键路径任何阶段 ≥100%）/ §8 编写规范（命名/结构/标记 + 禁止模式对照表）/ §9 按 Phase 测试重点与关键风险矩阵 / §10 命令速查 + 新模块上线流程。测试进度追踪见 ROADMAP.md
  - `pytest.ini` — pytest 配置（asyncio_mode=auto, default_loop_scope=function, strict-markers, unit/integration/slow/regression 四标记）
  - `tests/conftest.py` — 共享 fixtures：SQLite 内存 test_engine（session 级复用 + 自动建表）、db_session（函数级事务隔离 + 自动回滚）、async_client（FastAPI httpx AsyncClient + get_db 依赖覆盖）、auth token fixtures（valid_access_token / valid_admin_token / valid_refresh_token_str / auth_headers / admin_headers）、seeded_user 预置数据
  - `frontend/vitest.config.js` — 前端测试配置（jsdom 环境 + `@/` 别名 + v8 覆盖率）
  - `frontend/tests/setup.js` — 全局 Mock（localStorage + Element Plus + matchMedia + ResizeObserver）+ 自动 cleanup

- **Phase 1 认证系统（ROADMAP §2.4）**：从 DocMind 复制并适配完整 Auth 体系：
  - `app/schemas/auth.py` — 7 个 Pydantic Schema：`RegisterRequest` / `LoginRequest` / `RefreshRequest` / `LogoutRequest` / `ChangePasswordRequest` / `TokenResponse` / `UserResponse`
  - `app/services/auth_service.py` — 6 个业务函数：`register()`（用户名唯一性检查 + bcrypt 哈希）/ `login()`（密码验证 + Token 对生成）/ `refresh()`（Rotation 刷新 + E1009 泄露检测）/ `logout()`（吊销 refresh_token）/ `change_password()`（改密后全量吊销）/ `revoke_all_user_tokens()`
  - `app/api/auth.py` — 5 个 API 端点：`POST /api/auth/register` / `POST /api/auth/login` / `POST /api/auth/refresh` / `POST /api/auth/logout` / `PUT /api/auth/password`
  - `app/dependencies.py` — `get_current_user` 依赖注入（JWT Bearer Token 解析 → 查 `users` 表 → 校验 `status=active` → 注入 `User` 对象）；此模块在 Phase 1 基础设施复用阶段已创建，本次确认与 Auth 体系正确集成
  - `app/main.py` — 新增 `AppException` 异常处理器（`AppException` → 对应 HTTP 码），与已有的 `RequestValidationError`（422/E9003）和 `Exception`（500/E9001）处理器构成完整三级异常处理链
  - `app/main.py` — 注册 auth 路由（`app.include_router(auth.router, prefix="/api/auth")`）
  - 端到端验证通过：注册 / 登录 / Token 刷新 Rotation / 泄露检测 E1009 / 登出 / 改密 + 全量吊销，全部 10 个场景正常
- **Phase 1 前端脚手架 + Auth + 布局框架（ROADMAP §2.5）**：从 DocMind 复制并适配完整前端骨架（18 个文件，~80% 代码复用）：
  - `package.json` / `vite.config.js` / `index.html` — 项目根文件：Vue 3 + Vite 6 + Pinia + Element Plus + Axios + Font Awesome + markdown-it + highlight.js + Vitest；`@/` alias + `/api` proxy → `localhost:8000`；title「ResearchMind - 可审计的结构化研究引擎」
  - `src/styles/global.css` — Design Token 系统：`--rm-*` CSS 变量全量定义（品牌色 teal-700 / slate 中性色 / 暗色侧边栏专用变量 / Element Plus 全量覆盖）；移除 DocMind 的 RAG/orphan/JSON/部门色等不适用变量
  - `src/main.js` — 应用入口（Vue + Pinia + Router + ElementPlus 中文 locale）
  - `src/api/index.js` — Axios 实例 + Token 自动刷新：请求拦截器附 Bearer Token；响应拦截器 401+E1003 → `doRefresh()` → 重放原请求，`isRefreshing` + `requestQueue` 防并发；错误码适配 E5003→E1003 / E5002→E1002 / E5010→E1010
  - `src/api/auth.js` — Auth API 封装：`login()` / `register()` / `refresh()` / `logout()` / `changePassword()`
  - `src/stores/auth.js` — AuthStore (Pinia)：`user` / `token` / `isAdmin` / `login()` / `logout()` / `refresh()` + `scheduleRefresh` 定时器（到期前 60s 自动刷新）+ `_refreshing` 并发防护
  - `src/router/index.js` — 路由表（`/login` 公开 / `/research` 需认证 / `/history` 需认证 / `/admin/*` 需管理员）+ 三级路由守卫
  - `src/views/LoginPage.vue` — 登录/注册页：品牌区（`fa-microscope` +「ResearchMind」+「可审计的结构化研究引擎」）+ Tab 切换 + 表单校验 + 提交 loading
  - `src/components/layout/AppLayout.vue` — 主布局（Sidebar + Header + 内容区）
  - `src/components/layout/Sidebar.vue` — 暗色侧边栏（slate-900 `#0F172A`）：Logo + 新建研究按钮 + 历史任务导航 + 用户栏 + 用户菜单卡片 + 修改密码弹窗 + 展开/收起切换（256px/64px）。移除 DocMind 会话列表逻辑（~250 行），CSS 全量重色适配暗色主题
  - `src/components/layout/AdminLayout.vue` — 管理后台独立布局（暗色侧边栏 + 系统统计/任务管理/用户管理导航）
  - `src/App.vue` — 根组件：三路布局分发（公开页/Admin/AppLayout）
  - 6 个 placeholder 页面（ResearchPage / HistoryPage / AdminStats / AdminTaskList / AdminTaskDetail / AdminUserList / AdminUserDetail）供 Phase 2+ 实现
  - 验证通过：`npm install` ✅ / Vite 启动 HTTP 200 ✅ / 零 `--dm-` 变量泄漏 ✅ / 零 DocMind 品牌引用残留 ✅

### Fixed
- `app/core/security.py` — `create_refresh_token()` 新增 `jti: uuid.uuid4().hex` 声明，修复同一秒内签发两个 refresh_token 时 JWT payload 完全相同 → SHA-256 哈希碰撞 → `refresh()` 中 `scalar_one_or_none()` 抛出 `MultipleResultsFound` 的 bug。此 bug 同样存在于 DocMind 源码，已同步修复
- `app/core/llm.py` — 修复导入错误：`from app.core.exceptions import LLMCallFailedException` 引用了 `exceptions.py` 与 [API.md §5](API.md#5-错误码表完整) 均未定义的异常类，导致整个 `app.core.llm` 模块无法导入。按「代码对齐文档」原则（禁止反向改文档迁就代码），将「LLM 返回空 choices」场景映射到已定义的 `LLMUnknownException`（E3111「调用返回未预期错误」），移除未定义引用；`except (LLMUnknownException, LLMAuthFailedException)` 保留「空结果/认证失败不重试」语义。[Deviation] TESTING_STRATEGY.md §4.5 原述「空 choices 抛出 LLMCallFailedException」随之调整为 `LLMUnknownException`

### Added
- **Phase 1 后端测试落地（ROADMAP §2.7）**——184 个单元/接口测试全部通过：
  - `tests/unit/core/test_security.py` — 密码哈希 & JWT（`hash_password`/`verify_password`/`create_access_token`/`decode_access_token`/`create_refresh_token`/`decode_refresh_token`/`hash_token` 全 7 函数，成功+失败成对：过期/伪造/错误密钥/无 exp token）
  - `tests/unit/core/test_exceptions.py` — 异常体系全 35 类三维度验证（错误码+HTTP 状态码 / detail 结构化字段 / HTTPException 三元组序列化），含 `recoverable`/`retry_after_ms` 可选字段
  - `tests/unit/core/test_token_counter.py` — 中英文自适应估算（纯英文 4.0 / 纯中文 1.5 / >30% 中文用中文 ratio / 临界 30% / 空串返回 1）
  - `tests/unit/core/test_llm.py` — LLM 客户端重试策略（`_classify_llm_error`/`_retry_delay`/`_max_retries` 真实逻辑 + Mock AsyncOpenAI）：timeout 重试 3 次 / auth 0 次 / rate_limit 指数退避 5/10/20s / 空 choices→E3111 不重试 / 流式 chunk 逐条 yield
  - `tests/unit/models/test_types.py` — UTCDateTime aware↔naive 双向转换 + `utcnow()` 读写一致性
  - `tests/unit/models/test_user.py` — User ORM 默认值 / created_at 自动填充 / username 唯一约束 / role·status 显式设置
  - `tests/unit/schemas/test_auth.py` — 7 个 Pydantic Schema 边界值校验（用户名 2-64 / 密码 6-128 / 纯数字·纯空格禁止）
  - `tests/unit/services/test_auth_service.py` — Auth Service 6 函数全分支：含 **E1009 泄露检测**（已吊销 token 重用→全量吊销该用户 token）/ Rotation 链 / 过期 E1006 / 禁用 E1010 / 改密全量吊销
  - `tests/unit/api/test_auth.py` — 5 个 API 端点正常流程 + 错误码（E1001/E1002/E1006-E1011）+ 异常处理器（422/E9003、未认证 401/E1004）
  - `tests/conftest.py` 增强：SQLite 兼容层（`MEDIUMTEXT`→`TEXT` 编译降级 / `BigInteger`→`INTEGER` 使主键自增可用 / 全局索引名按表前缀去重，解决 DATABASE.md 多表复用 `idx_task` 与 SQLite 全局索引命名空间冲突）；`async_client` 改用「单连接单事务」共享 `db_session` 模式 + 覆盖 `get_current_user`（避免生产实现经 `async_session_factory()` 打开真实 MySQL）
- **Phase 1 前端测试落地（ROADMAP §2.7）**——45 个单元/组件测试全部通过：
  - `tests/unit/authStore.test.js` — AuthStore (Pinia)：login token+user 持久化 / logout 清除 / 登录失败不提权 / isAdmin 计算属性 / register 不自动登录 / refresh 并发防抖（仅发起 1 次 API）/ 无 token refresh 拒绝 / 刷新失败清除状态
  - `tests/unit/tokenRefresh.test.js` — Axios 拦截器：请求拦截器附 Bearer Token / E1003→刷新→重放 / E1002·E1010·非 401·_retry 直接透传 / 刷新失败清除 token 跳转 login / 并发 E1003 排队重放（isRefreshing 防并发）
  - `tests/components/LoginPage.test.js` — LoginPage 组件：品牌区渲染 / 登录↔注册 Tab 切换 / 表单校验（空用户名/纯数字/<2 字符/密码<6 字符）/ 提交 loading+disabled / 登录成功跳转 /research / 失败错误提示 / 注册成功切回登录
  - `tests/components/AppLayout.test.js` — AppLayout 组件：.app-layout 根容器 / Sidebar 存在性 / slot 内容区 / Header 标题（Research→「ResearchMind」、History→「历史任务」）
  - `tests/components/routerGuards.test.js` — 路由守卫：未登录→/login / 已登录访问/login→/research / 普通用户/admin→/research / admin→/admin 通过 / 根路径→/research
  - 修复预置 `tests/setup.js` bug：`@vue/test-utils` 2.4.11 未导出 `cleanup`（2.6+ 新增），改用 `document.body.innerHTML = ''`
  - element-plus mock 扩展 `default: { install() {} }` 使 `app.use(ElementPlus)` 可用，同时 mock ElMessage/ElMessageBox/ElLoading

- **Phase 1 基础设施复用落地（ROADMAP §2.3）**：从 DocMind 复制并适配 11 个基础设施模块：
  - `app/core/exceptions.py` — 异常体系（AppException 基类 + 31 个异常类，E1xxx/E2xxx/E3xxx/E9xxx 错误码）
  - `app/core/llm.py` — LLM 客户端（DeepSeek SDK 封装 + timeout/rate_limit/auth_error 分级重试）
  - `app/core/token_counter.py` — Token 估算（中英文自适应算法，从 DocMind chunker.py 复制）
  - `app/core/security.py` — JWT 安全模块（密码哈希 + access/refresh token 签发验证）
  - `app/middleware/auth_middleware.py` — JWT 认证中间件（ASGI，验证 Bearer Token + 写入 request.state）
  - `app/dependencies.py` — 依赖注入（get_db / get_current_user / require_admin）
  - `app/core/permissions.py` — 权限中间件（三层分离：task_accessible / task_owner / admin）
  - `app/core/sse.py` — SSE 流式框架（StreamingResponse + 15s 心跳，Phase 2-3 替换事件类型）
  - `app/core/trace_recorder.py` — Trace 追踪器（Pipeline 七阶段计时 + JSON 字段）
  - `app/pipeline/bm25.py` — BM25 核心轻量版（72 行纯内存计算，不复用 DocMind ~686 行版）
  - `app/models/_types.py` + `app/core/database.py` — 时区策略（UTCDateTime + 四层 UTC，Phase 1 脚手架已提前完成）
- `requirements.txt` 新增依赖：jieba、rank-bm25、bcrypt
- `config.py` 新增配置项：LLM_FLASH_MODEL、Token 估算参数、Rerank BM25 参数、Pipeline 重试次数、SSE 心跳间隔
- **INFRASTRUCTURE_REUSE.md 遗漏补充**：新增 5 个遗漏的基础设施模块文档：
  - §1.3 `rate_limit_middleware.py` — 限流中间件（Phase 4 激活，代码提前就位）
  - §3.4 `redis_client.py` — Redis 同步/异步双客户端（Phase 2 Celery + SSE Bridge 依赖）
  - §5.3 `logging_config.py` + `request_id_middleware.py` — 结构化日志 + Request ID 链路追踪
  - §5.4 `utils.py` — `escape_like()` SQL LIKE 转义
- **ROADMAP.md §2.3** 新增 7 行：JWT 认证中间件、依赖注入、结构化日志、Request ID 中间件、Redis 客户端、通用工具、限流中间件
- **ROADMAP.md §2.3 基础设施复用落地收尾**：完成剩余 5 个 ⏳ 模块的代码落地（全部直接复制自 DocMind）：
  - `app/core/logging_config.py` — 结构化日志（contextvars + JSONFormatter + RequestIDFilter + setup_logging），零改动
  - `app/middleware/request_id_middleware.py` — Request ID 中间件（生成/透传 X-Request-ID + 注入 contextvars），零改动
  - `app/core/redis_client.py` — Redis 同步/异步双客户端 + Windows ThreadedRedisClient 兼容包装，零改动
  - `app/core/utils.py` — `escape_like()` SQL LIKE 转义，零改动
  - `app/middleware/rate_limit_middleware.py` — 限流中间件（Redis 固定窗口计数器 + Lua 原子脚本），接口组映射调整：`chat`→`research`，移除 `upload`，保留 `login`/`default`。Phase 4 激活，代码提前就位
- `config.py` 新增限流配置项：`RATE_LIMIT_ENABLED` / `RATE_LIMIT_WINDOW_SECONDS` / `RATE_LIMIT_RESEARCH_PER_MINUTE` / `RATE_LIMIT_LOGIN_PER_MINUTE` / `RATE_LIMIT_DEFAULT_PER_MINUTE`（全部默认关闭，Phase 4 激活）

- 项目初始化：创建 ResearchMind 仓库
- 产品需求文档 [PRD.md](PRD.md)
- 架构设计文档 [ARCHITECTURE.md](ARCHITECTURE.md)
- 研究管线设计文档 [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md)
- 接口文档 [API.md](API.md)
- 数据库设计文档 [DATABASE.md](DATABASE.md)
- 基础设施复用清单 [INFRASTRUCTURE_REUSE.md](INFRASTRUCTURE_REUSE.md)
- 版本演进路线 [ROADMAP.md](ROADMAP.md)
- 开发指南 [DEVELOPMENT.md](DEVELOPMENT.md)
- 项目入口 [README.md](../README.md)
- 前端交互设计文档 [FRONTEND.md](FRONTEND.md)
- 前端基础设施复用清单 [INFRASTRUCTURE_REUSE_FRONTEND.md](INFRASTRUCTURE_REUSE_FRONTEND.md)
- 前端 UI 样式规范 [UIDESIGN.md](UIDESIGN.md)（Design Token `--rm-*` 体系，提取自 `ai_studio_code.html` 静态原型）

### Fixed
- API.md §5.3：E3107 `recoverable` 从 `false` 修正为 `true`（与 RESEARCH_PIPELINE.md §8.7/§8.9 一致——Render 失败可复用 Evidence Graph 重渲）
- ARCHITECTURE.md line 77：API.md 交叉引用从 §2 修正为 §3（研究任务接口）
- ROADMAP.md line 20：API.md 交叉引用从 §2 修正为 §3（研究任务接口）
- ARCHITECTURE.md line 195：DATABASE.md 交叉引用从 §3 修正为 §2（表结构）
- 初始化迁移 `7685a032ccd7_init` 执行失败修复：
  - `users.updated_at` 的 `server_default=(UTC_TIMESTAMP()) ON UPDATE UTC_TIMESTAMP()` 为 MySQL 语法错误——`ON UPDATE` 子句引用非 `CURRENT_TIMESTAMP` 表达式须加括号。改用 `CURRENT_TIMESTAMP` + ORM `onupdate`，对齐 docmind 模型层
  - `research_sources.uk_task_url` 此前以全列 `UNIQUE (task_id, url)` 建索引，`url VARCHAR(2048)` 超出 MySQL 3072 字节索引长度限制（错误 1071）。改回 DATABASE.md §2.4 规定的前缀唯一索引 `uk_task_url (task_id, url(255))`

### Changed
- 时区实现统一到 docmind 模型层方案（[DATABASE.md §0](DATABASE.md#0-时区约定)）：
  - 新增 `app/models/_types.py::UTCDateTime` TypeDecorator（impl=`DateTime`，写入转 UTC 剥离 tzinfo / 读取附加 UTC tzinfo），替换原 `DateTime(timezone=True)`
  - 所有 `created_at` / `updated_at` 服务端默认值由 `(UTC_TIMESTAMP())` 改为 `func.current_timestamp()`；`updated_at` 自动更新由 DDL `ON UPDATE` 改为 ORM `onupdate=func.current_timestamp()`
  - `utcnow()` 返回值由 naive UTC 改为 aware UTC datetime，与 `UTCDateTime` 兼容
  - 涉及模型：`user` / `refresh_token` / `research_task` / `research_step` / `research_source` / `evidence_item`
- `research_sources.uk_task_url` 模型声明由 `UniqueConstraint` 改为 `Index(..., unique=True, mysql_length={"url": 255})`，与 DATABASE.md §2.4 前缀索引规格一致
- DATABASE.md §0 时区约定重写：补充 `UTCDateTime` 双向转换说明、`CURRENT_TIMESTAMP` 选择理由、`updated_at` 由 ORM `onupdate` 维护；表结构中 `research_tasks.created_at` / `evidence_items.created_at` 的 `(UTC_TIMESTAMP())` 与 `users.updated_at` 的 DDL `ON UPDATE` 同步移除
- 时区复用规格文档对齐（根因修复：INFRASTRUCTURE_REUSE.md §5.1 原将 DocMind 源标注为 `UTCDateTime`，却把 ResearchMind 实现规格写成 `DateTime(timezone=True)`，与已验证的 docmind 实现矛盾——实现者照文档复刻即引入时区 bug。现以 docmind 实际实现为准统一全部文档）：
  - `INFRASTRUCTURE_REUSE.md §5.1` 重写为唯一权威规格：DocMind 源更正为 `app/models/_types.py::UTCDateTime` + `core/database.py` 的 `SET time_zone='+00:00'`；复用方式为「直接复制，零改动」；明确**禁止**裸 `DateTime`/`DateTime(timezone=True)`/`(UTC_TIMESTAMP())`，并声明本节为时区实现唯一规格、其余文档交叉引用
  - `CLAUDE.md` 时区条款：`ORM DateTime(timezone=True)` → 改为「必须用 `UTCDateTime`，禁止裸 `DateTime`/`DateTime(timezone=True)`，禁止 `(UTC_TIMESTAMP())`」并交叉引用 §5.1
  - `DEVELOPMENT.md §6.2` 四层 UTC 表「后端 (ORM)」行：`DateTime(timezone=True)` → `UTCDateTime` TypeDecorator；§时区规范同步改写并交叉引用 §5.1
  - `ROADMAP.md` 时区策略行：`app/core/database.py — ... + DateTime(timezone=True)` → `app/models/_types.py（UTCDateTime）+ app/core/database.py（SET time_zone='+00:00'）`，交叉引用 §5.1
  - 确认 `.claude/commands/review.md` 评审规则（裸 `DateTime` 视为 🔴 严重问题）本已正确，无需改动

	- 复用基础设施文档全面审计与对齐（根因扩展：时区矛盾是系统性问题——INFRASTRUCTURE_REUSE.md 虚报了 docmind 不存在的功能/组件，导致项目文档描述的复用能力与实际可复制代码不匹配。逐项核查 docmind 源码，修正全部 10 项严重不一致 + 5 项中等问题）：
	  - **INFRASTRUCTURE_REUSE.md 虚报修正**（docs/INFRASTRUCTURE_REUSE.md）：
	    - §2.1 LLM 客户端：`Anthropic SDK` → `OpenAI 兼容 SDK (openai 库)`；去掉"已封装 Anthropic SDK 的 `messages.create()`/`messages.stream()`"虚报；去掉"重试逻辑是通用基础设施"虚报（docmind 零重试代码）；错误处理从 `timeout/rate_limit/auth_error` 修正为仅 `rate_limit`；文件行数 ~150→222
	    - §2.3 Prompt Builder：去掉"单条 Evidence 截断"为 docmind 已有功能的虚报——docmind 的 `prompt_builder.py` 不做逐条截断，仅整条跳过/包含
	    - §3.1 SSE：去掉 `seq` 序号为 docmind 已有功能的虚报（docmind 无 seq 字段）；去掉"重连快照模式"为 docmind 已有功能的虚报（docmind SSE 是单向一次性生成器，无重连/快照）；修正复用范围为仅传输层（StreamingResponse + 心跳 + `event:type\ndata:json` 格式）
	    - §3.2 Trace：去掉"context manager 模式"虚报——docmind 的 `TraceRecorder` 无 `__enter__`/`__exit__`，使用普通对象方法记录模式
	    - §3.3 Reranker：去掉 `RerankInput`/`RerankOutput` 数据类虚报——docmind 不存在这些类，实际使用 `RetrievalOutput`/`RetrievalResult`
	    - §4.1 BM25：`ChromaDB（向量路由）三级缓存` → `进程内 dict + Redis 两层缓存 + MySQL 懒加载回源`；文件行数 ~400→686
	    - §4.2 Sentence Matcher：去掉"改引用格式正则"误标——引用正则在 `evidence_auditor.py`，`sentence_matcher.py` 只有中文标点切句正则；"段落切分"→"句级切分"（以标点符号切句）
	    - §4.4 Evidence Auditor：修正自相矛盾（"改引用格式正则…零改动"），改为"直接复制，零改动——引用格式 `[来源N]` 完全相同"；审计结果改为"ResearchMind 需自行决定"
	    - §1.2 Exceptions：文件行数 ~50→~266；复用方式明确错误码重新编号和 detail 类型扩展为 [Deviation]
	    - 底部汇总表重写：按"可直接复制"/"需改造适配"/"需重写"三类分组，行数/描述全部修正
	  - **项目文档 [Deviation] 标注**：
	    - `API.md §1.2`：新增 [Deviation] 说明 `detail` 为结构化 JSON 对象，与 docmind 基类 `detail: str` 不同，实现时需扩展 `AppException` 构造函数
	    - `API.md §1.4`：新增 [Deviation] 说明认证错误码段从 docmind E5xxx 重新编号为 E1xxx
	    - `ARCHITECTURE.md §4.3`：新增 [Deviation] 标注 `require_admin` 代码示例中 `detail` 传 dict
	    - `ARCHITECTURE.md §5.7`：SSE 事件有序规则明确 `seq` 序号为 ResearchMind 自行设计，非 docmind 已有
	    - `CLAUDE.md` 异常约定：更新为 `detail` 为结构化 JSON 对象，`dict | str` 双类型
	    - `RESEARCH_PIPELINE.md §11.2`：新增 [Deviation] 说明 trace 为成本+计时双模型，与 docmind 纯计时模型不同
	  - **设计原则确立**：
	    - 项目文档（API/ARCHITECTURE/DATABASE/RESEARCH_PIPELINE）是 ResearchMind 的独立设计蓝图，不标注"复用 docmind 设计"
	    - INFRASTRUCTURE_REUSE.md 是施工快照，仅指向可复制的 docmind 源文件，不参与设计决策
	    - 实现细节以 docmind 源码为准，项目文档描述与其一致（零矛盾）。故意改造之处标注 `[Deviation]`

### Deprecated
- 无

### Removed
- 无

### Security
- 无

---

## [0.1.0] — 2026-06-20（设计阶段）

### Added
- 完成全部 7 份设计文档初稿
- 确立文档驱动开发流程与归属矩阵
- 确立 Infrastructure Reuse 策略（从 DocMind 复用 Auth、LLM、异常体系、SSE 流式推送）
