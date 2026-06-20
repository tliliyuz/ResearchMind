# ARCHITECTURE — 架构设计文档

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-19 |

> 本文档是 **系统架构、技术选型、研究任务状态机（三层模型）、权限模型、非功能需求** 的唯一真理源。相关定义禁止在其他文档中重复，应使用交叉引用链接到本文档对应章节。实现进度和开发排期见 [ROADMAP.md](ROADMAP.md)。

---

## 1. 技术选型

| 层面 | 技术 | 说明 |
|:---|:---|:---|
| 后端框架 | FastAPI | 异步 Python，原生 SSE |
| 异步任务 | Celery + Redis | 任务编排 + 断点续跑 |
| LLM | deepseek-v4-pro (DeepSeek SDK) | MVP 单一模型，后续分级 |
| 搜索 | Tavily API | 含内容提取 |
| Rerank | BM25 + LLM Rerank | 粗筛 + 精排 |
| 关系数据库 | MySQL + aiomysql + SQLAlchemy 2.0 async | 所有业务数据 |
| 迁移 | Alembic | 所有 schema 变更走迁移脚本 |
| 部署 | Docker Compose | 4 服务：FastAPI + Celery Worker + Redis + MySQL |
| 时区 | 四层 UTC 统一 | MySQL → 后端 → API → 前端全链路 UTC |

---

## 2. 系统分层与 Pipeline 架构

### 2.1 系统分层（核心引擎 vs 表达层）

ResearchMind 架构分为两层，**核心引擎产出 Evidence Graph（结构化认知资产），表达层将其渲染为不同形态的报告**。

```
┌─────────────────────────────────────────────┐
│            Presentation Layer               │
│  Report Render (模板驱动，可多形态输出)       │
├─────────────────────────────────────────────┤
│            Core Research Engine             │
│                                             │
│  Planning → Search → Fetch → Rerank →       │
│  Synthesis → Evidence Graph Build           │
│                                             │
│  核心产物：Evidence Graph                    │
│  (结构化认知资产，独立于任何报告格式)          │
└─────────────────────────────────────────────┘
```

**为什么要分层？**

| 混在一起 | 分开 |
|:---|:---|
| Synthesis 和 Report 耦合，换报告模板需重跑全 Pipeline | Evidence Graph 是稳定中间产物，Report Render 可单独重跑 |
| 无法支持「同一 research 产出技术版 + 投资版」两份报告 | 一个 Graph → 多模板渲染 |
| 报告格式变更侵入核心引擎 | 表达层独立演进 |

### 2.2 Pipeline 七阶段定义

| 阶段 | 所属层 | 核心职责 |
|:---|:---|:---|
| **Planning** | Core | LLM 拆解研究主题为可并行检索的子问题 |
| **Search** | Core | 调用 Tavily API，获取 URL + 标题 + 摘要 |
| **Fetch** | Core | 网页内容抓取 + 正文提取 + 截断 |
| **Rerank** | Core | BM25 + LLM Rerank，按相关性+信息量排序 |
| **Synthesis** | Core | LLM 跨源综合、冲突识别、观点聚类 |
| **Evidence Graph Build** | Core | 构建段落→证据→来源的结构化映射，**全流程的核心资产** |
| **Report Render** | Presentation | 按 task_type 选择模板，渲染 Markdown + 引用锚点，组装最终 JSON |

> 各阶段输入/输出数据结构的完整定义（含类型、校验规则、失败策略）见 [RESEARCH_PIPELINE.md §1.2](RESEARCH_PIPELINE.md#12-pipeline-全览)。

**`task_type` 如何驱动各阶段策略**（`task_type` 必填，直接决定 Planner 拆解策略、Rerank 排序维度、Report Render 模板选择，不能用「LLM 自己猜」替代）：

| task_type | Planner 策略 | Rerank 偏好 | Report 模板 |
|:---|:---|:---|:---|
| `comparison` | 对比矩阵拆解 | 属性对齐度 | 对比表 + 逐维度分析 |
| `explainer` | 研究方向聚类 | 观点新颖度 | 按研究方向组织章节 |
| `analysis` | 因果链拆解 | 因果关联度 | 威胁→影响→应对递进结构 |

> `task_type` 的产品定义与示例见 [PRD.md §1.4](PRD.md#14-研究任务类型)。各策略的完整算法（System Prompt、参数、输出 Schema）见 [RESEARCH_PIPELINE.md §2.4](RESEARCH_PIPELINE.md#24-planner-策略按-task_type)。

> 研究任务的输入 / 输出数据契约（Request / Response 模型）见 [API.md §3 请求与响应模型](API.md#3-请求与响应模型)。Pipeline 各阶段的 Prompt 模板、算法策略、SSE 事件映射等深度设计见 [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md)。

---

## 3. 研究任务状态机

### 3.0 核心原则

**ResearchMind 是先有 Workflow Engine，再在其上构建 AI Research 能力。** 状态机不是流程的附属品，而是系统的骨架。三层状态模型、Execution Context、Partial Failure Semantics 是断点续跑和 DAG 并发的根基。

### 3.1 三层状态模型

```
🧠 Level 1：Task State（用户可见，对外 API）
─────────────────────────────────────────────
PENDING → RUNNING → COMPLETED
                 → PARTIALLY_COMPLETED
                 → FAILED
                 → CANCELED
                 → PAUSED [v2]

⚙️ Level 2：Phase State（Pipeline 阶段，决定"当前在做什么"）
─────────────────────────────────────────────
PLANNING → SEARCHING → FETCHING → RERANKING →
SYNTHESIZING → BUILDING_EVIDENCE_GRAPH → RENDERING

🔧 Level 3：Step State（执行单元，Celery + DAG 的核心）
─────────────────────────────────────────────
PENDING → RUNNING → COMPLETED
                  → FAILED
                  → SKIPPED
                  → RETRYING
```

| 层级 | 概念 | 所有权 | 持久化 | 示例 |
|:---|:---|:---|:---|:---|
| Task State | 用户任务的宏观状态 | `research_tasks.status` | 每条任务一行 | "这个研究任务正在运行" |
| Phase State | 当前 Pipeline 阶段 | `research_tasks.current_phase` | 每条任务一个字段 | "当前在执行搜索阶段" |
| Step State | 每个子步骤的执行状态 | `research_steps.status` | N 条记录，按 parent_step_id 构成执行树 | "search_step_3 已完成，fetch_step_7 正在运行" |

**三层之间有严格的转换规则，禁止跨层判断：**

- Task 状态由 Step 完成情况**推导**，不直接设置
- Phase 状态随 Pipeline 推进**单调前进**
- Step 状态由 Celery Worker 直接写入

### 3.2 Task State 转换规则

| 当前状态 | 目标状态 | 触发条件 |
|:---|:---|:---|
| `PENDING` | `RUNNING` | Celery Worker 拾取任务，首个 Phase 开始 |
| `RUNNING` | `COMPLETED` | 所有非 SKIPPED 的 Step 均为 COMPLETED |
| `RUNNING` | `PARTIALLY_COMPLETED` | 所有 Step 终态（COMPLETED / FAILED / SKIPPED），但至少一个 FAILED 或 SKIPPED，且满足 Evidence Completeness Threshold（见 §3.5） |
| `RUNNING` | `FAILED` | 致命 Step 失败（见 §3.5），或不满足 Evidence 最小阈值 |
| `RUNNING` | `CANCELED` | 用户主动取消，当前 Step 收到中断信号 |
| `RUNNING` | `PAUSED` | [v2] 用户暂停 |
| `PAUSED` | `RUNNING` | [v2] 用户恢复 |

> Task State **禁止**由任务自身直接写入（例如 Synthesis 完成不能直接 `UPDATE status='COMPLETED'`）。Task State 由 `TaskStateResolver` 统一计算：检查所有 `research_steps` 的终态后推导出 Task State。

### 3.3 Execution Context（断点续跑的核心）

```python
# research_tasks.execution_context 列（JSON）
{
    "current_phase": "FETCHING",           # Level 2: 当前 Pipeline 阶段
    "last_completed_step_id": "uuid-12",   # 最后完成的 Step
    "execution_pointer": {
        "phase": "FETCHING",
        "step_index": 3,                   # 当前 Phase 内的 Step 序号
        "total_steps_in_phase": 10
    },
    "progress": {
        "completed_steps": 15,
        "total_steps": 22,
        "estimated_remaining_ms": 45000
    }
}
```

**没有 Execution Context 的后果：**

| 场景 | 无 Execution Context | 有 Execution Context |
|:---|:---|:---|
| Celery Worker 崩溃重启 | 不知道恢复到哪一步，只能全量重跑 | 读取 `execution_pointer`，精确恢复 |
| DAG 并发 Barrier 恢复 | 不知哪些并行 Step 已完成，Barrier 永远挂起 | 遍历已完成 Step，跳过 Barrier 判断 |
| 用户请求 Retry | 不知道哪些阶段要重跑 | 从 `last_completed_step_id` 的下一个 Step 开始 |
| SSE 重连 | 不知道当前进度，无法推送 | 读取 `progress` 字段，立即推送当前状态 |

> Execution Context **在每个 Step 完成后原子更新**，与 Step 状态写入在同一个事务内。

### 3.4 Step 执行树（v1.0 Tree，v2.0 DAG）

**v1.0 线性执行树：**

```
task
 └── step_01: PLANNING       (parent: NULL)
       └── step_02: SEARCH_1  (parent: step_01)
             └── step_03: SEARCH_2  (parent: step_02)
                   └── step_04: FETCH_1  (parent: step_03)
                         └── step_05: FETCH_2  (parent: step_04)
                               └── ...
```

**v2.0 并行 DAG（架构预留）：**

```
task
 └── step_01: PLANNING
       ├── step_02: SEARCH[子问题1]  ─┐
       ├── step_03: SEARCH[子问题2]  ─┤ 并行
       └── step_04: SEARCH[子问题3]  ─┘
              ├── step_05: FETCH[URL-1]
              ├── step_06: FETCH[URL-2]
              └── ...
```

`research_steps` 表结构设计见 [DATABASE.md §2 核心表结构](DATABASE.md#2-核心表结构)。

> **v1.0 备注**：MVP 使用 Tree 结构（`parent_step_id` 指向上一阶段），所有 Step 线性串行。v2 升级为真 DAG 时将引入 `step_edges` 关联表（`from_step_id`、`to_step_id`、`dependency_type`），`parent_step_id` 降级为显示用标记。

### 3.5 部分失败策略与 Evidence Completeness Threshold

> Step 类别的失败策略、重试次数、降级行为详见 [§5.5 Failure Model](#55-failure-model失败分类学)（架构真理源）。此处仅定义 Evidence Completeness Threshold——即部分失败时判定 PARTIALLY_COMPLETED vs FAILED 的边界条件。

**Evidence Completeness Threshold（证据完整性阈值）：**

```
min_evidence = max(5, ceil(max_sources * 0.4))

PARTIALLY_COMPLETED 判定：
  ✅ evidence_graph.items.length >= min_evidence
  → 即使有 Fetch 失败，报告质量可接受
  → Task State = PARTIALLY_COMPLETED

  ❌ evidence_graph.items.length < min_evidence
  → 报告质量不可接受
  → Task State = FAILED (insufficient_evidence)
```

> 阈值默认值：`min_evidence = max(5, ceil(max_sources * 0.4))`。管理员可通过 `requirements` 覆盖。

### 3.6 SSE 事件与状态同步

每个 Step 状态变更时，SSE 推送对应事件：

| Step 事件 | Task 事件 | Phase 事件 |
|:---|:---|:---|
| `step.started` | — | `phase.started`（Phase 首个 Step 开始时） |
| `step.progress` | `task.progress`（携带 progress 快照） | — |
| `step.completed` | — | `phase.completed`（Phase 内所有 Step 完成时） |
| `step.failed` | `task.warning`（可降级失败）或 `task.failed`（致命） | — |
| `step.skipped` | `task.warning` | — |
| — | `task.completed` | — |

> **SSE 重连恢复**：客户端断连后重连，服务端读取 `execution_context.progress` 立即推送一份完整的状态快照（`task.status.snapshot` 事件），包含当前 Task State、Phase、所有已完成 Step 摘要、`progress` 对象。此后恢复正常增量推送。SSE 事件协议完整定义见 [API.md §5 SSE 事件协议](API.md#5-sse-事件协议)。

### 3.7 TaskStateResolver

所有 Step 进入终态后触发 TaskStateResolver，按以下优先级推导 Task 最终状态：

```
1. 存在 FAILED 且 failure_type = FATAL？
   → Task = FAILED
2. 全部非 SKIPPED 的 Step 为 COMPLETED？
   → Task = COMPLETED
3. 存在 SKIPPED 或 FAILED（可降级）？
   → 统计 evidence_items 数量
      ├── >= min_evidence → PARTIALLY_COMPLETED
      └── < min_evidence  → FAILED (E3103 InsufficientEvidence)
```

> `min_evidence` 计算见 [§3.5 Evidence Completeness Threshold](#35-部分失败策略与-evidence-completeness-threshold)。Resolver 由 Celery Worker 在每 Step 完成后调用，**禁止** Task 自身直接写入状态。

---

## 4. 权限模型

### 4.1 设计原则

权限分为两层，**禁止混用**：

| 层级 | 语义 | 函数 | 稳定性 |
|:---|:---|:---|:---|
| **Task Access** | "用户能否访问这个研究任务" | `require_task_accessible` | 最稳定，很少扩展 |
| **System Permissions** | "用户是否有系统级管理权限" | `require_admin` | 独立，可扩展角色 |

> **为什么不能合并？** Task 权限语义是「资源归属判断」（owner / admin 审计），System 权限语义是「角色能力判断」（谁能看统计、改配置）。合并后加 `moderator`、`readonly_admin`、`billing_admin` 等新角色时，`require_task_accessible` 会膨胀为 200 行 if-else。

### 4.2 CRUD 权限矩阵

| 操作 | owner | admin | 其他用户 |
|:---|:---|:---|:---|
| 创建研究任务 | ✅ | ✅ | ✅ |
| 查看/操作自己的任务 | ✅ | ✅ | ❌ |
| 查看/操作他人的任务 | ❌ | ✅（审计） | ❌ |
| 系统管理（统计/限流/审计日志） | ❌ | ✅ | ❌ |

### 4.3 实现层

```python
# app/core/permissions.py

async def require_task_accessible(task_id: str, user: User, db: AsyncSession) -> ResearchTask:
    """
    Task 级权限：检查用户是否有权访问该研究任务。
    - owner → 允许
    - admin → 允许（审计权限）
    - 其他 → 403
    """
    task = await db.get(ResearchTask, task_id)
    if not task:
        raise AppException(code="E2001")  # TaskNotFound
    if task.user_id != user.id and user.role != "admin":
        raise AppException(code="E2002")  # TaskNotOwned

    # [Planned: v1.5] 审计日志 hook
    # await audit_log("task_access", user_id=user.id, task_id=task_id)

    return task


async def require_admin(user: User) -> None:
    """
    System 级权限：检查用户是否是管理员。
    用于统计、限流配置、审计日志等系统级接口。
    """
    if user.role != "admin":
        raise AppException(
            code="E2009",
            detail={
                "error_type": "AdminRequired",
                "error_description": "该操作需要管理员权限"
            }
        )
```

### 4.4 未来角色扩展（v1.5+）

```
当前 (v1.0)                    未来 (v1.5+)
  user      admin              user  moderator  researcher  readonly_admin  billing_admin  admin
  │         │                   │       │           │             │               │          │
  │         ├─ Task Access      │       │           │             │               │          │
  │         ├─ System Perm      ├─Task──┤           │             │               │          │
  ├─Task───┤                   │       ├─System────┤             │               │          │
  └─ own only                   │       │           │             │               │          │
                                └─ own ─┴─ flagged ─┴─ own only ──┴─ billing ─────┴─ full ───┘
```

> **`require_task_accessible` 不变**——新增角色只需在判断条件中加 `user.role in ('admin', 'moderator')`，不会破坏已有体系。`require_admin` 函数按需升级为 `require_role(["admin", "billing_admin"])`。

---

## 5. 非功能需求

### 5.1 性能（端到端 Pipeline SLA）

| 阶段 | P50 | P95 | P99 |
|:---|:---|:---|:---|
| Planning | < 5s | < 10s | < 15s |
| Search | < 8s | < 15s | < 20s |
| Fetch | < 30s | < 60s | < 90s |
| Rerank | < 3s | < 5s | < 8s |
| Synthesis + Evidence Graph | < 20s | < 30s | < 45s |
| Render | < 5s | < 10s | < 15s |
| **端到端 (quick)** | **< 2min** | **< 3min** | **< 4min** |

### 5.2 并发与系统容量

| 指标 | v1.0 目标 | 说明 |
|:---|:---|:---|
| 并发任务数 | 20-50（取决于 LLM QPS） | 单节点 FastAPI + Celery |
| Celery Worker | 4-8 进程 | `--concurrency=4`，IO 密集型可上调 |
| 队列策略 | FIFO，Retry 任务优先出队 | 避免失败任务被正常流量饿死 |
| LLM 并发限制 | ≤ 3 并发（DeepSeek API 默认限额） | 通过 Celery 队列节流，不客户端限流 |
| 任务创建速率限制 | 5 次/分钟/用户 | Redis 固定窗口计数器 |

### 5.3 成本控制

Deep Research = Token Burning System。**每条任务必须有 Token 预算，不可无限消耗。**

| 预算项 | 限额 | 硬/软 |
|:---|:---|:---|
| Tavily Search 调用 | ≤ 5 次/任务 | 硬限制 |
| Fetch URL 数 | ≤ 15 个/任务 | 硬限制 |
| **单任务总 Token 预算** | **≤ 35K input + 15K output** | **软限制（超出告警但不截断）** |

> **成本估算（v1.0 单任务）**：约 50K tokens ≈ deepseek-v4-pro $0.15 + Tavily $0.05 ≈ **$0.20/task**。月 1000 任务约 $200。
>
> 各阶段 LLM token 限额（硬/软限制）与追踪时机见 [RESEARCH_PIPELINE.md §11](RESEARCH_PIPELINE.md#11-成本追踪与-token-预算)。

### 5.4 可靠性

| 指标 | 目标 |
|:---|:---|
| LLM 调用成功率 | > 99%（3 次重试） |
| Tavily API 可用性 | 不可控；降级策略见 §5.6 |
| Fetch 成功率 | > 70%（互联网网页天然有失败） |
| 任务完成率 | > 90%（含 PARTIALLY_COMPLETED） |
| 断点续跑恢复成功率 | 100%（从 `execution_context` 恢复） |

### 5.5 Failure Model（失败分类学）

| 失败类型 | 来源 | 可重试？ | 重试次数 | 降级策略 |
|:---|:---|:---|:---|:---|
| `LLM_TIMEOUT` | LLM 调用超时 | ✅ | 3 | 无降级，重试耗尽 → FAILED |
| `LLM_RATE_LIMIT` | LLM API 限流 | ✅ | 3（指数退避） | 无降级，重试耗尽 → FAILED |
| `SEARCH_EMPTY` | 某子问题搜索返回 0 结果 | ❌ | 0 | 跳过该子问题，标记 SKIPPED |
| `SEARCH_BACKEND_DOWN` | Tavily API 完全不可用 | ✅ | 2 | 降级 Fallback Chain，全失败 → FAILED |
| `FETCH_TIMEOUT` | 单个 URL 超时 | ✅ | 1 | 跳过该 URL，标记 SKIPPED |
| `FETCH_403` | 单个 URL 拒绝访问 | ❌ | 0 | 跳过该 URL，标记 SKIPPED |
| `FETCH_EMPTY` | 抓取成功但无正文 | ❌ | 0 | 跳过该 URL，标记 SKIPPED |
| `RERANK_INVALID` | Rerank 输入格式错误 | ❌ | 0 | 无降级 → FAILED |
| `SYNTHESIS_FAILED` | LLM 综合失败 | ✅ | 3 | 无降级，重试耗尽 → FAILED |
| `PARTIAL_COMPLETION` | 非致命降级聚合（搜索/抓取部分失败） | ❌ | 0 | 见 §3.5 Evidence Completeness Threshold |

### 5.6 Search/Fetch Fallback Chain

每个子问题独立执行搜索降级，每个 URL 独立执行抓取降级。v1.0 仅 Tavily + 直接 HTTP GET，不做缓存降级、不做搜索后端切换。v1.5 引入 SearXNG 作为兜底后端。

> 完整的降级链路（含重试间隔、HTTP 状态码映射、超时阈值）见 [RESEARCH_PIPELINE.md §3.4](RESEARCH_PIPELINE.md#34-失败策略) 和 [§4.5](RESEARCH_PIPELINE.md#45-失败策略)。

### 5.7 数据一致性与幂等性

| 规则 | 机制 | 违反后果 |
|:---|:---|:---|
| **所有 Step 执行必须幂等** | Step 执行前检查 `status`：已是 `completed` 则跳过执行 | 重试导致同 Step 重复执行 |
| **所有 Task 状态更新必须 CAS** | `UPDATE ... WHERE status = 'old_value'`，更新失败则重试 | 并发 Worker 导致状态覆盖错乱 |
| **Evidence 只追加不覆盖** | `INSERT` only，Retry 不会删除已有 evidence 行 | 重试丢失已收集证据 |
| **Task-level Retry 创建新 Execution Context** | `retry` 操作新建 `execution_context`，不修改原始失败的 context | 断点续跑逻辑与原始执行冲突 |
| **SSE 事件有序** | 每个事件带 `seq` 序号，客户端丢弃 `seq < last_seen` 的事件 | 重连后事件乱序 |

### 5.8 安全

| 方面 | 措施 |
|:---|:---|
| 鉴权 | JWT Bearer Token，ResearchMind 自有 Auth 实现 |
| 任务隔离 | `require_task_accessible` 统一校验，严格 `user_id` 隔离 |
| 输入校验 | topic ≤ 500 字符，Pydantic Schema 严格校验 |
| URL 安全 | Fetch 前校验协议（仅 http/https）、禁止内网 IP、禁止 127.0.0.1 |
| 内容安全 | Fetch 内容长度截断（单页 100KB），响应体限制 2MB |
| 速率限制 | 创建任务 5 次/分钟/用户，API 调用 20 次/分钟/用户 |

### 5.9 可观测性

| 方面 | 措施 |
|:---|:---|
| 结构化日志 | 每 Step 开始/结束 JSON log，含 task_id + step_id + duration_ms |
| Trace 链路 | `research_tasks.trace` JSON + 各 Step `duration_ms` |
| SSE 事件 | 全 Pipeline 事件流可记录可重放 |
| 成本追踪 | 每任务记录 `total_tokens` + `estimated_cost` |

### 5.10 数据生命周期

DeepResearch 是「临时计算系统」，不是「永久知识库」。存储必须设置 TTL。

| 数据 | 保留期 | 过期行为 | 说明 |
|:---|:---|:---|:---|
| `research_tasks` + `research_steps` | 30 天 | Celery Beat 定时清理 | 用户可能回头查阅近期报告 |
| `report_sections` | 30 天 | 随 task CASCADE | — |
| `research_sources` | 30 天 | 随 task CASCADE | — |
| `evidence_items` | 30 天（可选 90 天） | 随 task CASCADE | 证据是核心资产，如需长期保留可配置 |
| `section_evidence` | 随 task CASCADE | — | — |
| SSE 事件日志 | 7 天 | 每日轮转 | 仅调试用 |
| 应用日志 | 14 天 | logrotate | — |

> 用户可主动「保存」报告（导出 PDF/Markdown），系统不承担永久存储责任。管理员可在 `requirements` 中覆盖 `ttl_days`。

---

## 6. 部署与运维

部署采用 Docker Compose，4 服务：**FastAPI + Celery Worker + Redis + MySQL**（技术栈见 §1）。

- **时区**：四层 UTC 统一（MySQL → 后端 → API → 前端）。所有 DATETIME 列存储 UTC，详见 [DATABASE.md §0 时区约定](DATABASE.md#0-时区约定)。
- **异步任务**：Celery + Redis 负责任务编排与断点续跑；Retry 任务优先出队（见 §5.2）。
- **数据清理**：Celery Beat 定时清理过期任务数据（TTL 见 §5.10）。
- **迁移**：Alembic 管理数据库迁移，禁止手动改库。

> 具体开发环境、项目结构、环境变量、启动命令等开发指南将在 DEVELOPMENT.md 中补充。

---

## 7. 相关文档

- [产品需求文档](PRD.md)
- [研究管线设计文档](RESEARCH_PIPELINE.md)
- [接口文档](API.md)
- [数据库设计文档](DATABASE.md)
- [开发排期](ROADMAP.md)
