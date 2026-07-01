# ResearchMind · 智能研究 Agent 系统 —— 项目深挖问答

> 基于项目经历原文扩展，用于面试/答辩中的深度技术问答准备。

---

## 1. 项目定位与价值

### Q1：一句话概括 ResearchMind 是什么？解决了什么痛点？

**答：** ResearchMind 是一个**可追溯、可审计的结构化智能研究 Agent**。它针对传统人工研究报告“来源不可追溯、结论难验证”的痛点，通过 7 阶段自主研究管线，让 Agent 自动完成从问题理解、检索、阅读、重排序、综合、证据图谱构建到最终报告渲染的全过程，并确保每个结论都能回溯到原始来源与完整推理链。

### Q2：产品的目标用户是谁？相比直接调用 ChatGPT/Perplexity 有什么差异？

**答：** 目标用户是需要撰写严谨研究报告的人群，例如行业研究员、咨询顾问、投资机构分析师、政策研究人员等。

与通用 Chat 产品相比，ResearchMind 的核心差异有三点：

1. **过程可审计**：不是只给最终答案，而是把每一步搜索、阅读、综合、引用都持久化下来，用户可以检查 Agent 看了哪些来源、为什么得出这个结论。
2. **结构化输出**：最终报告不是自由文本，而是绑定 Evidence Graph 的章节化报告，每个结论都带 `[来源 N]` 锚点。
3. **断点续跑与高可用**：面向长耗时任务设计，Worker 崩溃后能恢复执行上下文，避免从头再来。

---

## 2. 系统架构与核心流程

### Q3：7 阶段研究管线具体是怎么划分的？每个阶段做什么？

**答：** 7 阶段管线是：

| 阶段 | 职责 |
|------|------|
| Planning | 解析用户问题，拆解研究目标与子问题，制定研究计划 |
| Search | 基于子问题调用搜索工具（Tavily 等），召回候选网页 |
| Fetch | 对候选链接进行内容抓取，获取原始文本 |
| Rerank | 对候选来源做相关性/可信度重排序，筛选高质量证据 |
| Synthesis | 整合多源信息，提炼章节结构与关键结论 |
| Evidence Graph Build | 构建“结论 → 来源 → 推理步骤”的证据图谱 |
| Report Render | 渲染带引用锚点的最终 Markdown 报告 |

每个阶段有明确的输入/输出 Schema 和阶段目标；阶段目标达成后由状态机推进到下一阶段，避免 LLM 随意跨阶段操作。

### Q4：为什么选择 FastAPI + Celery + MySQL + Redis 这套技术栈？

**答：**

- **FastAPI**：异步原生、类型驱动，适合承载 SSE 实时进度推送和 RESTful API。
- **Celery**：成熟可靠的分布式任务队列，配合 Redis Broker，天然支持任务重试、ack、可见性超时。
- **MySQL**：关系型数据适合存储任务、阶段、步骤、证据图谱等强结构化数据，事务支持保证状态一致性。
- **Redis**：作为 Broker、缓存和分布式锁（任务级租约锁）的载体，支撑高可用与并发控制。
- **Tavily**：专门面向 LLM 的搜索 API，返回带摘要和链接的搜索结果，降低召回侧开发成本。

### Q5：前端如何感知任务进度？SSE 推了哪些事件？

**答：** 前端通过 `fetch` + `ReadableStream` 消费 SSE。事件覆盖 `task.*`、`phase.*`、`step.*`、`checkpoint.*` 四类共 15 种 v1.0 事件，例如：

- `task.created`、`task.status_changed`、`task.completed`、`task.failed`
- `phase.started`、`phase.completed`、`phase.failed`
- `step.started`、`step.progress`、`step.completed`
- `checkpoint.saved`

15s 一次心跳注释帧 `: ping\n\n` 用于保活。断线后按 1s/2s/4s/8s 指数退避最多重连 3 次；用户主动取消任务时禁止重连。

---

## 3. Agent 任务调度引擎

### Q6：什么是“阶段锁定机制”？为什么需要它？

**答：** 阶段锁定机制是指：在任意时刻，LLM 只能基于当前阶段定义的 Tool Schema 自主调用工具，阶段目标未达成前不允许进入下一阶段。

需要它的原因是：复杂研究管线涉及搜索、抓取、排序、综合等多类工具，如果让 LLM 自由调度，容易出现：

- **跨阶段权限扩散**：还没搜完就急着写结论；
- **推理不可控**：工具调用顺序混乱，难以复现；
- **状态难以审计**：不知道当前处于哪一步、为什么进入下一步。

阶段锁定把“自由 Agent”约束为“有阶段边界的流水线工人”，在阶段内部保留 LLM 的自主性，在阶段之间由状态机保证顺序。

### Q7：阶段目标如何判定？LLM 怎么知道该进入下一阶段了？

**答：** 每个阶段有明确的退出条件，例如：

- Search 阶段：已生成足够的候选查询并召回不少于 N 条结果；
- Fetch 阶段：所有高优先级链接已完成抓取；
- Rerank 阶段：已完成可信度与相关性评分并产出 Top-K 来源；
- Synthesis 阶段：已产出结构化的章节大纲与每个章节的核心论点。

退出条件由 Prompt 模板 + 程序化校验共同决定。LLM 在阶段内通过 Function Calling 调用工具，执行上下文（Execution Context）收集工具返回；当阶段退出条件满足时，调度器推进状态机。

### Q8：Tool Calling 的实现流程是怎样的？

**答：** 流程如下：

1. 根据当前阶段构造 System Prompt + 阶段上下文（已收集证据、当前目标、可用工具 Schema）。
2. 调用支持 Function Calling 的大模型（如 Claude/OpenAI）。
3. 模型返回 `tool_calls`，解析出工具名和参数。
4. 校验参数是否符合 Schema，执行对应工具（搜索、抓取、重排序等）。
5. 将工具结果写回 Execution Context 的工作记忆。
6. 判断阶段目标是否达成：未达成则继续循环；达成则进入下一阶段。

阶段内是“LLM 决策 → 工具执行 → 结果反馈 → LLM 再决策”的 ReAct 循环，但工具集合被阶段锁定收窄。

### Q9：端到端平均 2.75min、P95 3.89min 是怎么测的？瓶颈通常在哪个阶段？

**答：** 指标来自对真实研究任务的端到端耗时统计，样本覆盖不同问题复杂度。计时范围从任务创建到最终报告渲染完成。

瓶颈通常出现在：

1. **Fetch 阶段**：大量网页抓取受目标网站响应时间和反爬策略影响；
2. **Synthesis 阶段**：需要多轮 LLM 调用生成大纲和章节论点；
3. **Search 阶段**：复杂问题需要多轮查询扩展。

优化方向包括：并行抓取、网页内容缓存、LLM 调用并发控制、重排序提前剪枝低质量来源。

---

## 4. Worker 崩溃恢复与高可用

### Q10：Worker 崩溃后任务如何恢复？请描述完整机制。

**答：** 设计了三级恢复机制：

1. **Redis 任务级租约锁**：Worker 领取任务时获取租约，定期续期；租约过期后其他 Worker 可接管。
2. **超时监察者（Watchdog）**：独立进程监控任务执行时间，超阈值且租约未续期的任务被标记为可重调度。
3. **双入口恢复**：
   - **启动时恢复**：Worker 启动扫描“运行中但租约失效”的任务；
   - **节点就绪恢复**：新节点加入集群时触发再平衡，接管孤儿任务。

执行上下文每步骤原子持久化到 MySQL，恢复时按 `task_id` 加载最新的 Execution Context，重建工作记忆和阶段状态，从断点继续执行。

### Q11：如何避免多个 Worker 同时恢复同一个任务？

**答：** 通过 Redis 分布式锁 + CAS 原子更新。

- 恢复前先尝试获取该 `task_id` 的租约锁，只有成功获取锁的 Worker 才能接管；
- 任务状态更新使用 `UPDATE ... WHERE status = 'old_value'`，如果更新行数为 0 说明已被其他 Worker 修改，当前 Worker 放弃；
- 所有状态写入走统一的状态机推导，禁止 Task 对象自身直接修改状态字段。

### Q12：任务完成率 94%、LLM 调用成功率 99.48% 这两个数字说明了什么？

**答：**

- **LLM 调用成功率 99.48%**：说明模型侧的稳定性较好，网络抖动、超时、格式错误等问题已被重试、降级、JSON 修复等手段有效控制。
- **任务完成率 94%**：说明仍有 6% 的任务最终失败，失败原因更多来自：
  - 外部网页大面积不可抓（Fetch 失败率累积）；
  - 用户输入的问题无法分解或搜索召回不足；
  - 长任务运行中被用户取消；
  - 极少数状态恢复失败或数据一致性问题。

这两个指标的差距说明：单点调用稳定 ≠ 端到端任务一定成功，复杂管线需要在每个阶段都做熔断、降级和断点续跑。

---

## 5. 推理全链路持久化

### Q13：工作记忆三级演进机制具体是什么？为什么需要三级？

**答：** 三级演进是：

1. **内存级（In-Memory）**：当前活跃的工作记忆，供 LLM 上下文窗口使用，访问最快。
2. **队列持久化（Queue Persistence）**：重要中间结果定期写入 Redis 队列/缓存，防止进程崩溃丢失。
3. **全链路追踪落库（DB Persistence）**：每个 Step 的执行结果、工具调用、输入输出都写入 MySQL，形成完整审计链。

三级设计的权衡：

- 内存最快，但容量有限、易失；
- Redis 做中间缓冲，平衡速度与持久化；
- MySQL 做最终审计，支持跨任务分析和断点续跑。

### Q14：如何控制 Token 膨胀？环形缓冲区怎么设计？

**答：** 随着研究深入，历史工具结果和中间结论会快速增长，容易撑爆上下文窗口。采用**环形缓冲区（Ring Buffer）** 控制工作记忆大小：

- 设定 Token 预算上限（例如 60% 上下文窗口）。
- 优先保留：当前阶段必要信息、高相关性证据、用户原始问题、近期步骤结果。
- 对较早/低相关性内容做摘要压缩或移出活跃记忆，需要时从数据库按需加载。
- 中文自适应 Token 估算：中文占比 > 30% 时按 1 char ≈ 1.5 token，否则按 4.0 计算。

这样既保证 LLM 看到足够上下文，又避免 Token 浪费。

### Q15：三层状态机（Task / Phase / Step）分别管理什么？

**答：**

| 层级 | 管理对象 | 状态示例 |
|------|----------|----------|
| Task | 整个研究任务 | `pending`, `running`, `paused`, `completed`, `failed`, `canceling`, `canceled` |
| Phase | 7 阶段管线的某一阶段 | `pending`, `running`, `completed`, `failed`, `skipped` |
| Step | 阶段内的一次 LLM 调用或工具执行 | `pending`, `running`, `completed`, `failed`, `skipped` |

三层状态由 `TaskStateResolver` 统一推导：底层 Step 状态变化会向上聚合为 Phase 状态，Phase 状态再聚合为 Task 状态。**禁止 Task 自身直接写入状态字段**，所有状态变更必须通过状态机 + CAS 原子写入，防止并发 Worker 覆盖。

### Q16：为什么状态更新必须用 CAS？举一个并发冲突的场景。

**答：** 典型冲突场景：

- Worker A 正在执行 Step 5，网络超时导致它认为任务失败，想把 Task 状态改为 `failed`；
- 同时 Worker B 通过租约接管了该任务，已经成功完成了 Step 5 并推进到 Step 6。

如果不用 CAS，Worker A 的“失败”更新可能覆盖 Worker B 的“成功”推进，导致任务状态不一致。

CAS 通过 `UPDATE task SET status='failed' WHERE status='running' AND id=xx` 保证：只有当前状态符合预期的 Worker 才能更新成功。更新行数为 0 时，当前 Worker 必须重新读取最新状态再决策。

---

## 6. Evidence Graph 与结论可追溯

### Q17：Evidence Graph 是什么？在 Pipeline 的哪个阶段构建？

**答：** Evidence Graph（证据图谱）是 ResearchMind 的核心认知资产，它把检索、抓取、重排序得到的候选来源按引用关系组织成结构化图谱。

每个证据节点包含：

- 原始链接（URL）
- 文本片段（Snippet）
- 可信度/相关性评分
- 被哪些结论引用
- 对应的推理步骤 ID

构建阶段在 **Synthesis 之后、Report Render 之前**，即“Evidence Graph Build”阶段。Synthesis 产出结论和引用索引，Evidence Graph Build 把这些引用落地为可查询的图谱结构。

### Q18：如何实现“结论 → 来源 → 推理步骤”三级回溯？

**答：**

- **结论 → 来源**：最终 Markdown 报告中的 `[来源 N]` 锚点绑定到 Evidence Graph 中的证据节点 ID。
- **来源 → 推理步骤**：每个证据节点记录它是在哪个 Step、哪个 Phase、通过哪次工具调用被引入的。
- **推理步骤 → 完整上下文**：Step 记录保存在 MySQL 中，包含该步的输入 Prompt、LLM 输出、工具调用参数和返回结果。

用户点击报告中的 `[来源 N]`，前端展开 Evidence 面板并滚动到对应条目；点击 Evidence 条目，前端高亮所有引用该来源的锚点，实现双向联动。

### Q19：Evidence Graph 对报告可信度有什么帮助？

**答：**

1. **可验证性**：读者可以检查每个结论是否有来源支撑，来源是否可靠。
2. **可审计性**：可以回溯到 Agent 是如何从原始文本推导出该结论的。
3. **可纠错性**：如果发现某个来源质量差或引用错误，可以定位到具体 Step 进行修复或重跑。
4. **知识沉淀**：Evidence Graph 本身成为独立于报告格式的结构化资产，可复用于后续研究。

---

## 7. 性能、稳定性与工程实践

### Q20：项目中遇到的最大技术挑战是什么？怎么解决的？

**答：** 最大挑战是**长耗时任务下的状态一致性与崩溃恢复**。

研究任务可能持续数分钟，期间 Worker 可能因部署、OOM、网络中断而重启。如果状态管理不当，会出现：重复执行、状态覆盖、任务丢失。

解决方案：

- 每 Step 原子持久化 Execution Context；
- Redis 租约锁 + Watchdog 保证任务只被一个 Worker 执行；
- Task / Phase / Step 三层状态机统一由 Resolver 推导，禁止直接写状态；
- 状态更新走 CAS；
- 启动时/节点就绪双入口扫描孤儿任务。

### Q21：如何保证代码质量？测试策略是什么？

**答：** 遵循项目中的质量约束：

- 每 Phase 完成后立即测试，不推迟；
- 变更后运行全部测试，全部通过方可提交；
- 测试命名统一为 `test_{模块名}.py`；
- 强断言：验证具体值/顺序/错误码，禁止 `is not None`、把断言包在 `if` 里；
- Mock 在边界截断，至少保留一层真实逻辑，禁止全量 Mock 只验证管道；
- 分支枚举：每个 `if/else`、错误码独立用例；
- 成功/失败/加载状态成对覆盖；
- 同时覆盖 API 层和 Service 层。

### Q22：如果要把任务完成率从 94% 提升到 98%，你会优先做什么？

**答：** 按收益/成本排序：

1. **Fetch 阶段降级**：对抓取失败的链接，优先使用 Tavily 返回的摘要作为 fallback，而不是直接失败；
2. **搜索阶段扩展**：当首轮搜索召回不足时，自动扩展查询词或切换搜索引擎；
3. **Synthesis 阶段重试**：对 JSON 解析失败、Schema 不匹配的 LLM 输出做自动修复和重试；
4. **用户取消与超时细分**：把“用户取消”从失败率中剥离，单独统计，避免误伤；
5. **监控告警**：对高频失败原因建立 SLO 告警，快速定位回归。

---

## 8. 开放性问题

### Q23：如果未来要支持多 Agent 协作研究，你会怎么设计？

**答：** 可以从 Evidence Graph 出发做分工：

- 一个 Agent 负责检索与事实核查；
- 一个 Agent 负责综合与观点提炼；
- 一个 Agent 负责报告结构与可读性优化。

它们通过 Evidence Graph 共享中间结果，避免重复搜索；通过 MySQL 中的 Step 记录进行冲突检测（例如两个 Agent 对同一来源得出矛盾结论时触发仲裁）。

### Q24：阶段锁定机制会不会限制 LLM 的灵活性？有没有考虑过更动态的调度？

**答：** 阶段锁定确实牺牲了部分灵活性，换来了可控性和可审计性。当前设计是“阶段内自由、阶段间受限”。

如果未来需要更动态调度，可以引入：

- **子阶段（Sub-phase）**：在大阶段内部划分更细的目标；
- **条件跳转**：允许在满足特定条件时跳过某些阶段；
- **人工介入节点**：在关键阶段边界引入人类确认，而非完全自动推进。

但核心原则不变：任何调度变更都必须落库到 Execution Context，保证可追溯。

### Q25：这个项目中最值得骄傲的工程决策是什么？

**答：** 最值得骄傲的是把 **Evidence Graph 设计为独立于报告格式的核心资产**，而不是报告的附属产物。

这个决策带来两个长期收益：

1. 报告可以渲染成 Markdown、PDF、网页任意形式，但证据图谱始终一致；
2. Evidence Graph 本身成为可复用的知识资产，支持后续研究引用、冲突检测、知识库构建。

---

## 附录二：P0 核心源码清单（面试前优先过一遍）

> 只列函数/类、路径、功能和重要性，不展开源码。按 **Agent 调度执行链路 → 7 阶段研究管线 → 任务调度/崩溃恢复/状态机 → 推理持久化 → 基础设施与可信度治理** 排序。

| 优先级 | 函数 / 类 | 源码路径 | 核心功能 | 为什么重要 |
|:------:|:----------|:---------|:---------|:-----------|
| P0 | `AgentRuntime.run()` | `app/agent/runtime.py` | Agent 执行总入口：加载/创建执行上下文 → 启动任务级锁 → 驱动 `AgentLoop` → 每步持久化 Step/Execution Context/Trace → CAS 写入终态 | 简历「Agent 任务调度引擎」「推理全链路持久化」的收口函数；面试必问“从任务提交到报告生成”完整链路 |
| P0 | `AgentLoop.run()` | `app/agent/loop.py` | ReAct 核心循环：调 LLM → 解析 tool_calls → 执行 Tool → 写回 `WorkingMemory` → 推送 SSE；LLM 异常作为 observation 自愈，迭代耗尽兜底 | 阶段内 Tool Calling 的循环心脏；体现“阶段锁定内的 LLM 自主性” |
| P0 | `PhaseController` | `app/agent/state.py` | 维护 7 个 phase 的固定顺序与可用 Tool 集合；判定当前 phase 目标达成后推进；断点恢复时自动定位到首个未完成 phase | 阶段锁定机制的“硬约束”；决定 Agent 何时能调用哪些 Tool |
| P0 | `run_planning()` | `app/pipeline/planner.py` | Planning 阶段：按 `task_type` 注入策略 → 调 LLM 拆分子问题 → JSON 校验 → 渐进式重试（最多 3 次） | 7 阶段管线第 1 阶段；子问题是后续 Search/Fetch 的输入源 |
| P0 | `run_search()` | `app/pipeline/searcher.py` | Search 阶段：读取子问题 → 调 Tavily → URL 去重 → 写入 `research_sources`；每个子问题一个子 Step，失败可 skipped | 7 阶段管线第 2 阶段；多子问题搜索与断点续跑防重复 |
| P0 | `run_fetch()` | `app/pipeline/fetcher.py` | Fetch 阶段：读取未抓取 URL → SSRF 检查 → 重定向链跟踪 → 流式下载 → `trafilatura` 提取正文 → 更新 source | 7 阶段管线第 3 阶段；原始来源持久化的关键环节 |
| P0 | `run_rerank()` | `app/pipeline/reranker.py` | Rerank 阶段：BM25 粗筛段落 + LLM 四维评分精排 → 输出 Top-K `evidence_items` | 简历「多阶段排序」核心实现；Evidence Graph 的数据源 |
| P0 | `run_synthesis()` | `app/pipeline/synthesizer.py` | Synthesis 阶段：读取 Evidence → LLM 聚类/共识/冲突/知识缺口 → 输出结构化 `SynthesisNotes` | 7 阶段管线第 5 阶段；结论到 Evidence 索引的中间层 |
| P0 | `run_evidence_graph()` | `app/pipeline/evidence_graph.py` | Evidence Graph Build 阶段：纯程序化把 clusters/conflicts/gaps 与 Evidence 组装为结构化 Graph | 简历「结论可追溯体系」的核心资产产出 |
| P0 | `run_render()` | `app/pipeline/renderer.py` | Render 阶段：按 `task_type` 选模板 → LLM 生成 Markdown → 解析 `[来源N]` → 持久化 `report_sections`/`section_evidence` | 7 阶段管线第 7 阶段；报告引用锚点与 DB 链路的收口 |
| P0 | `execute_research_task()` | `app/tasks/research_task.py` | Celery 任务入口：`acks_late=True` + `max_retries=0` → 复用事件循环 → 识别 `running` 崩溃恢复 → 从 steps 重建 trace | 简历「Worker 崩溃恢复与高可用」的入口函数 |
| P0 | `TaskLockHandle` / `start_research_task()` | `app/services/task_lifecycle.py` | 任务级锁自动续约；CAS `pending → running`；崩溃恢复路径锁竞争检查；Step 显式加载 | 任务级租约锁 + CAS 原子写入的落地 |
| P0 | `acquire_task_lock_async()` / `refresh_task_lock_async()` | `app/tasks/lock.py` | Redis `SET EX NX` 任务级租约锁 + `EXPIRE` 续约；同步/异步双接口适配 Celery 与协程 | 简历「任务级租约锁」核心实现；崩溃判定的关键依据 |
| P0 | `recover_stale_tasks()` | `app/tasks/recovery.py` | 启动时/Worker ready 双入口扫描 `running` 超阈值任务，仅当任务级锁不存在时才重新投递 | 简历「Worker 崩溃恢复与高可用」「超时监察者」的落地 |
| P0 | `TaskStateResolver.resolve()` | `app/core/task_state_resolver.py` | 三层状态机推导：Step 终态 → Phase 完成度 → Task 终态；FATAL 错误优先，Evidence 阈值决定 partially_completed | 简历「Task/Phase/Step 三层状态机」核心规则库；禁止 Task 自写状态的体现 |
| P0 | `WorkingMemory` | `app/agent/memory.py` | 内存级 ReAct Trace：双队列（`_entries` + `_pending_persist`）→ 环形缓冲区控制容量 → 转 LLM messages → DB 恢复 | 简历「工作记忆三级演进机制」「环形缓冲区控制 Token 膨胀」的实现 |
| P0 | `persist_pending_entries()` / `build_working_memory()` | `app/services/agent_memory_service.py` | ReAct Trace 的 DB 持久化：entry 分类 → 完整 JSON 落 `agent_memory_entries` → 按时间重建 `WorkingMemory`（只 flush 不 commit） | 工作记忆从内存→DB 的演进；事务边界由 `AgentRuntime` 控制 |
| P0 | `chat_completion()` / `stream_chat_completion()` | `app/core/llm.py` | DeepSeek API 统一调用层：流式/非流式、Tool Calling、reasoning_content、按错误类型区分的重试策略 | Tool Calling 的底层依赖；Token/成本追踪的源头 |
| P0 | `EvidenceAuditResult` / `audit_evidence()` | `app/core/evidence_auditor.py` | POST-LLM 三层证据审计：引用存在性 → 来源一致性 → 关键词覆盖度 → 输出置信度 | 简历「结论可追溯体系」的系统级反幻觉防线 |
| P0 | `stream_with_heartbeat()` | `app/core/sse.py` | SSE 基础传输层：事件格式化、15s 注释帧心跳、事件流与心跳流合并输出 | 简历「SSE 连接管理」的底层帧格式与心跳机制 |
| P1 | `ToolRegistry` / `build_default_tool_registry()` | `app/tools/registry.py` | Tool 注册中心：按 phase 过滤、生成 OpenAI Function Calling schema、追加全局 `finish_tool`/`memory_tool` | LLM 看到的 `functions` 列表来源；决定 Agent 可调用的 Tool 集合 |
| P1 | `PhaseHandlerTool` | `app/tools/base.py` | 把现有 Pipeline handler 包装为统一 `execute(ctx, **params)` 接口的 Tool；含轻量 JSON Schema 参数校验 | 7 阶段 Pipeline 被 LLM 调用的适配器；Tool Calling 基础设施 |
| P1 | `estimate_tokens()` | `app/core/token_counter.py` | 中英文自适应 Token 估算：中文占比 > 30% 按 1.5，否则 4.0 | 简历「Token 估算」；控制 Prompt 预算与成本 |
| P1 | `TraceRecorder` | `app/core/trace_recorder.py` | Pipeline 七阶段计时/Token/成本追踪；断点续跑时合并 previous_trace；最终输出 trace JSON | 可观测性、成本控制与断点续跑 |
| P1 | `build_agent_system_prompt()` | `app/agent/prompts.py` | 构造 ReAct + Phase 锁定的 system prompt，约束 LLM 按固定顺序推进、只调当前 phase 允许 Tool | Phase 锁定的“软约束”；与 `PhaseController` 双保险 |
| P1 | `bm25_rerank()` | `app/pipeline/bm25.py` | 轻量 BM25 段落级粗筛：jieba 分词 → `BM25Okapi` → 每文档 top-k 段落 | Rerank 二段式架构的 Stage 1 |
| P1 | `rrf_fusion()` | `app/pipeline/fusion.py` | 多路检索 RRF 融合：按 `source_id` 聚合分数，k=60 | 多路搜索融合的算法实现 |
| P1 | `match_sentences()` | `app/pipeline/sentence_matcher.py` | 句级证据定位：切句 → 修辞角色过滤 → 段落内微型 BM25 → argmax | 证据颗粒度从“段落”下沉到“句子” |
| P1 | `SSEBridge` | `app/pipeline/sse_bridge.py` | Worker → Redis Pub/Sub → FastAPI SSE Stream 的桥梁；seq 单调递增；连接时发送快照 | SSE 15 种事件的跨进程传输；断线重连后 UI 恢复 |
| P1 | `ResearchTask` / `ResearchStep` | `app/models/research_task.py` / `app/models/research_step.py` | Task 表存三级状态/执行上下文/追踪/统计；Step 表存 DAG 节点状态/输入输出/成本/耗时 | 三层状态机与断点续跑的物理基础 |

---

*文档生成时间：2026/07/01*
*对应项目经历版本：ResearchMind · 智能研究 Agent 系统（2026.03 - 2026.05）*
