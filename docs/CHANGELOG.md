# CHANGELOG — 变更日志

> 本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/) 格式。
>
> 版本号使用 [语义化版本](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`。
>
> 分类：`Added`（新增）、`Changed`（变更）、`Deprecated`（弃用）、`Removed`（移除）、`Fixed`（修复）、`Security`（安全修复）。

---

## [Unreleased]

### Added
- **Celery Worker 崩溃自动恢复机制**待实现：解决 Worker 被 SIGKILL/OOM/断电杀死后任务永久卡在 `running` 的死锁问题。包含：
  - `_run_pipeline()` 三元状态检查（`pending`→正常执行 / `running`→崩溃恢复 / 终态→跳过），修复二元检查导致的跳过执行问题
  - `_start_task()` 新增 `running` 状态预检与崩溃恢复路径（不重复 CAS、不重复 SSE、获取任务级锁）
  - 任务级幂等锁（`rm:task_lock:{task_id}`，TTL=900s），防止多 Worker 并发恢复同一任务
  - `run()` 中 `try/finally` 确保所有退出路径释放任务锁
  - FastAPI `lifespan()` 启动时过时任务自动检测与 re-queue（阈值 1800s = 2× `task_time_limit`）
  - `GET /api/health/workers` 运维端点（Celery `control.ping()` 返回活跃 Worker 列表）
  - 新增 `CeleryWorkerLostException`（E3112，`recoverable=true`）
  - 新增配置项 `STALE_TASK_RECOVERY_SECONDS`（1800s）、`STARTUP_RECOVERY_ENABLED`（True）

### Fixed
- **修复断点续跑后任务状态永久卡在 `running`**：`retry_task()` 只重置 `failed` Step → `pending`，但崩溃残留的 `running` 子 Step 未被处理，导致 `TaskStateResolver._all_steps_terminal()` 返回 False → `resolve()` 返回当前状态 `running` → `_finalize_task` 的 CAS `SET status='running' WHERE status='running'` 无操作，状态无法变更。修复：(1) `retry_task()` 新增三步清理：崩溃残留 `running` → `failed`、非终态子 Step → `skipped`、主 Step `failed` → `pending`；(2) `_create_step()` 全部查询增加 `parent_step_id IS NULL` 过滤，确保只匹配主 Step 而非 search/fetch 内部子 Step。
- **修复 Celery Worker 崩溃后任务死锁**：`acks_late=True` 正确重投递后，`_run_pipeline()` 二元幂等检查（`if task.status != "pending"`）错误跳过 `running` 状态任务，导致任务永久卡住。修复为三元检查，`running` 状态进入崩溃恢复路径。
- **修复进度条百分比与步骤数不一致（第 6 步显示 33% 而非 ~86%）**：回退 🟡9 的动态 `total_steps` 扩展逻辑。根因是 `_update_total_steps_on_completion` 将分母改为子步骤总数（如 18），但分子 `completed_steps` 仍按 Phase 维度计数（6），导致 `6/18≈33%`。修复：(1) `research_service.create_task()` 中 `total_steps` 恢复为 `len(PHASE_ORDER)`=7；(2) 移除 `_update_total_steps_on_completion` 方法及其调用；(3) `_start_task` 中增加安全修正——对旧任务自动将 `total_steps` 修正为 7，避免已创建任务残留动态值。
- **Phase3 批次 B 规范修复（🟡1-🟡31，对应 REVIEW_FIX_PLAN.md §4）**——后端 19 项 + 前端 7 项 + 测试 3 项 + 文档 2 项规范化修复：
  - **后端规范化（🟡1-🟡19）**：
    - 🟡1: `PipelineOrchestrator._get_handler()` 将 7 个 Phase handler 的延迟导入移至模块顶部，消除函数内局部导入
    - 🟡2: 移除 `app/pipeline/fetcher.py` 和 `app/models/research_source.py` 中的重复 import 语句
    - 🟡3: `delete_task` bulk `sa_delete` 标注 `[Deviation]`（SQLite 驱动限制），同步更新 `DATABASE.md §4` 外键策略
    - 🟡4: `GET /api/research` 的 `keyword` 参数补充到 `API.md §3.1` 查询参数表；`status` 参数使用 Pydantic 枚举校验
    - 🟡5: topic 为空改为抛 `InvalidRequirementsException`，不再抛 `TopicTooLongException`
    - 🟡6: `require_admin` 非 admin 返回 `E2009 AdminRequired`，与 `ARCHITECTURE.md §4.3` 对齐
    - 🟡7: `_build_snapshot` 中 step 摘要补充 `completed_at` 字段
    - 🟡8: `cancel_task` 成功后主动发布 `task.canceled` SSE 事件
    - 🟡9: `total_steps` 按实际阶段数动态计算（1 planning + n sub_questions + m fetch URLs + 4 fixed phases），不再固定为 7 `[已回退]`——导致进度百分比错配（6/18=33%），已回退为固定分母 7。`pipeline_orchestrator._start_task` 增加安全修正，对旧任务自动将残留动态值修正为 7。
    - 🟡10: 拆分 `task.total_sources` 与 `task.total_evidence` 语义：`total_sources` = Search 去重后 URL 数，`total_evidence` = Rerank 后有效证据数
    - 🟡11: 各阶段重试次数语义统一为「初始 1 次 + max_retries 次」
    - 🟡12: Token 估算工具 `token_counter.py` 接入 Rerank/Synthesis/Render Prompt 构建
    - 🟡13: Render Prompt 按 `RESEARCH_PIPELINE.md §8.3/§8.4` 在 Section 末尾列出来源
    - 🟡14: Search 阶段去重后结果 < 3 时发布 `task.warning`，按 `tavily_score` 截断至 25 条
    - 🟡15: `total_cost_usd` 计入 Tavily Search / HTTP Fetch 成本并在 `CHANGELOG.md` 标注 `[Deviation]`（Phase 3 简化估算模型）
    - 🟡16: Evidence Graph 作为独立持久化资产，标注 `[Deviation]`（Phase 3 仍用 JSON 存储）
    - 🟡17: `task.total_evidence` 改为先清空再写入，消除累加重复计数风险
    - 🟡18: `TraceRecorder` 统一接收 `int` 类型 `user_id`，移除 `str()` 转换
    - 🟡19: 移除 `PipelineOrchestrator` 中 `inspect.isawaitable` 检查，改为真实 ORM 调用
  - **前端规范化（🟡20-🟡26）**：
    - 🟡20: `style` 属性覆盖改为 CSS class + Design Token 变量（`ResearchPage.vue`、`HistoryPage.vue`）
    - 🟡21: `💡` emoji 替换为 Font Awesome 6 `fa-lightbulb` 图标
    - 🟡22: 15+ 个 Vue/CSS 文件中硬编码颜色值全部替换为 `--rm-*` 语义 Design Token（`PipelineProgress.vue` / `StepLog.vue` / `RunningHeader.vue` / `ReportArticle.vue` / `EvidencePanel.vue` / `TracePanel.vue` / `FailedView.vue` / `TypeCard.vue` / `ExampleCard.vue` / `CheckpointBanner.vue` / `LoginPage.vue` 等）`[StepLog+PipelineProgress 已回退]`——`--rm-bg-dark-card` 等变量未写入 `global.css`，导致终端面板变白，已回退为硬编码颜色。
    - 🟡23: 硬编码间距/圆角/字号/行高替换为 `--rm-space-*` / `--rm-radius-*` / `--rm-text-*` / `--rm-leading-*` Token（`HistoryPage.vue` / `SectionNav.vue` / `Sidebar.vue` / `EvidencePanel.vue` / `ReportArticle.vue` / `TracePanel.vue` / `FailedView.vue` / `global.css`）
    - 🟡24: `global.css` 中 `--rm-accent` / `--rm-accent-light` 补充进 `UIDESIGN.md §1` CSS 变量定义，保持文档与代码一致
    - 🟡25: `sse.js` 注释中退避策略 `1s/2s/4s/8s` 修正为 `1s/2s/4s`，与 `FRONTEND.md §8.1` 一致
    - 🟡26: `EvidencePanel.vue` 中 `fa-external-link-alt` → `fa-up-right-from-square`（FA6 正确命名）
  - **测试规范化（🟡27-🟡29）**：
    - 🟡27: 弱断言全部替换为强断言：`>= 1`/`> 0` → 精确值（如 `len(skip_phases) == 6`、`cost_usd == 0.000609`、`total_cost_usd == 0.006628`）；`.toBeDefined()`/`.toBeGreaterThan(0)` → 精确值（如 `stepLogs.length === 3`）
    - 🟡28: 测试函数内局部导入全部移至模块顶部（`test_pipeline_orchestrator.py` 8 处、`test_research_service.py` 1 处）
    - 🟡29: 异常捕获由 `pytest.raises(Exception)` 改为 `pytest.raises(ValidationError)`（`test_research_service.py` 2 处）
  - **文档规范化（🟡30-🟡31）**：
    - 🟡30: `API.md` 补充 `keyword` 查询参数说明；`DATABASE.md` 更新最后修改日期为 2026-06-28
    - 🟡31: `DATABASE.md §4` 新增 `[Deviation]` 说明 `delete_task` bulk `sa_delete` 的原因与影响
  - **测试结果**：后端 `pytest tests/unit/ -v` 全部通过；前端 `npm run test` 全部通过

### Changed
- **TESTING_STRATEGY.md 记录 Phase 3 评估基线（§11.6.3-§11.6.5）**：写入三轮人工评估聚合结果（9 条记录，总体均分 3.81，最低维度为综合质量 3.44）、系统可靠性基线（Task Completion Rate 100%、LLM Call Success Rate 100%）以及单任务检索评估示例（LLM Observability，Search Coverage/Recall@5 100%、Fetch Success Rate 77.27%、Rerank Mean 0.775），并附与 §11.3 / §11.4.5 目标的达标对比。
- **人工评估轮次定义对齐 sample（TESTING_STRATEGY.md §11.4.3 / §11.4.4）**：将每轮样本量从 9 题修正为 3 题、总样本量为 9 题；轮次表从 2 轮扩展为 3 轮，分别对应技术趋势 / 政策法规 / 产品/方案对比三类主题领域，与 `app/evaluation/eval_question_sample.md` 及 `eval/manual/round{N}/` 目录结构一致。
- **人工评估目录加载与聚合**：`app/evaluation/manual.py` 新增 `load_manual_records()` 与 `load_all_manual_rounds()`，支持从 `eval/manual/round{N}/` 读取单个对象或对象数组形式的 JSON 记录，并支持聚合所有 `round*` 子目录；`scripts/eval_offline.py` 新增 `--manual-round` 与 `--manual-all-rounds` 参数输出聚合结果；`tests/unit/evaluation/test_manual.py` 补充 `TestLoadManualRecords` 与 `TestLoadAllManualRounds` 覆盖单文件、数组文件、无效 JSON、校验失败、多轮加载、非 round 目录过滤、目录不存在等分支。
- **HistoryPage 列表列合并（FRONTEND.md §5.1 / §5.2）**：删除「证据数」列，仅保留「来源数」列；该列实际取 `total_evidence` 值，与用户侧「来源」即 Evidence Graph 内部「证据」的概念统一。
- **前端用户侧文案统一：所有面向用户的「证据」改为「来源」**：
  - 运行态阶段名：`证据图谱` → `来源图谱`（`frontend/src/utils/phase.js`）
  - 运行态日志：`task.completed` 消息改为「研究完成！共 N 个参考来源」；后端生成给前端展示的 Synthesis / Evidence Graph 阶段 label 同步改为「来源」
  - 完成态面板：`ReportViewer.vue` 右侧面板标题 `Evidence Graph` → `来源图谱`
  - 错误文案：`E3103` / `E3106` 用户可见 message / error_description 中的「证据」改为「来源」
  - 文档同步：`FRONTEND.md`、`UIDESIGN.md` 中所有用户视角的「证据图谱 / 证据卡片 / 证据 N」改为「来源图谱 / 来源卡片 / 来源 N」
- **前端 UI/UX 优化（FRONTEND.md §4.4-§5.4）**：
  - 报告页三栏布局：章节导航固定 `160px`；报告正文展开态 `620px`、收起态（`body.sidebar-collapsed`）`800px`；Evidence/Trace 面板展开态 `184px`、收起态 `194px`。[Deviation]
  - Pipeline 进度条：Planning 阶段显示「任务规划中…」，完成后恢复百分比与步骤数。
  - 阶段标签中文化（任务规划 / 搜索 / 抓取 / 重排 / 综合 / 来源图谱 / 报告渲染）。
  - Evidence Graph 面板：来源标题可点击跳转新标签页，编号统一为「来源 N」。
  - HistoryPage 列表状态与侧边栏解耦：使用本地 `historyList` / `historyTotal` / `historyLoading`；新建研究按钮先 `clearCurrent()` 再跳转。[Deviation]
  - 失败视图居中显示，错误信息保留换行与滚动，并支持解析 JSON 字符串提取 `message` / `error_description`。

### Fixed
- **Phase3 代码审查 A 批次修复（🔴 合并阻塞项，对应 REVIEW_FIX_PLAN.md 3.1-3.6）**：
  - **后端并发与事务一致性**：
    - `_start_task` 改为返回 `bool` 的 CAS 更新：`UPDATE research_tasks SET status='running' WHERE status='pending'`，`rowcount==0` 时 `run()` 直接退出，阻止并发 Worker 重复执行同一任务。
    - `_handle_fatal_error` 先检查 `session.is_active` 再 `rollback()`，避免在 session 已失效时撤销已 flush 的 Step 失败状态；关键属性在 rollback 前缓存到本地变量，杜绝 `MissingGreenlet` 二次崩溃。
    - `_emergency_fail` 改为 CAS 更新：`UPDATE ... WHERE status IN ('pending','running')`，终态任务（completed/canceled）不被覆盖；新增 `recoverable` 参数，兜底 `except` 通过 `extract_recoverable_from_exception()` 保留原异常可恢复语义。
  - **SSE 与状态接口**：
    - `/stream` 端点对终态任务（completed/failed/canceled）仅推送 `task.status.snapshot` 后立即关闭连接，不再进入 Redis 订阅循环，避免客户端对已结束任务无效挂起。
    - `require_task_accessible` 改为 `select(ResearchTask).options(selectinload(ResearchTask.steps))` 显式预加载；`_build_snapshot` 改为显式查询 `research_steps` 表，字段名 `step_id` 修正为 `id`，与 `API.md §3.6` 示例对齐。
    - `SSEBridge.publish` 由同步改为异步 `async def publish`，内部通过 `asyncio.to_thread` 调用同步 Redis 客户端，Celery Worker 事件循环不再被阻塞；所有调用点统一改为 `await self._sse.publish(...)`。
  - **安全与 Fetch 限制**：
    - 修复 SSRF 绕过：新增 `app/utils/url_safety.py::check_url_safety()`，使用 `socket.getaddrinfo()` 解析全部 IPv4/IPv6 地址，覆盖 `127.0.0.0/8`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`、`0.0.0.0/8`、`::1/128`、`fc00::/7`、`fe80::/10`、`ff00::/8`；Fetch 关闭 `follow_redirects=True`，改为手动跟随并对每个跳转目标复用安全检查。
    - Fetch 阶段新增流式响应体读取，累计超过 `FETCH_MAX_BODY_SIZE`（2 MB）即标记为 `blocked`；每任务 URL 数硬上限 `FETCH_MAX_URLS_PER_TASK=15`，超出部分写入 step output `truncated` 字段。
  - **错误码与迁移**：
    - `E3999` 错误码登记入 `docs/API.md §1.4` 速查表与 §5.3 完整错误码表，描述为「未预期的内部错误（Pipeline Worker 崩溃/未捕获异常兜底）」。
    - Alembic 迁移 `c02701951a41` 将 `sa.DateTime(timezone=True)` 改为 `sa.DateTime()`，与 `UTCDateTime` 底层类型一致并补充 UTC 注释。
  - **依赖注入健壮性**：
    - `get_current_user` 使用 `getattr(request.state, "user_id", None)`，缺失或异常时抛 `InvalidTokenException(E1004)` 返回 401，避免 `AttributeError` 导致 500。
  - **前端安全与功能**：
    - `frontend/src/utils/markdown.js` 移除 `wrapCodeBlocks` 中的内联 `onclick` 与 `encodeURIComponent`，改为在渲染后的高亮 HTML 中提取原始代码文本并存入隐藏 `<textarea class="code-raw">`；`ReportArticle.vue` 通过事件委托读取 textarea value 写入剪贴板，消除 XSS 与 URL 编码污染。
  - **测试覆盖**：新增/更新 `tests/unit/services/test_pipeline_orchestrator.py`（CAS 失败、fatal error 状态一致性）、`tests/unit/tasks/test_research_task.py`（`_emergency_fail` CAS + recoverable）、`tests/unit/api/test_sse.py`（终态 snapshot 关闭连接、`id` 字段）、`tests/unit/pipeline/test_fetcher.py`（SSRF 多 A 记录/IPv6/重定向/2MB/15 URL）、`tests/unit/test_dependencies.py`（`get_current_user` 缺失 state）、`frontend/src/utils/markdown.test.js`（无内联 onclick/无 URL 编码/textarea 原始代码），并批量将 SSE mock 由 `MagicMock` 替换为 `AsyncMock`。
- **`app/evaluation/__init__.py` 移除未实现模块导入**：`question_bank` 模块尚未创建，但 `__init__.py` 已导出其符号，导致导入 `app.evaluation` 报 `ModuleNotFoundError`。暂时移除相关导入与 `__all__` 条目，使现有评估功能可正常导入；题目样本库功能待后续实现时再加回。
- **报告页右侧面板固定分区与 Trace 常驻底部修复**：[Deviation/修复] 由于 `.research-page` 未声明高度，`.completed-state` / `.report-viewer` / `.report-body` 的 `height: 100%` / `flex: 1` 失去参照，导致来源过多时右侧面板无限增长、Trace 摘要被压到最底部。修复：`ResearchPage.vue` 增加 `.research-page { height: 100% }` 贯通高度链；`ReportViewer.vue` 将 `.report-side-panel` 改为 `overflow: hidden` 并给 `EvidencePanel`/`TracePanel` 分配固定 flex 分区；`EvidencePanel.vue` 移除 `flex-shrink: 0` 与 `justify-content: space-between`，增加 `min-height: 0`，使来源列表在侧栏上半部分内部滚动，Trace 始终可见。
- **报告页三栏布局回归修复**：SectionNav / ReportArticle / EvidencePanel / ReportViewer 通过压缩内边距与增加卡片溢出约束适配窄栏，不再缩小字体导致不可读；Evidence 卡片改为「窄而长」垂直滚动，避免撑破容器。[Deviation]
- **进度条分母跳变修复**：`searcher.py` / `fetcher.py` 创建子 step 时不再递增 `task.total_steps`；前端 `task.js` 移除 `step.completed` 本地进度累加；`PipelineProgress.vue` 维护 `maxTotalSeen` 防御分母收缩，杜绝 `100% → 33%` 回退。[Deviation]
- **Trace 搜索/抓取/证据图谱无耗时修复**：`PipelineOrchestrator._complete_step` 新增 Search / Fetch / Evidence Graph 的 `TraceRecorder` 埋点；`TracePanel.vue` 字段与后端对齐，七阶段均显示耗时与摘要数字。[Deviation]
- **失败视图居中修复**：`ResearchPage.vue` 的 `.completed-state` 仅对 `report-viewer` / `state-placeholder` 拉伸，`FailedView` / `CanceledView` 卡片加 `margin: auto` 兜底居中。
- **失败信息 JSON 字符串修复**：`FailedView.vue` 的 `displayMessage` 支持去掉 `500: ` 前缀、解析单引号 JSON、提取 `message` / `error_description` / `detail.message`。
- **Step 日志细化与切页丢失修复**：`taskStore.js` 修正 `buildLogsFromSnapshot` 字段名并为 step 事件写入 `message`；`StepLog.vue` 消息兜底；`ResearchPage.vue` 切回运行态时自动重连 SSE。[Deviation]
- Trace 执行摘要无值：在 `reportStore.normalize()` 中将后端嵌套 trace 扁平化为 `TracePanel` 期望的结构。[Deviation]
- 章节导航点击无滚动：`ReportArticle.vue` 监听 `selectedSectionId` 并平滑滚动到对应 section。
- 新建任务后侧边栏不刷新：`taskStore.createTask()` 成功后刷新最近任务列表。
- 前端测试对齐最新 UI/UX 修复：`SectionNav` / `EvidencePanel` / `TracePanel` / `FailedView` / `CanceledView` / `PipelineProgress` / `StepLog` / `ResearchPage` / `taskStore.sse` 补充/更新断言，前端测试 222 用例全绿。
- **报告页三栏布局第三轮修复**：展开态三栏宽度为章节导航 160px + 报告正文 620px + Evidence/Trace 面板 184px；`body.sidebar-collapsed` 下报告正文加宽至 800px、右面板加宽至 194px，以释放更多主内容区空间。`EvidencePanel.vue` 与 `ReportViewer.vue` 的 `:deep(.evidence-panel)` 改为 `width: 100%` 由 grid 列宽控制，避免 Evidence 内容因 `width: auto` 撑出容器或偏右隐藏。[Deviation]
- **进度条分母固定为七阶段**：`research_service.create_task()` 初始化 `task.total_steps = len(PHASE_ORDER)`；`PipelineOrchestrator._create_step()` 不再递增 `task.total_steps`；前端 `PipelineProgress.vue` 分母固定为 7，杜绝创建任务即 100% 与执行中分母跳变到 30 的问题。[Deviation]
- **失败信息 JSON 字符串第三轮修复**：`FailedView.vue` 的 `displayMessage` 改为正则优先提取最外层 `message` / `error_description`，避免嵌套单引号 JSON 导致 `JSON.parse` 失败后整串外露。[Deviation]
- **Step 日志切页后时间戳与细化内容修复**：后端 `_build_snapshot()` 增加 `started_at` 与 `progress_label`；前端 `buildLogsFromSnapshot()` 恢复 `timestamp` / `icon` / `progress.label`；`upsertStepLog` / `updateStepLog` 为无时间戳日志补充当前时间；`StepLog.vue` 对 completed/skipped/failed 状态也显示 progress label；后端 `step.started` SSE 事件携带 `timestamp`。[Deviation]
- 前端测试对齐第三轮修复：`PipelineProgress` / `FailedView` / `taskStore.sse` 更新断言，前端测试 223 用例全绿；后端 `test_research_service.py` 更新 total_steps 断言。
- **失败视图布局与错误信息一致性修复**：`FailedView.vue` 错误消息改为居中、卡片加宽至 `560px`、增加垂直间距；新增 `.failed-detail` 区域展示异常类名等多行补充信息；`standardErrorCode` 仅展示 E 系列标准码，异常类名下沉到 detail。`taskStore.js` 的 `fetchDetail()` 按 API.md 从 `data.error` 嵌套对象读取错误信息，并兼容顶层字段；`task.failed` SSE 事件处理增加 `normalizeErrorCode`，在 `error_type` 为异常类名时从描述中提取标准错误码。`FailedView.test.js` / `taskStore.test.js` 补充对应断言，前端测试 230 用例全绿。[Deviation]
- **侧边栏最近任务滚动修复**：`Sidebar.vue` 显式设置 `height: 100%` / `max-height: 100vh`；`.history-section` 拆分为 `.history-section-scroll` + `.history-view-all`，独立 `overflow-y: auto` 与 `overscroll-behavior: contain`，避免滚动事件穿透；新增 Webkit 细滚动条样式与底部「查看全部历史任务」链接。
- **侧边栏最近任务数量修复**：`Sidebar.vue` 挂载时 `fetchList` 的 `page_size` 从 `10` 调整到 `50`，确保「今天 / 昨天 / 近 7 天」时间分组不会因为今日任务过多而被截断，滚动条可正常滚动到更早分组。
- **取消视图布局同步修复**：`CanceledView.vue` 卡片加宽至 `560px`、padding 与图标尺寸对齐失败页、按钮尺寸统一，避免取消状态卡片与失败页视觉不一致。[Deviation]
- **失败/取消视图固定卡片布局修复**：`FailedView.vue` 与 `CanceledView.vue` 改为固定宽度 `560px`、最小高度 `520px`；卡片内部拆分为 `.card-body`（错误内容垂直居中，过长时独立滚动）与 `.card-footer`（「返回新建研究」按钮固定在底部），两页结构一致，避免弹性布局导致视觉大小不一。[Deviation]
- **切页后运行态日志样式统一修复**：`taskStore.js` 的 `fetchDetail()` 在同一任务重新加载时保留已有 `stepLogs`；`buildLogsFromSnapshot()` 按 phase 分组并插入「进入阶段 / 阶段完成」日志，合并快照状态与现有 rich step 日志，使 SSE 快照/重连后的日志样式接近实时 SSE 事件渲染效果。
- **取消页已完成阶段切页后丢失修复**：`taskStore.js` 的 `fetchDetail()` 对 `canceled` / `failed` / `completed` / `partially_completed` 等终态任务调用 `GET /api/research/{task_id}/state` 获取含 `steps` 的快照，重建 `phaseStates` / `phaseDurations` / `stepLogs`；`frontend/src/utils/phase.js` 新增 `buildPhaseStatesFromSteps()` 从 completed steps 推断各 phase 状态，保证取消页「已完成阶段」在切页/重载后仍一致显示。
- **侧边栏最近任务状态图标实时刷新修复**：`taskStore.js` 新增 `watch` 监听 `current`，在 SSE 事件、`cancelTask()`、`fetchDetail()` 等场景下自动同步 `status` / `current_phase` / `completed_at` 回 `taskList`，侧边栏图标无需刷新页面即可随任务状态变化（pending → running → completed）。
- **侧边栏无限滚动到底仍显示「加载更多」修复**：`taskStore.js` 的 `hasMore` 改为优先信任后端 `total`；`total` 异常时根据最后一页是否满载兜底，避免总数等于整页数量或空页返回时仍提示继续滚动。

### Added
- **Pipeline 端到端集成测试（全链路）**：新增 `tests/integration/test_pipeline_full.py`，使用真实 SQLite 测试数据库 + Mock 外部 API（Tavily / HTTP / LLM），通过 `PipelineOrchestrator` 跑通 Planning→Search→Fetch→Rerank→Synthesis→EvidenceGraph→Render 全 7 阶段，验证 SSE 事件序列完整性与 Report 产出（`report_sections` / `section_evidence` / `evidence_items.used_in_sections`）。
- 侧边栏「最近任务」支持无限滚动加载：`taskStore` 新增 `append` 模式、`hasMore`、`fetchMore()`；`Sidebar.vue` 滚动距底部 `40px` 且仍有数据时自动加载下一页，底部显示「加载中…」/「没有更多任务了」提示；首次加载与新建任务后重置为第 1 页并回到顶部。
- CSS Design Token 新增 `--rm-report-article-width` / `--rm-evidence-highlight-*` / `--rm-evidence-flash-border`；`body.sidebar-collapsed` 下 `--rm-report-article-width` 加宽至 `800px`、`--rm-evidence-panel-width` 加宽至 `194px`，章节导航保持 `160px`。
- `TracePanel.vue` 新增各阶段耗时比例进度条，以总耗时为 100% 显示单阶段耗时占比。
- **离线 Pipeline 评估与人工评估策略**：
  - 新增 `docs/TESTING_STRATEGY.md` §11「检索评估与人工评估策略」，定义 Search Recall / Fetch Success Rate / Rerank Relevance 指标公式与 v1.0 目标值，以及人工评估 4 维度、1-5 Likert 量表、抽样策略与轮次安排。
  - 新增 `app/evaluation/` 模块：`search_eval.py` / `fetch_eval.py` / `rerank_eval.py` 实现三阶段指标计算；`loader.py` / `aggregator.py` 支持按 `task_id` 生成完整 `PipelineEvaluationReport` 并与目标值对比；`manual.py` 支持人工评估 JSON 记录校验、聚合与轮次对比；`cli.py` 提供 argparse CLI。
  - 新增 `scripts/eval_offline.py` 离线评估脚本，支持 `--task-id`、`--all-completed`、`--limit`、`--json`。
  - 新增测试：`tests/unit/evaluation/test_search_eval.py`、`test_fetch_eval.py`、`test_rerank_eval.py`、`test_aggregator.py`、`test_manual.py`；`tests/integration/test_pipeline_evaluation.py` 复用全链路 Mock 验证 Pipeline 完成后评估指标正确。
  - 更新 `docs/ROADMAP.md` §4.9，将 Phase 3「人工报告质量评估（第 1 轮）」与「离线 Pipeline 评估」标为完成，并交叉引用 TESTING_STRATEGY.md。

- **Phase 4 §5.1 Execution Context + 断点续跑（ROADMAP §5.1）**——失败任务从最后 checkpoint 恢复执行：
  - `app/core/exceptions.py` — 扩展 `TaskStatusConflictException`：`detail` 支持结构化 `current_status` / `allowed_statuses` 字段，Retry API 返回精确冲突信息
  - `app/schemas/research.py` — 新增 `ResumeFromSchema`（`phase` / `last_completed_step_id` / `next_step_type`）与 `ResearchRetryResponse`
  - `app/services/research_service.py` — 新增 `retry_task()`：前置校验（`RETRY_ALLOWED_STATUSES = frozenset({"failed", "partially_completed", "canceled"})` + `recoverable=true`）→ 重置所有 failed Step 为 pending → CAS 更新 task status（`WHERE status = old_value`）→ 清空 error 字段 → 从 `execution_context` 构建 `resume_from`；新增常量 `RETRY_ALLOWED_STATUSES`
  - `app/api/research.py` — 新增 `POST /api/research/{task_id}/retry`（202），遵循 Service→commit→Celery dispatch 模式；`require_task_accessible` 权限校验
  - `app/services/pipeline_orchestrator.py` — `_create_step()` 新增三层复用：已终态 Step（completed/skipped）直接返回 → 未终态 Step（pending/running）崩溃恢复复用 → 均无匹配时新建。Retry 场景下 failed Step 已被 `retry_task()` 重置为 pending，`_create_step` 自动新建 Step 重新执行
  - 设计决策（非 Deviation）：不新增 `"retrying"` task 状态（复用 `pending→running` 流程）；不新增 `retry_count` 列（v1.0 step 级已有）；Evidence 只追加不覆盖（`evidence_items` 表无 UNIQUE 约束，天然支持）
  - 测试覆盖 35 用例：`test_research_service.py` +15（retry_task 正常/状态非法/recoverable=false/CAS 冲突/failed step 重置/resume_from 正确性/RETRY_ALLOWED_STATUSES 常量）/ `test_pipeline_orchestrator.py` +9（_create_step completed/skipped/pending 复用 + failed 不复用 + 无已存在 step 新建 + **ExecutionContext 原子更新 4 用例**：_complete_step 原子写入/连续 phase 递进/崩溃恢复 resume_from 构造/失败时 execution_context 不部分更新）/ `test_research_api.py` +11（POST /retry 202×3/E2001/E2002/admin 可 retry 他人/E2003×4/failed step 重置验证）

> Phase 1 骨架搭建完成（后端 §2.1-2.4 + 前端 §2.5 ✅，测试 §2.7 待执行）。
> Phase 2.3.1 研究任务 CRUD + 状态机完成（ROADMAP §3.1 ✅）。
> Phase 2.3.2 Celery 异步 Pipeline 编排基础设施完成（ROADMAP §3.2 ✅）。
> Phase 2.3.3-§3.6 Pipeline 前半段完成：Planning（LLM）+ Search（Tavily）+ Fetch（HTTP+trafilatura）+ SSE 端点（ROADMAP §3.3-§3.6 ✅）。
> Phase 2 §3.7 前端实现完成：ResearchPage + HistoryPage + Sidebar 历史任务 + SSE 框架（ROADMAP §3.7 ✅）。
> Phase 2 §3.9 测试完成：Celery 幂等锁 + 5 个前端测试全绿，Phase 2 全部关闭准入 Phase 3（ROADMAP §3.9 ✅）。
> Phase 3 §4.1 Rerank ✅ | §4.2 Synthesis ✅ | §4.3 Evidence Graph Build ✅ | §4.4 Report Render ✅ | §4.5 Cancel 基础实现 ✅ | §4.6 成本追踪 ✅ | §4.7 前端运行态进度可视化 + 完成态报告查看 ✅。

### Added
- **Phase 3 §4.7 前端运行态进度可视化 + 完成态报告查看（ROADMAP §4.7 / FRONTEND.md §4.4-§4.5 / UIDESIGN.md §4.9-§4.14）**：
  - `frontend/src/api/research.js` — 新增 `getReport(taskId)` 封装 `GET /api/research/{task_id}/report`
  - `frontend/src/utils/phase.js` — 新建 Pipeline 七阶段元数据与 key 归一化：`PHASE_ORDER` / `PHASE_LABELS` / `PHASE_ICONS` / `normalizePhaseKey()` / `buildPhaseStates()`，统一 SSE 长 key（searching/fetching/...）与 UI 短 key（search/fetch/...）
  - `frontend/src/utils/format.js` — 新增 `formatElapsedTime(ms)`：<1h 返回 `MM:SS`，≥1h 返回 `HH:MM:SS`
  - `frontend/src/stores/report.js` — 新建 Pinia Store：管理报告数据、章节导航、Evidence 双向高亮、按章节筛选；Actions `fetch()` / `selectSection()` / `highlightEvidence()` / `setEvidenceFilter()` / `clear()`；Computed `filteredEvidence`
  - `frontend/src/stores/task.js` — **扩展运行态实时状态**：新增 `stepLogs` / `phaseStates` / `phaseDurations` / `lastCheckpoint` / `warnings` / `completedStepIds`；补全 `handleSSEEvent` 对 15 种 SSE 事件的处理（phase.started/completed、step.started/progress/completed/failed/skipped、checkpoint.saved、task.warning、task.status.snapshot 重建 logs）；新增 `resetRuntimeState()` / `buildLogsFromSnapshot()`
  - `frontend/src/views/ResearchPage.vue` — **重写运行态与完成态 UI**：运行态接入 `RunningHeader` / `PipelineProgress` / `StepLog` / `CheckpointBanner`；完成态接入 `ReportViewer` / `FailedView` / `CanceledView`；新增已用时 `elapsedMs` 定时器
  - 运行态组件（`frontend/src/components/task/`）：
    - `RunningHeader.vue` — 深色顶栏：任务标题、状态标签、当前阶段、已用时计时器、取消按钮
    - `PipelineProgress.vue` — 七阶段横向进度条：done/current/pending 三态 + 渐变进度条 + 阶段耗时
    - `StepLog.vue` — 暗色终端日志面板：SSE 事件追加、自动滚动、sticky「↓ 最新」按钮
    - `CheckpointBanner.vue` — checkpoint.saved 提示横幅
  - 完成态报告组件（`frontend/src/components/report/`）：
    - `ReportViewer.vue` — 三栏布局容器（章节导航 240px + 报告正文 + Evidence/Trace 面板 320px），进入完成态自动 `reportStore.fetch(taskId)`；新增报告加载态：章节导航骨架屏 + 正文区 spinning + Evidence Graph 面板骨架屏
    - `SectionNav.vue` — 章节导航：层级列表、当前高亮、badge 引用计数、点击平滑滚动
    - `ReportArticle.vue` — Markdown 报告正文 + `[来源N]` 引用锚点点击 → EvidencePanel 联动
    - `EvidencePanel.vue` — Evidence Graph 面板：按 `index` 排序、点击高亮正文锚点、按章节筛选、`.flash` 动画
    - `TracePanel.vue` — Trace 摘要折叠面板：七阶段耗时 + 总耗时
    - `FailedView.vue` — 失败视图：错误描述、失败阶段、`recoverable=true` 时展示禁用态「断点续跑」按钮
    - `CanceledView.vue` — 取消视图：已完成阶段摘要 +「返回新建研究」按钮
  - 测试覆盖（前端新增 11 个测试文件 + 扩展 `ResearchPage.test.js`）：
    - `frontend/tests/unit/reportStore.test.js` — ReportStore fetch / selectSection / highlightEvidence / filter / clear（14 用例）
    - `frontend/tests/unit/taskStore.sse.test.js` — SSE 运行态事件映射、step 幂等、snapshot 重建 logs（12 用例）
    - `frontend/tests/components/PipelineProgress.test.js`（6 用例）/ `StepLog.test.js`（5 用例）/ `SectionNav.test.js`（4 用例）/ `ReportArticle.test.js`（3 用例）/ `EvidencePanel.test.js`（4 用例）/ `TracePanel.test.js`（3 用例）/ `FailedView.test.js`（4 用例）/ `CanceledView.test.js`（3 用例）
    - `frontend/tests/components/ResearchPage.test.js` — 扩展运行态/完成态/失败态/取消态切换（4 用例）

### Changed
- **`frontend/src/utils/markdown.js` [Deviation]**： `[来源N]` 渲染的 `data-evidence-index` 由逗号分隔改为空格分隔（如 `data-evidence-index="0 1"`），支持精确 CSS 选择器 `[data-evidence-index~="N"]`。原计划为逗号分隔，见 FRONTEND.md §4.5.3 / UIDESIGN.md §4.12
- **`frontend/src/utils/sse.js` [Deviation/修复]**：重连成功后连接状态由 `reconnecting` 修正为 `connected`，与 FRONTEND.md §8 5 态状态机一致（首次连接 `connecting→connected`，重连成功后也应恢复 `connected`）

### Fixed
- **`frontend/tests/components/HistoryPage.test.js` 搜索防抖测试断言修复**：测试设置 `searchKeyword = '量子'` 后，断言 `getTaskList` 调用参数应包含 `keyword: '量子'`（原断言遗漏 `keyword` 字段导致失败）
- **`app/services/pipeline_orchestrator.py` 修复 flush 后访问 `self._task` 触发 `MissingGreenlet` 的致命错误处理崩溃**：在 `_handle_step_error` / `_check_early_termination` / `_finalize` / `_handle_fatal_error` 中，flush/rollback 前提前读取 `task_id` / `execution_context` / `started_at` / `total_sources` / `total_evidence` / `trace` 等属性；`_build_task_failed_payload` 与 `_get_last_checkpoint` 改为接收本地参数，不再访问 `self._task`。修复 Render 阶段 LLM `Connection error` 导致任务失败时，SSE 发送与状态回滚二次崩溃的问题

### Added
- **Phase 3 §4.6 成本追踪实现（ROADMAP §4.6 / RESEARCH_PIPELINE §11.2）**——LLM token 成本写入 Step 并聚合到 Task Trace：
  - `app/core/cost_tracker.py` — 新建成本计算模块：维护 DeepSeek 模型定价字典（`deepseek-v4-pro` / `deepseek-v4-flash`），`calculate_cost_usd()` 按 cache miss 单价计算并保留 6 位小数，`extract_step_cost()` 从 Step output 提取 token / model / cost（兼容 `prompt_tokens`/`completion_tokens` 与 `usage.*` 备选路径）
  - `app/models/research_step.py` — 新增 `cost` JSON 列，结构 `{input_tokens, output_tokens, estimated_cost_usd, model}`
  - `alembic/versions/fd49212435a6_research_steps_新增_cost_列.py` — 新增迁移脚本，为 `research_steps` 表添加 `cost` 列
  - `app/core/trace_recorder.py` — 扩展成本聚合：新增 `_phase_cost` 与 `_accumulate_cost()`，为 `record_planning` / `record_rerank` / `record_synthesis` / `record_render` 增加 `model` 参数并累加 token / cost；`finish()` 输出新增 `total_tokens` / `total_cost_usd` / `breakdown`
  - `app/services/pipeline_orchestrator.py` — `_complete_step()` 在 Step output 写入后、flush 前设置 `step.cost`；扩展现有 render-only 埋点，为 planning / rerank / synthesis / render 四个 LLM 阶段分别调用对应 `record_*` 方法
  - `docs/DATABASE.md` §2.3 — 更新 `research_steps` 表 DDL 与字段说明，新增 `cost JSON` 定义
  - 测试覆盖：`tests/unit/core/test_cost_tracker.py`（4 用例）+ `tests/unit/services/test_pipeline_orchestrator.py`（追加 Step cost 写入与 Trace 聚合断言）

- **Phase 3 §4.5 Cancel 基础实现（ROADMAP §4.5 / API.md §3.2）**——任务取消接口与 Orchestrator 检测修复：
  - `app/api/research.py` — 新增 `POST /api/research/{task_id}/cancel` 端点，返回 `{task_id, status: "canceled"}`，错误码 E2001/E2002/E2003
  - `app/services/research_service.py` — 新增 `cancel_task()`：终态校验（completed/failed/partially_completed/canceled）抛 E2003；CAS 更新 `status=canceled` + `completed_at`；CAS 失败同样抛 E2003
  - `app/schemas/research.py` — 新增 `ResearchCancelResponse` Schema
  - `app/services/pipeline_orchestrator.py` — 修复取消检测：Phase 循环检查 `status == "canceled"`（而非不存在的 `"canceling"`），发送 `EVENT_TASK_CANCELED` 并补设 `completed_at`
  - 测试覆盖：`tests/unit/api/test_research.py` + `tests/unit/services/test_research_service.py`（追加 cancel 正常/终态冲突/权限/admin/CAS 并发共 8+ 用例）

### Changed
- **Phase 3 §4.5/§4.6 实现偏差标注 `[Deviation]`**：
  - Cancel 不引入 `canceling` 中间态：API 直接 CAS 更新 `status=canceled`，Orchestrator 在 Phase 边界检测 `canceled` 后停止（API.md §3.2 原述"Worker 收到中断信号后保存当前 checkpoint"，MVP 简化为在下一 Phase 前停止）
  - 成本追踪 MVP 仅计入 LLM token 成本：Search（Tavily）/ Fetch（HTTP）等第三方服务成本暂不计入 `total_cost_usd`，与 RESEARCH_PIPELINE.md §11.2 "Search/Fetch 成本计入 total_cost_usd" 不同
  - DeepSeek 定价使用 cache miss 价格作为保守估算

- **Phase 3 §4.4 Report Render 阶段实现（ROADMAP §4.4 / RESEARCH_PIPELINE §8）**——Evidence Graph 渲染为 Markdown 报告：
  - `app/pipeline/renderer.py` — Report Render 阶段完整实现（~360 行）：从最新 completed Evidence Graph Step 读取 `output["graph"]`；按 `task_type` 选择模板（`comparison_v1` / `explainer_v1` / `analysis_v1`）；构建 System Prompt（含 topic/task_type/language/模板说明/证据图谱摘要/证据详情）；调用 `deepseek-v4-pro`（`deep_thinking=False`，`temperature=0.5`，`max_tokens=8000`）；从 LLM 输出提取 JSON 并解析为 `RenderSection` 列表；正则提取正文 `[来源N]` 引用，按 `GraphItem.index` 映射到 `source_id` + `evidence_index`，去重排序后持久化到 `report_sections` 与 `section_evidence`；更新 `evidence_items.used_in_sections`；失败策略：LLM 调用/JSON 解析失败重试 1 次（`settings.PIPELINE_RENDER_MAX_RETRIES`），耗尽 → `RenderFailedException(E3107, recoverable=True)`；Section 数量不足不阻断；无引用/非法引用章节标记 `citation_issues=True`；返回 `sections_count`/`citations_count`/`template`/`model`/`retry_count`/`prompt_tokens`/`completion_tokens`/`duration_ms`/`citation_issues`
  - `app/pipeline/evidence_graph.py` — `GraphItem` 新增 `evidence_item_id` 字段并在 `to_dict()` 输出，供 Render 阶段直接更新 `evidence_items.used_in_sections`
  - `app/services/pipeline_orchestrator.py` — `build_default_phase_handlers()` 注册 `render` handler；`_complete_step()` 中对 `render` Step 调用 `TraceRecorder.record_render()` 埋点
  - `app/schemas/research.py` — 新增报告相关 Schema：`ReportSourceSchema` / `ReportSectionSourceSchema` / `ReportSectionSchema` / `ReportSchema` / `ResearchReportResponse`
  - `app/services/research_service.py` — 新增 `get_report()`：校验任务 completed/partially_completed，从 `evidence_graph` Step 读取 graph，按 `sort_order` 查询 `report_sections` 与 `section_evidence`，组装 `ResearchReportResponse`
  - `app/api/research.py` — 新增 `GET /api/research/{task_id}/report` 端点，错误码 E2001/E2002/E2003
  - `tests/unit/pipeline/test_renderer.py` — Render 单元测试（10 用例：正常渲染并持久化 report_sections/section_evidence/used_in_sections / 3 种 task_type 模板分支 / 引用按 evidence_index 去重排序 / 无引用章节标记 citation_issues / 无效 JSON 重试后成功 / 无效 JSON 重试耗尽→E3107 call_count=2 / LLM 异常重试耗尽→E3107 call_count=2 / section 数量不足不阻断 / 越界 index 过滤并标记 citation_issues / 空 Evidence Graph→E3107）
  - `tests/unit/api/test_research.py` — 追加 Report API 测试（4 用例：completed 任务返回完整报告 JSON / 任务不存在→404 E2001 / 无权访问→403 E2002 / 未完成任务→409 E2003）
  - `tests/unit/services/test_research_service.py` — 追加 `get_report` Service 测试（4 用例：completed 返回完整报告 / partially_completed 可获取 / running→E2003 / 无 Evidence Graph Step→E2003）

### Fixed
- **修复 Pipeline 完成后 Task 状态卡在 `running` 的问题**：根因是 `app/services/research_service.py` 在创建任务时已写入一个 `status=pending` 的首个 `planning` Step，但 `app/services/pipeline_orchestrator.py::_run_phase()` 每次执行 planning 时又调用 `_create_step()` 新建一个 planning Step，导致 research_service 预先创建的 Step 永远停留在 `pending`。`TaskStateResolver._all_steps_terminal()` 要求全部 Step 进入终态，这个遗留的 pending Step 使 Resolver 误判为“还有步骤未终态”，最终 CAS 把 task status 写回 `running`。修复后 `_create_step()` 优先查询并复用同一任务同一 phase 下 `status IN ('pending', 'running')` 的已有 Step（按 `started_at` 升序，pending 的 NULL 在最前），无匹配时才新建 Step；这样即可复用 research_service 预先创建的 planning Step，也覆盖 Worker 断点续跑 / 异常重启后遗留的非终态 Step。同步保留 `_load_task_steps()` 显式查询 `research_steps` 表 + `execution_options(populate_existing=True)`，确保 identity map 中过期的 Step 对象被 DB 最新值覆盖；新增 `tests/unit/services/test_pipeline_orchestrator.py::TestPipelineWithRealSession::test_复用research_service创建的pending_planning_step` 真实 DB session 集成测试，验证预先存在的 pending planning Step 被复用且 Task 最终变为 `completed`
- **修复 Celery Worker 事件循环冲突导致的 `Future attached to a different loop`**：`app/tasks/research_task.py` 中 `execute_research_task` 不再使用 `asyncio.run()`（每次任务新建/关闭事件循环），改为通过 `_get_worker_loop()` 获取或创建当前 Worker 进程的持久事件循环，使用 `loop.run_until_complete()` 执行异步 Pipeline；避免 SQLAlchemy async engine 连接池复用旧连接时 Future 绑定到已关闭 loop 的问题
- **`docs/RESEARCH_PIPELINE.md` §8.4 引用锚点示例 [Deviation]**：明确正文中 `[来源N]` 的 `N` 使用 0-based `GraphItem.index`（与 `API.md §3.3` 及前端 `markdown.js` 解析一致），修正原示例中 `[来源1]` 映射到 `evidence_index: 0` 的表述；`section.sources[].id` 仍为 `research_sources.id`，`section.sources[].evidence_index` 存储 `GraphItem.index`
- **修复 Fetch 阶段 `dns_error` 写入 `research_sources.fetch_status` 触发 MySQL `DataError (1265)`**：`app/models/enums.py` 已含 `dns_error`，但数据库层 MySQL ENUM 仍只有 `success/timeout/blocked/empty`。新增 `alembic/versions/8ab6268d8077_research_sources_fetch_status_枚举扩展_dns_.py` 迁移脚本，通过 `op.alter_column` 将 `fetch_status` ENUM 扩展为 `success/timeout/blocked/empty/dns_error`，与模型、设计文档 `DATABASE.md §2.4` 对齐
- **修复致命错误处理路径上的 `MissingGreenlet` 导致 task 状态无法写入 `failed`**：当 Fetch 等阶段先抛出 `DataError` 使 session 进入 `PendingRollbackError` 后，原 `_handle_fatal_error()` 在 `rollback()` 之后仍访问 `self._task.id`，触发 ORM 懒加载；Celery Worker 运行在同步 greenlet 中，懒加载调用 `await_only()` 抛出 `MissingGreenlet`，导致 `failed` 状态写入失败。修复后 `_handle_fatal_error()` 在 rollback 前即捕获 `task_id` 变量，后续所有日志 / CAS 更新 / 状态查询均使用 `task_id`，不再访问 `self._task`；`_start_task()` 同步采用相同模式；CAS 失败时改为显式 `select status` 而非 `refresh(self._task)`，避免对象过期触发懒加载

### Fixed
- **修复 MySQL 不兼容 `NULLS LAST` 导致 Synthesis / Evidence Graph Build 阶段 `ProgrammingError (1064)`**：
  - `app/pipeline/synthesizer.py` — `_load_evidence()` 排序由 `.relevance_score.desc().nulls_last()` 替换为 `sa.case((... == None, 1), else_=0)` + `.relevance_score.desc()`，生成 MySQL/SQLite/PostgreSQL 通用 SQL
  - `app/pipeline/evidence_graph.py` — `_load_evidence_items()` 同步替换相同排序逻辑
  - `tests/unit/pipeline/test_evidence_graph.py` — 更新测试断言中的排序 SQL 以保持一致
  - `app/tasks/research_task.py` — `_run_pipeline()` 在返回前增加 `session.refresh(task)`，避免 Orchestrator 通过 `update` 直接修改 DB 后返回 stale `task.status` 或触发懒加载异常
- **修复 `research_sources.content` 实际为 MySQL `TEXT`（64KB）导致大正文写入 `DataError` 的级联故障**：
  - `app/models/research_source.py` — `content` 字段类型由 `sa.Text` 修正为 `sqlalchemy.dialects.mysql.MEDIUMTEXT`，与 `DATABASE.md §2.4` 设计文档及 `report_sections.content` 保持一致（MySQL 16MB，足以容纳 Fetch 阶段 100KB 截断正文）
  - `alembic/versions/f277d4d29190_research_sources_content_列改为_mediumtext.py` — 新增迁移脚本，将生产环境 `content` 列从 `TEXT` 升级为 `MEDIUMTEXT`
  - `app/services/pipeline_orchestrator.py` — `_run_phase()` 提前缓存 `task_id`，避免 session 进入 `PendingRollbackError` 后在 `finally` 中访问 `self._task.id` 触发懒加载失败；`_handle_fatal_error()` 开头先执行 `session.rollback()`，确保中毒 session 能正常写入 `failed` 状态

### Fixed
- **修复 Search 阶段 `MissingGreenlet` 导致 Rerank 误报 `E3105`**：
  - `app/pipeline/searcher.py` — `_get_sub_questions_from_planning` 改为异步 `_load_sub_questions`，显式查询 `research_steps` 表读取 Planning 输出，避免在 `AsyncSession` 中访问 `step.parent_step` relationship 触发 `MissingGreenlet`
  - `app/services/pipeline_orchestrator.py` — `_handle_step_error` 对 Planning/Search/Rerank/Synthesis/EvidenceGraph/Render 等致命 Phase 的未知异常（非 `AppException`）按致命失败处理，不再降级继续，防止错误被延迟到后续阶段才暴露
  - `tests/unit/pipeline/test_searcher.py` — 更新为 mock `session.execute` 返回 Planning Step
  - `tests/unit/pipeline/test_integration.py` — 补充 `session.execute` mock，适配 Search 新的读取方式
  - `tests/unit/services/test_pipeline_orchestrator.py` — `_make_task` 构造真实 steps 列表，避免 `task.steps` MagicMock 被 `_check_early_termination` 误判为空列表触发 Evidence Threshold

### Added
- **Phase 3 §4.3 Evidence Graph Build 阶段实现（ROADMAP §4.3 / RESEARCH_PIPELINE §7）**——结构化认知资产组装：
  - `app/pipeline/evidence_graph.py` — Evidence Graph Build 阶段完整实现（~240 行）：`GraphItem`/`GraphCluster` 内存类型定义；从 `task.requirements` 读取 `max_sources`；读取最新 completed Synthesis Step 的 `output` 并校验 `clusters`；从 `evidence_items` 表读取 Evidence（`selectinload(EvidenceItem.source)`），按 `relevance_score` 降序取前 `max_sources` 条；为每条 Evidence 重新分配 0-based `index`；将 Synthesis cluster 的 `supporting_evidence_indices` 写回对应 item 的 `cluster_theme`/`consensus_level`（`conflicting_evidence_indices` 作为未被 supporting 覆盖时的 fallback）；生成 `graph.clusters`（`evidence_indices` 为去重排序后的 supporting+conflicting 合并列表）；透传 `conflicts`/`knowledge_gaps`；按 `source_id` 聚合 `sources[]` 并统计 `evidence_count`；`used_in_sections` 初始为空数组；输出 SSE `step.progress`(item_count/cluster_count/source_count)；返回完整 `graph` + 计数摘要 + `duration_ms`
  - `app/services/pipeline_orchestrator.py` — `build_default_phase_handlers()` 注册 `evidence_graph` handler，import `app.pipeline.evidence_graph.run_evidence_graph`
  - `tests/unit/pipeline/test_evidence_graph.py` — Evidence Graph Build 单元测试（14 用例：正常构建完整 graph + SSE / items 按 relevance_score 降序并重新分配 index / cluster 信息写回 items / conflicting indices fallback 写回 / sources 聚合 evidence_count / used_in_sections 初始为空数组 / knowledge_gaps 和 conflicts 透传 / max_sources 截断 / 缺少 Evidence→E3106 / 缺少 Synthesis output→E3106 / cluster 越界索引过滤 / conflict 越界索引过滤 / Graph index 与 EvidenceItem.id 不同 / source 字段为空时 source_id 保留）

### Fixed
- **修正 `docs/RESEARCH_PIPELINE.md` §7.3 `relevance_score` 范围描述**：由 `(0-10)` 修正为 `(0-1)` 并标注 `[Deviation]`，与实际 Rerank 归一化存储及 API.md 报告示例保持一致

### Added
- **Phase 3 §4.2 Synthesis 阶段实现（ROADMAP §4.2 / RESEARCH_PIPELINE §6）**——跨源综合：
  - `app/pipeline/synthesizer.py` — Synthesis 阶段完整实现（~340 行）：`ConflictPosition`/`SynthesisCluster`/`SynthesisConflict`/`SynthesisNotes` 内存类型定义；从 `evidence_items` 表读取 Rerank 产出的 Evidence（`selectinload(EvidenceItem.source)`），按 `relevance_score` 降序 + `max_sources` 截断 + 单条内容截断至 1500 字符；使用 0-based evidence 索引构建 Prompt；LLM 调用 `deepseek-v4-pro`（`deep_thinking=True`，`temperature=0.3`，`max_tokens=5000`）；严格 JSON 解析与校验（clusters 必填 + theme/summary/consensus_level 校验 + supporting/conflicting indices 校验；conflicts 允许 null → 空数组；knowledge_gaps 数组；overall_assessment 字符串）；越界索引过滤不阻断，非整数索引触发重试；重试 3 次耗尽 → `SynthesisFailedException(E3104, recoverable=true)`；空 Evidence → E3104 `"没有可供综合的证据"`；输出 SSE `step.progress`(clusters_count) + `step.completed`(clusters/conflicts/gaps_count)
  - `app/services/pipeline_orchestrator.py` — `build_default_phase_handlers()` 注册 `synthesis` handler，import `app.pipeline.synthesizer.run_synthesis`
  - `tests/unit/pipeline/test_synthesizer.py` — Synthesis 单元测试（10 用例：正常产出完整 output + SSE / Evidence 降序+1500 截断+0-based 索引 / max_sources=3 截断 / 3 种 task_type Prompt 注入 / conflicts:null → 空数组 / 越界索引过滤 / 无效 JSON 重试后成功 / 无效 JSON 重试耗尽→E3104 call_count=3 / LLM 异常重试耗尽→E3104 call_count=3 / 空 evidence→E3104 且不调用 LLM）

### Fixed
- **失败模型修正：解耦「致命停止」与「不可恢复」两个维度**：
  - `app/core/task_state_resolver.py` — `FATAL_STEP_ERROR_CODES` 从 5 码扩展至 10 码（新增 E3104/E3107/E3108/E3109/E3111，E3103 仍由 Resolver 生成故不入集）；新增 `RECOVERABLE_STEP_ERROR_CODES`（E3102/E3104/E3107/E3108/E3109/E3111，对齐 API.md §5 recoverable 列）；`_check_fatal()` 的 `recoverable` 字段按异常自身定义传播（致命停止 ≠ 不可恢复）
  - `app/services/pipeline_orchestrator.py` — 新增 `_extract_recoverable()` 从 `AppException.error_detail` 提取 recoverable、`_get_last_checkpoint()` 防御性读取 `execution_context.last_completed_step_id`、`_build_task_failed_payload()` 构造 task.failed payload（仅 recoverable=true 时附带 `last_checkpoint`）；替换 3 处硬编码 `recoverable=False`：`_handle_step_error` FATAL 分支 / `_handle_fatal_error` CAS + SSE / `_check_early_termination` 与 `_finalize_task` failed 分支
  - `tests/unit/core/test_task_state_resolver.py` — 更新 FATAL 集测试（10 码完整 + E3103 不入集 + RECOVERABLE 集完整）；所有原用 E3104 模拟「可降级失败」的用例改为 `error_code=None`（修复后裸异常才是可降级）；新增 `test_Fatal失败_E3104_返回failed且recoverable为True` 与 `test_Fatal失败_E3101_返回failed且recoverable为False`
  - `tests/unit/services/test_pipeline_orchestrator.py` — 重写 `test_可恢复致命错误_emit_task_failed_recoverable为True_终止Pipeline`：从 planning handler 抛 `SynthesisFailedException`，断言 `task.failed` 中 `recoverable=True` + 附带 `last_checkpoint` + Pipeline 终止（search 未执行）+ `task.warning` 为 0

### Added
- **`research_sources` 表新增 `content` 列，Fetcher 持久化正文供 Rerank 复用**：
  - `app/models/research_source.py` — 新增 `content` 字段（`sa.Text`，nullable，server_default `NULL`），写入 trafilatura 提取的 Markdown 正文
  - `alembic/versions/39b5ffae3624_research_sources_新增_content_列.py` — 新增迁移脚本，为 `research_sources` 表添加 `content` 列
  - `app/pipeline/fetcher.py` — `run_fetch()` 成功分支将 `_fetch_one_url()` 返回的 `content` 写入 `ResearchSource.content`；失败/跳过分支保持 `NULL`
  - `docs/DATABASE.md` §2.4 — 更新 `research_sources` DDL 与字段说明表，新增 `content MEDIUMTEXT` 定义
  - `docs/RESEARCH_PIPELINE.md` — 更新 `FetchedDoc` 定义（标注 content 持久化到 `research_sources.content`），新增 §5.2a 说明 Rerank 从表读取正文
  - `tests/unit/pipeline/test_fetcher.py` — 新增 content 写入断言（成功写入 / 失败保持 NULL / 超长正文写入）

### Added
- **Phase 3 §4.1 Rerank 阶段实现（ROADMAP §4.1 / RESEARCH_PIPELINE §5）**——二段式证据粗筛精排：
  - `app/pipeline/reranker.py` — Rerank 阶段完整实现（~430 行）：`FetchedDoc`/`Candidate`/`Evidence` 内存类型定义；从 `research_sources` 读取成功抓取的 `content`，从 planning step output 读取 `sub_questions`；BM25 粗筛（`app.pipeline.bm25.segment_document` 按 `\n\n` 分段 ≤2000 字符 + `bm25_rerank` 对每个 sub_question 评分，每文档取 top-3 segments，最多 45 候选）；LLM 精排（DeepSeek `LLM_FLASH_MODEL`，`deep_thinking=False`，`temperature=0.3`，四维评分 Prompt：相关性 40% / 信息量 30% / 权威性 15% / task_type 维度 15%）；输出 `Evidence[]` 按 `relevance_score` 降序取 `top-K = min(max_sources, 候选数)`；写入 `evidence_items` 表（INSERT only，幂等追加）；失败策略：BM25 候选为空 / 无成功 fetch 文档 / 缺少 sub_questions → E3105；LLM 失败或无效 JSON 重试 2 次后仍失败 → E3105；Evidence < 3 仅触发 `task.warning` 不阻断
  - `app/services/pipeline_orchestrator.py` — `build_default_phase_handlers()` 注册 `rerank` handler，import `app.pipeline.reranker.run_rerank`
  - `tests/unit/pipeline/test_reranker.py` — Rerank 单元测试（9 用例：正常流程 Evidence 持久化 + output 字段 / 3 种 task_type Prompt 维度注入 / Evidence<3 仅 warning / 无成功 fetch 文档→E3105 / 缺少 sub_questions→E3105 / LLM 无效 JSON 重试耗尽→E3105 / LLM 调用异常重试耗尽→E3105 / Evidence 按 relevance_score 降序 / score 0-10 归一化为 0-1）

### Added
- **Phase 2 §3.9 测试完成（ROADMAP §3.9）**——6 个新测试文件 + 105 个新测试用例：
  - `tests/unit/tasks/test_lock.py` — Celery 幂等锁单元测试（19 用例：Key 格式验证 / SET NX 获取成功+拒绝 / 自定义 TTL / 不同 step_type·task_id Key 隔离 / 七阶段全类型 / 释放锁+重复释放 / check_step_lock 存在+不存在 / 完整生命周期 / 并发拒绝 / 异步版 acquire+release+自定义 TTL）。Mock Redis 客户端在函数边界截断
  - `frontend/tests/unit/sse.test.js` — SSE 解析工具单元测试（18 用例：单行 event+data 解析 / 注释帧跳过 / 纯注释帧过滤 / 多行 data 拼接 / 跨 chunk buffer 保留 / JSON 解析失败容错+onError / event/data 无空格前缀兼容 / 空帧跳过 / 14 种事件类型全量遍历 / 连接状态机 connecting→connected / close→disconnected / 无 token→无 Authorization 头 / 有 token→Bearer 携带 / HTTP 500→reconnecting / close 阻止重连 / 重试耗尽→error / 重连成功后恢复 connected）。Mock fetch + ReadableStream（悬空流模式避免递归重连）
  - `frontend/tests/unit/taskStore.test.js` — TaskStore 单元测试（27 用例：createTask 成功 current 字段+SSE 重置+失败 loading 恢复 / fetchList 正常+空列表+status 筛选+分页参数 / fetchDetail 满字段+不存在 404 / deleteTask 本地移除+total 减 1+清空 current+不清空非当前 / cancelTask do SSE+更新状态+非当前任务不更新 / connectSSE 状态流转 / disconnectSSE close+重复调用不报错 / clearCurrent 清空 current+progress / handleSSEEvent task.created·task.status.snapshot·phase.started·task.progress·task.completed·task.failed·task.canceled·未知事件）。Mock API + SSE 模块在边界截断
  - `frontend/tests/components/TypeCard.test.js` — TypeCard 组件测试（13 用例：comparison/explainer/analysis 三卡独立渲染+图标+标题+描述+示例 / selected class 开关 / 勾标 icon 显示隐藏 / click emit select 三种 type / selected=true 再次点击仍 emit / 父组件 selected prop 控制三选一互斥 / 非法 type validator 警告）
  - `frontend/tests/components/ResearchPage.test.js` — ResearchPage 创建态组件测试（15 用例：el-input textarea 渲染 / 三张 TypeCard / 提交按钮初始 disabled / 三张 ExampleCard / 高级选项默认折叠+展开+再折叠 / 示例卡片点击填入 topic+task_type / topic 为空·未选 type·两者齐全 按钮 disabled+enabled / 提交中 loading+disabled / 提交成功→切运行态+API 参数校验+SSE 连接 / TypeCard 选中状态切换 / 422 错误 ElMessage.error）。ElementPlus mocked 场景使用 `wrapper.vm.form` 直接设值
  - `frontend/tests/components/HistoryPage.test.js` — HistoryPage 组件测试（13 用例：列表加载 store 数据 / 状态筛选重置 currentPage=1 / 搜索 300ms 防抖验证 / 空状态文字+引导 / 查看→fetchDetail→router.push / 删除取消→不调 API / 删除确认→API 调用+ElMessage.success+本地移除 / 空页回退 / 分页组件显示+隐藏 / 挂载自动 loadList / 分页换页+pageSize 变更 reset）。所有 el-* 组件 stubbed（scoped slots 兼容）
  - 后端全量回归 380 passed（+19 新增）/ 前端全量回归 131 passed（+86 新增）

- **Phase 2 §3.7 前端实现：研究任务创建 + 历史列表 + SSE 框架（ROADMAP §3.7）**——5 新建文件 + 2 重写文件 + 1 修改文件：
  - `frontend/src/api/research.js` — 研究任务 API 封装（6 个函数）：`createTask()` / `getTaskList()`（分页+status 筛选）/ `getTaskDetail()` / `deleteTask()` / `cancelTask()` / `getTaskState()`。模式对齐 `api/auth.js`，统一使用 Axios 拦截器处理 Token 刷新
  - `frontend/src/utils/sse.js` — SSE 流式解析工具（~120 行）：`connectSSE(url, options)` → 返回 `{ close }`。`fetch` + `ReadableStream` + `response.body.getReader()` 逐块读取 → buffer 按 `\n\n` 分割事件帧 → 跳过注释帧（`: ping`）→ 解析 `event:`/`data:` 行 → JSON.parse → 回调 `onEvent(eventName, data)`。连接状态机 5 态（`connecting`→`connected`→`reconnecting`→`error`→`disconnected`）。断线指数退避重连（1s/2s/4s/8s，最多 3 次，可配）。`close()` 调 `abortController.abort()` + `reader.cancel()` 并阻止重连。对齐 FRONTEND.md §8 + API.md §4
  - `frontend/src/stores/task.js` — TaskStore (Pinia，~240 行)：Composition API 风格（对齐 `stores/auth.js`）。State：`taskList` / `current`（当前任务详情或 null→创建态）/ `currentPage`·`total`·`pageSize` / `loading`·`listLoading` / `sseStatus`（5 态）/ `progress`（{completed_steps, total_steps, progress}）/ `sseConnection`。Actions：`createTask()`（调 API→设 current）/ `fetchList()`（分页+筛选→更新列表）/ `fetchDetail()`（加载详情→设 current）/ `deleteTask()`（调 API→本地 filter()+total--→若删除当前任务则 clearCurrent）/ `cancelTask()`（调 API→disconnectSSE→更新状态）/ `connectSSE()`（调 sse.js + 绑定 handleSSEEvent）/ `disconnectSSE()` / `clearCurrent()`。`handleSSEEvent()` 内部映射 15 种 SSE 事件到状态更新（task.created→设 running / task.status.snapshot→恢复完整进度 / task.progress→更新进度 / task.completed→设 completed+关 SSE / task.failed→设 failed+存储 error 字段 / task.canceled→关 SSE 等）
  - `frontend/src/components/task/TypeCard.vue` — 研究类型选择卡片（~100 行）：Props `type`（comparison/explainer/analysis）+ `selected`。三张卡片各含 Font Awesome 图标（`fa-balance-scale`/`fa-lightbulb`/`fa-chart-line`）+ 标题 + 描述 + 示例。点击 emit `select(type)`。选中态：`border-color: var(--rm-primary)` + `background: rgba(15,118,110,0.08)` + `box-shadow: 0 0 0 1px var(--rm-primary)` + 右上角勾标 `fa-circle-check`。三选一互斥（父组件控制）。样式全部 `--rm-*` CSS 变量，对齐 UIDESIGN.md §4.3
  - `frontend/src/components/task/ExampleCard.vue` — 快捷示例卡片（~65 行）：Props `example`（{topic, task_type, label}）。hover 时 `border-color: rgba(15,118,110,0.3)` + `background: rgba(15,118,110,0.05)`。点击 emit `select(example)` 自动填入表单。父组件预设 3 个示例（向量数据库对比·注意力机制·量子计算密码学）。样式全部 `--rm-*` CSS 变量
  - `frontend/src/views/ResearchPage.vue` — **完全重写**（~340 行 + ~280 行样式）。三态切换基于 `taskStore.current.status`：
    - **创建态**（current === null）：欢迎区（`fa-microscope` 图标 +「开始一项新的研究」）+ 表单卡片（topic textarea ≤500 字符 + show-word-limit + 字数统计 / 研究类型 TypeCard 三选一 / 高级选项折叠区 [max_sources el-slider 1-50 + language el-select zh/en + depth 固定 quick 灰显]）+ 提交按钮（全宽 teal，#0F766E，48px，loading 禁用）+ 3 个 ExampleCard 快捷示例。表单校验：topic 非空 + ≤500 + task_type 必选 → 提交 `POST /api/research` → 成功→`ElMessage.success`→`taskStore.createTask()`→切运行态→`taskStore.connectSSE()`。错误处理：400·422（字段级错误提取）·429·403·500/503 分级提示
    - **运行态**（pending/running，Phase 3 占位）：旋转图标 +「研究正在执行中」+ 当前阶段 + 进度（completed/total steps）+ SSE 连接状态（已连接✓/连接中/重连中/连接失败颜色编码）+「取消研究」按钮（`ElMessageBox.confirm` 二次确认 → `POST /api/research/{task_id}/cancel` → 409 冲突提示）
    - **完成态**（completed/failed/canceled，Phase 3 占位）：状态图标（✅ success/❌ danger/⚠️ warning/muted）+ 标题（研究完成/研究失败/研究已取消/部分完成）+ 统计（来源数+证据数）/ 失败信息（error_message + error_code + recoverable 提示）+「返回新建研究」按钮 → `taskStore.clearCurrent()`
  - `frontend/src/views/HistoryPage.vue` — **完全重写**（~200 行 + ~130 行样式）。工具栏：`el-select` 状态筛选（全部/排队中/运行中/已完成/部分完成/失败/已取消）+ `el-input` 主题搜索（300ms 防抖 + `fa-search` 前缀图标）+「新建研究」按钮。`el-table` 列：主题（40 字符截断 + `el-tooltip`）/ task_type 彩色标签（comparison=蓝 / explainer=绿 / analysis=紫）/ status 彩色标签（含 Font Awesome 图标 + 脉冲动画 running 态）/ 来源数 / 证据数 / 创建时间 / 操作（查看·删除）。`el-pagination`（total + sizes[10/20/50] + prev/pager/next）。空状态：「暂无研究任务」+ `fa-inbox` 图标 + 引导按钮→`/research`。删除：`ElMessageBox.confirm` 二次确认 → 调 `taskStore.deleteTask()`→`ElMessage.success`→本地 filter()+total--→空页自动回退 `currentPage--`+loadList()。查看：`taskStore.fetchDetail()`→`router.push('/research')`。筛选变更→`loadList()`+reset `currentPage=1`
  - `frontend/src/components/layout/Sidebar.vue` — **修改**（+~80 行模板 + ~60 行脚本 + ~55 行样式）。在 `.sidebar-middle` 内导航链接下方新增「最近任务」区域（仅展开态显示 `v-show="!collapsed"`）：`onMounted` 中调 `taskStore.fetchList({ page: 1, page_size: 10 })` → `groupedTasks` computed 按时间四组（今天/昨天/近7天/更早）+ 分组标签/时间标签 → 任务条目含状态图标（✅`fa-circle-check` completed / ⚠️`fa-triangle-exclamation` partially_completed / ❌`fa-times-circle` failed / 🚫`fa-ban` canceled / ⏳`fa-spinner fa-spin` running / 🔄`fa-clock` pending）+ 主题截断。点击→`taskStore.fetchDetail(task_id)`→`router.push('/research')`。高亮当前任务（`active` class）。无任务时显示「暂无任务」。样式全部 `--rm-*` CSS 变量

### Added
- **Phase 2.3.3-§3.6 Pipeline 前半段完整实现（ROADMAP §3.3-§3.6）**——10 个文件 + 82 新测试：
  - `app/pipeline/planner.py` — Planning 阶段完整实现（~200 行）：System Prompt 构建（含 task_type 策略注入）、deepseek-v4-pro LLM 调用（deep_thinking=True, temperature=0.3, max_tokens=1000）、JSON 解析（处理 markdown 代码块包装）、Pydantic 式输出校验（sub_questions 数量 3-5 / ≤200 字符 / ≥2 实体关键词）、校验失败重试（最多 3 次，传递反馈信息）、重试耗尽 → E3101 PlanningFailed
  - `app/pipeline/searcher.py` — Search 阶段完整实现（~200 行）：读取 Planning 产出的 sub_questions、对每个子问题调 Tavily Search API（POST /search + 重试 2 次指数退避 1s/2s）、子 step 管理（每个子问题创建独立 ResearchStep + SSE 事件）、跨子问题 URL 去重（保留首次归属）、写入 ResearchSource 行、失败策略（单子问题可降级 SKIPPED / 全部失败 → E3102 SearchFailed）
  - `app/pipeline/fetcher.py` — Fetch 阶段完整实现（~220 行）：读取 Search 创建的待 fetch URL 列表、URL 安全检查（协议白名单 http/https + IP 黑名单 SSRF 防护 / 9 段内网 CIDR 拒绝）、HTTP GET（httpx, timeout=15s, User-Agent: ResearchMind/1.0）、trafilatura 正文提取（Markdown 格式, favor_precision=True）、内容截断（100KB）、子 step 管理（每个 URL 独立 ResearchStep）、更新 ResearchSource 行（fetch_status + title + domain + fetched_at）、失败策略（超时重试 1 次 / 403/404/5xx/DNS→直接 SKIPPED）
  - `app/api/research.py` — 新增 SSE 事件流端点 `GET /api/research/{task_id}/stream`（StreamingResponse + text/event-stream + task.status.snapshot 初始推送）+ 新增 REST 状态快照端点 `GET /api/research/{task_id}/state`（SSE 等价物，轮询降级）
  - `app/core/llm.py` — 新增 `temperature` 可选参数（`chat_completion` + `stream_chat_completion`），向后兼容
  - 测试覆盖：`tests/unit/pipeline/test_planner.py`（20 用例：JSON 提取+实体计数+校验+LLM Mock 成功/重试/E3101+3 种 task_type 策略注入验证+SSE 事件）+ `tests/unit/pipeline/test_searcher.py`（12 用例：域名提取+子问题读取+正常搜索+去重+ResearchSource 创建+SSE 事件+单子问题 SKIPPED+全失败 E3102+重试恢复）+ `tests/unit/pipeline/test_fetcher.py`（15 用例：安全校验 9 场景+正常抓取+超时+403+SSRF+空正文+DNS 失败）+ `tests/unit/api/test_sse.py`（9 用例：状态快照 API 正常+404+403+401+错误信息+SSE 流权限+快照结构完整性+进度计算）+ `tests/unit/pipeline/test_integration.py`（6 用例：Planning→Search 数据流+失败阻断+Search→Fetch 持久化+全失败终止+SSE 事件序列完整性）
- **Phase 2.3.2 Celery 异步 Pipeline 编排（ROADMAP §3.2）**——7 个源文件 + Celery 分发激活：
  - `app/pipeline/sse_bridge.py` — SSE Bridge（~300 行）：Redis Pub/Sub 桥接 Celery Worker ↔ FastAPI ↔ SSE Stream。发布层 `SSEBridge` 类（同步 publish + seq 序号单调递增）+ 订阅层 `sse_event_stream()` 异步生成器（连接时推送 `task.status.snapshot`，循环获取 Redis 消息 yield SSE 格式事件，`stream_with_heartbeat` 包裹）。15 种 SSE 事件类型常量（v1.0，`EVENT_TASK_CREATED` 等，2 种 [v2] 预留）
  - `app/services/pipeline_orchestrator.py` — Pipeline Orchestrator（~450 行）：`PipelineOrchestrator` 类，七阶段串行调度。每 Phase：创建 ResearchStep → 幂等锁检查（`acquire_step_lock_async`）→ 更新 step status→running → 发送 SSE 事件（`phase.started` / `step.started`）→ 调用 Phase handler → 更新 output + status→completed → 原子更新 `execution_context` → 发送 SSE 事件（`step.completed` / `phase.completed` / `task.progress` / `checkpoint.saved`）→ `TaskStateResolver` 检查提前终止 → 释放锁。含 `build_default_phase_handlers()` 注册表（planning/search/fetch → Phase 2 stub，rerank/synthesis/evidence_graph/render → Phase 3 待实现自动跳过）。`TaskFatalException` 不可恢复错误
  - `app/tasks/research_task.py` — Celery 任务入口（~110 行）：`@celery_app.task` 装饰的 `execute_research_task(task_id)`，`asyncio.run()` 包裹 async 逻辑。幂等检查（非 pending 状态跳过）+ 实例化 SSEBridge / TraceRecorder / Orchestrator → `orchestrator.run()` → commit。`_emergency_fail()` 兜底写入失败状态
  - `app/pipeline/planner.py` — Planning Phase stub（~40 行）：`run_planning()` 函数签名 + 返回 stub output（等待 §3.3 替换为 LLM 调用 + 输出校验 + task_type 策略注入）
  - `app/pipeline/searcher.py` — Search Phase stub（~40 行）：`run_search()` 函数签名 + 返回 stub output（等待 §3.4 替换为 Tavily API 调用 + 去重 + 失败重试）
  - `app/pipeline/fetcher.py` — Fetch Phase stub（~40 行）：`run_fetch()` 函数签名 + 返回 stub output（等待 §3.5 替换为 HTTP GET + trafilatura 提取 + SSRF 防护）

### Fixed
- **修复测试间数据污染导致的批量失败**（CLAUDE.md 测试规范）：
  - `tests/conftest.py` — `async_client` fixture 中将 `db_session.commit` 在测试环境下重定向为 `flush`，避免 API 层的显式 `commit()` 提交外层事务，确保每个测试函数结束后统一回滚，消除跨测试状态泄漏
  - `tests/unit/api/test_research.py::TestListResearchAPI` — 列表 total 计数不再受前序测试残留数据影响
  - `tests/unit/services/test_auth_service.py` — 消除 `users.username` UNIQUE 冲突（前序 API 测试 commit 残留导致）
- **同步 `TestPlanningFailedException` 断言与文档**：`tests/unit/core/test_exceptions.py` 中 E3101 的 `recoverable` 改为 `False`，并移除对 `retry_after_ms` 的断言，对齐 [API.md §5.3](docs/API.md#53-研究执行错误e3xxx) / [RESEARCH_PIPELINE.md §2.7](docs/RESEARCH_PIPELINE.md#27-checkpoint)

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
- **Phase2 代码审查修复（第一批：功能正确性阻断）**：
  - **S1**: `pipeline_orchestrator.py:395,575` — `getattr(error, "code", None)` → `getattr(error, "error_code", None)`（AppException 属性名为 `error_code`，错误属性名导致致命错误检测全链路失效：`FATAL_STEP_ERROR_CODES` 匹配永不触发、E3101/E3110 等致命错误被降级为 warning）
  - **S2**: `enums.py:33` — `FETCH_STATUS_ENUM` 增加 `"dns_error"`（fetcher DNS 失败时返回该值，原枚举不含会导致落库 IntegrityError）
  - **S3**: `api/research.py:50` — `_execute_research_task.delay()` 前显式 `await db.commit()`，消除 Celery Worker 竞态窗口（对齐 CLAUDE.md 强制规则）
  - **S12**: `frontend/src/styles/global.css` — 补定义 `--rm-welcome-icon-size: 56px;`（UIDESIGN.md 已定义但 global.css 缺失，导致欢迎图标尺寸塌缩为 ~24px）
  - **S13**: HistoryPage 搜索关键字从未传入 API — `api/research.py` 新增 `keyword` Query 参数 + `research_service.py` 新增 `topic.ilike()` 模糊搜索 + `HistoryPage.vue` → `stores/task.js` → `api/research.js` 全链路传递 `keyword`
- **Phase2 代码审查修复（第二批：Phase4 断点续跑前必修）**：
  - **S4**: `pipeline_orchestrator.py` — 每 Phase 完成后显式 `await self._session.commit()`（替代仅 flush），checkpoint 状态崩溃后可恢复；`_handle_fatal_error` 兜底 commit
  - **N1**: Task 状态更新改为 CAS（Compare-And-Swap）— `_start_task`（pending→running）、`_check_early_termination`（running→failed）、`_finalize_task`（running→终态）、`_handle_fatal_error`（running→failed）全部使用 `sa_update(ResearchTask).where(…status == old).values(…status=new)` 防并发覆盖
  - **N2**: Phase 循环中每次进入前 `await self._session.refresh(self._task)` + 检查 `status == "canceling"` → 提前退出 Pipeline
  - **N3**: `_run_phase` Step 创建后检查 `step.status in {"completed", "failed", "skipped"}` → 终态跳过执行（Phase4 断点续跑后生效的防御深度）
  - **N4**: `sse.py:format_sse_event()` 新增 `event_id` 可选参数 → SSE `id:` 字段透传；`sse_bridge.py` 订阅层提取 `seq` 传入 `event_id`，客户端可基于 `id:` 去重
- **Phase2 代码审查修复（第三批：文档一致性）**：
  - **S5**: `API.md §3.6` — 统一 `task_status` → `status`（与代码 `_build_snapshot` 及其他端点一致）；`execution_pointer`/`last_completed_step`/`checkpoints` 标注 `[v2]` 未实现；补 `steps`/`topics`/`error`/`stats` 字段与代码同步
  - **S6**: `app/models/research_task.py` — 补 `updated_at` 列（`UTCDateTime` + `server_default=func.current_timestamp()` + `onupdate=func.current_timestamp()`），与 `DATABASE.md §2` 定义一致；生成 Alembic 迁移 `c02701951a41`
  - **S7**: `app/core/exceptions.py` — `E3101 PlanningFailedException` 和 `E3105 RerankFailedException` 的 `recoverable` 从 `True` 改为 `False`，与 `task_state_resolver.py` FATAL 集和 `API.md §5.3` 错误码表一致
  - **Phase2 代码审查修复（第四批：测试与规范修复）**：
    - **S9**: `docs/TESTING_STRATEGY.md` — 新增 Phase2 说明段落
    - **S10**: 新建 `tests/unit/services/test_pipeline_orchestrator.py` — 9 个用例覆盖七阶段调度、幂等锁、FATAL 终止、_finalize_task 三分支
    - **S11**: `test_sse.py:175-179` `pass` → `pytest.skip`；`test_lock.py:287-295` 补断言
    - **N5**: `exceptions.py` — 新增 `UnknownInternalException`（E3999）
    - **N6**: `fetcher.py` — 硬编码 `_FETCH_*` → `settings.FETCH_*`
    - **N7**: `searcher.py` — 硬编码 `_TAVILY_*` → `settings.TAVILY_*`
    - **N8**: `orchestrator.py` — FATAL_STEP_ERROR_CODES 导入上移到顶部
    - **N9**: `fetcher.py` — `_check_url_safety` async 化，DNS 通过 run_in_executor
    - **N10**: `orchestrator.py` — execution_pointer 查询实际 step 数量
    - **N11**: `task_state_resolver.py` — E3102 加入 FATAL 集
    - **F1-F11**: 前端规范修复（Sidebar clearCurrent / pulse 动画 / ElLoading / cancel :loading / CSS变量 / .danger-btn / auto connectSSE / 退避对齐 / 死代码 / sidebar-hover / cancelTask SSE 等待）
    - **ROADMAP**: 更新日期→2026-06-25；函数清单/SSE描述/§3.8进度/Cancel UI 同步修正

  - **S8**: SSE 事件计数全局统一为「15 种（v1.0）+ 2 种预留 [v2]」— 修改 `ROADMAP.md`（4 处）、`CHANGELOG.md`（1 处）、`CLAUDE.md`（1 处）、`TESTING_STRATEGY.md`（1 处）、`DEVELOPMENT.md`（1 处）、`FRONTEND.md`（3 处）、`RESEARCH_PIPELINE.md`（1 处）、`sse.py`（1 处）、`.claude/commands/review.md`（3 处），共 16 处

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
