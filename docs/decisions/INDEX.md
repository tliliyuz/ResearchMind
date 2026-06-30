# 决策索引

> 本文档汇总 ResearchMind 所有架构决策（ADR）与关键设计决策的交叉引用。原分散在 `resource/docs/ROADMAP.md` 各 Phase 中的「关键决策索引」已迁移至此，作为统一的决策注册表。

| 编号 | 决策 | 权威文档 |
|:---|:---|:---|
| 1 | 创建任务 → `commit()` → `task.delay()` 时序（避免竞态窗口） | [ARCHITECTURE.md §3.3](../ARCHITECTURE.md#33-execution-context断点续跑的核心) |
| 2 | 任务列表：仅当前用户，按 `created_at DESC`，分页+status 筛选 | [API.md §3.1](../../resource/docs/API.md#31-研究任务) |
| 3 | 任务详情：`progress` 从 `execution_context.progress` 提取，前端不直接访问 `execution_context` | [API.md §3.1](../../resource/docs/API.md#31-研究任务) |
| 4 | 任务删除：FK CASCADE 级联清理全部派生数据 | [DATABASE.md §4](../DATABASE.md#4-外键与级联策略) |
| 5 | TaskStateResolver：禁止 Task 自身直接写入状态，统一由 Resolver 推导 | [ARCHITECTURE.md §3.7](../ARCHITECTURE.md#37-taskstateresolver) |
| 6 | 权限两层分离：`require_task_accessible`（资源归属）+ `require_admin`（系统角色） | [ARCHITECTURE.md §4](../ARCHITECTURE.md#4-权限模型) |
| 7 | Pipeline Orchestrator 负责阶段调度 + Execution Context 原子更新 | [ARCHITECTURE.md §3.3](../ARCHITECTURE.md#33-execution-context断点续跑的核心) |
| 8 | SSE Bridge：Redis Pub/Sub 桥接 Celery Worker ↔ FastAPI ↔ SSE Stream | [RESEARCH_PIPELINE.md §9](../RESEARCH_PIPELINE.md#9-pipeline-sse-事件映射) |
| 9 | Planning：deepseek-v4-pro + `deep_thinking=True` + `temperature=0.3` | [RESEARCH_PIPELINE.md §2.5](../RESEARCH_PIPELINE.md#25-参数) |
| 10 | Planner 输出校验：3-5 SubQuestions + ≤200 字符 + ≥2 实体 → 3 次重试 | [RESEARCH_PIPELINE.md §2.6](../RESEARCH_PIPELINE.md#26-输出校验) |
| 11 | `task_type` 策略注入：Planning Prompt 运行时注入对应策略段落 | [RESEARCH_PIPELINE.md §2.4](../RESEARCH_PIPELINE.md#24-task_type-驱动的拆解策略) |
| 12 | Search：Tavily `advanced` + 5 results/sub_question + 去重后上限 25 | [RESEARCH_PIPELINE.md §3.2](../RESEARCH_PIPELINE.md#32-搜索策略) |
| 13 | Search 失败：单个 SKIPPED（不致命）/ 全部失败→E3102（致命） | [RESEARCH_PIPELINE.md §3.4](../RESEARCH_PIPELINE.md#34-失败策略) |
| 14 | Fetch 安全：协议白名单 + IP 黑名单 SSRF 防护 + 15s 超时 | [RESEARCH_PIPELINE.md §4.4](../RESEARCH_PIPELINE.md#44-安全约束) |
| 15 | Fetch 失败：403/404/DNS 不重试直接 SKIPPED / 超时重试 1 次 | [RESEARCH_PIPELINE.md §4.5](../RESEARCH_PIPELINE.md#45-失败策略) |
| 16 | SSE 事件类型：v1.0 18 种核心事件 + 2 种预留 [v2]，覆盖 task.* / phase.* / step.* / checkpoint.* / agent.* | [API.md §4.1](../../resource/docs/API.md#41-事件类型总览) |
| 17 | SSE 实现：手动 `StreamingResponse`（非 sse-starlette）+ 15s 心跳 | [API.md §4](../../resource/docs/API.md#4-sse-事件协议) |
| 18 | SSE 重连恢复：`task.status.snapshot` 立即推送完整状态快照 | [API.md §4.2](../../resource/docs/API.md#42-重连与快照恢复) |
| 19 | BM25 Stage 1：纯内存计算 ~50ms，零 API 成本，45 候选上限 | [RESEARCH_PIPELINE.md §5.3](../RESEARCH_PIPELINE.md#53-stage-1bm25-粗筛) |
| 20 | LLM Rerank Stage 2：DeepSeek API 打分 + `task_type` 加权维度 | [RESEARCH_PIPELINE.md §5.4](../RESEARCH_PIPELINE.md#54-stage-2llm-rerank) |
| 21 | Rerank Prompt：四维评分（相关性 40% + 信息量 30% + 权威性 15% + task_type 维度 15%） | [RESEARCH_PIPELINE.md §5.4](../RESEARCH_PIPELINE.md#54-stage-2llm-rerank) |
| 22 | Synthesis：deepseek-v4-pro + `deep_thinking=True` + `temperature=0.3` | [RESEARCH_PIPELINE.md §6.4](../RESEARCH_PIPELINE.md#64-参数) |
| 23 | Synthesis 输入截断：最多 `max_sources` 条 + 单条 ≤1500 字符 | [RESEARCH_PIPELINE.md §6.3](../RESEARCH_PIPELINE.md#63-evidence-格式化策略) |
| 24 | Evidence Graph Build：纯程序化，不调用 LLM——核心认知资产不受 LLM 随机性影响 | [RESEARCH_PIPELINE.md §7](../RESEARCH_PIPELINE.md#7-evidence-graph-build--结构化认知资产) |
| 25 | Render：`deep_thinking=False` + `temperature=0.5`，报告质量靠模板约束 | [RESEARCH_PIPELINE.md §8.6](../RESEARCH_PIPELINE.md#86-参数) |
| 26 | 报告模板：3 种 task_type → 3 种 Section 组织方式 | [RESEARCH_PIPELINE.md §8.2](../RESEARCH_PIPELINE.md#82-模板选择) |
| 27 | 引用锚点：`[来源N]` 正则提取 → 去重排序 → 填充 `section.sources[]` → 写 `section_evidence` | [RESEARCH_PIPELINE.md §8.4](../RESEARCH_PIPELINE.md#84-引用锚点机制) |
| 28 | Execution Context：每个 Step 完成后原子更新，与 Step 状态在同一事务 | [ARCHITECTURE.md §3.3](../ARCHITECTURE.md#33-execution-context断点续跑的核心) |
| 29 | Checkpoint 保存时机：每 Phase 完成后 + 每个 Fetch URL 后 + Synthesis 后 | [RESEARCH_PIPELINE.md §10.3](../RESEARCH_PIPELINE.md#103-checkpoint-策略) |
| 30 | Retry：从 `last_completed_step_id` 的下一个 Step 恢复，复用已完成 output | [ARCHITECTURE.md §3.3](../ARCHITECTURE.md#33-execution-context断点续跑的核心) |
| 31 | CAS 状态更新：`WHERE status = 'old_value'`，并发 Worker 防覆盖 | [ARCHITECTURE.md §5.7](../ARCHITECTURE.md#57-并发控制) |
| 32 | 限流阈值：创建任务 5/min/user → E9004 / 登录 10/min → E1012 / 全局默认 120/min → E9004。压测后调整 | [API.md §1.4](../../resource/docs/API.md#14-限流) |
| 33 | Phase-Locked ReAct：保留七阶段顺序，每阶段内 LLM 自主调用 Tool | [ARCHITECTURE.md §2.3.1](../ARCHITECTURE.md#231-react-loop-控制流) |
| 34 | `PhaseController` 负责 phase 推进与可用 Tool 过滤 | [ARCHITECTURE.md §2.3.1](../ARCHITECTURE.md#231-react-loop-控制流) |
| 35 | `MAX_AGENT_ITERATIONS=30` 作为 Loop 失控兜底 | [ARCHITECTURE.md §2.3.1](../ARCHITECTURE.md#231-react-loop-控制流) |
| 36 | Tool / LLM 异常记录 observation 后继续，不立即终止任务 | [ARCHITECTURE.md §2.3.1](../ARCHITECTURE.md#231-react-loop-控制流) |
| 37 | 断点续跑从 `agent_context` + `agent_memory_entries` 恢复 | [ARCHITECTURE.md §2.3.3](../ARCHITECTURE.md#233-working-memory) |
| 38 | Tool 抽象采用 MCP 风格 Protocol | [ARCHITECTURE.md §2.3.2](../ARCHITECTURE.md#232-tool-system) |
| 39 | `ToolRegistry` 统一负责 schema 生成与查找 | [ARCHITECTURE.md §2.3.2](../ARCHITECTURE.md#232-tool-system) |
| 40 | 9 个 Tool：7 phase + finish + memory | [ARCHITECTURE.md §2.3.2](../ARCHITECTURE.md#232-tool-system) |
| 41 | 轻量 JSON Schema 参数校验（类型 + 必填） | [ARCHITECTURE.md §2.3.2](../ARCHITECTURE.md#232-tool-system) |
| 42 | `PhaseHandlerTool` 薄适配器，不改既有 handler | [ARCHITECTURE.md §2.3.2](../ARCHITECTURE.md#232-tool-system) |
| 43 | PhaseController 过滤 Tool，越权调用返回错误 observation | [ARCHITECTURE.md §2.3.2](../ARCHITECTURE.md#232-tool-system) |
| 44 | `ReActEntry` 统一记录 Thought / Action / Observation / Finish | [ARCHITECTURE.md §2.3.3](../ARCHITECTURE.md#233-working-memory) |
| 45 | `agent_memory_entries` 表结构与索引 | [DATABASE.md §2.9](../DATABASE.md#29-agent_memory_entries) |
| 46 | `AGENT_WORKING_MEMORY_MAX_ENTRIES=20` FIFO 淘汰 | [ARCHITECTURE.md §2.3.3](../ARCHITECTURE.md#233-working-memory) |
| 47 | `AgentMemoryService` 提供异步持久化 API | [ARCHITECTURE.md §2.3.3](../ARCHITECTURE.md#233-working-memory) |
| 48 | Pending-Queue 模式：AgentRuntime 统一 flush | [ARCHITECTURE.md §2.3.3](../ARCHITECTURE.md#233-working-memory) |
| 49 | `agent.thought` SSE 事件 | [API.md §4.1](../../resource/docs/API.md#41-事件类型总览) |
| 50 | `agent.action` SSE 事件 | [API.md §4.1](../../resource/docs/API.md#41-事件类型总览) |
| 51 | `agent.observation` SSE 事件 | [API.md §4.1](../../resource/docs/API.md#41-事件类型总览) |
| 52 | Admin 权限：仅 `require_admin` 可访问管理后台接口 | [ARCHITECTURE.md §4](../ARCHITECTURE.md#4-权限模型) |
| 53 | Trace 数据写入 `research_tasks.trace` JSON 列 | [ARCHITECTURE.md §5.9](../ARCHITECTURE.md#59-可观测性) |
| 54 | 统计图表按天聚合 + P50/P95/P99 分位数 | [API.md §3.5](../../resource/docs/API.md#35-统计) |
