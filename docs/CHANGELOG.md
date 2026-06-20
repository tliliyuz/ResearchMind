# CHANGELOG — 变更日志

> 本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/) 格式。
>
> 版本号使用 [语义化版本](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`。
>
> 分类：`Added`（新增）、`Changed`（变更）、`Deprecated`（弃用）、`Removed`（移除）、`Fixed`（修复）、`Security`（安全修复）。

---

## [Unreleased]

> Phase 1 骨架搭建完成（后端 §2.1-2.4 + 前端 §2.5 ✅，测试 §2.7 待执行）。

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
