# ADR-001: Agent Runtime Phase 1（Phase-Locked Loop）

| 属性 | 值 |
|:---|:---|
| 状态 | 已接受 |
| 日期 | 2026-06-29 |
| 决策人 | yuz |
| 关联文档 | `docs/agent_design.md`、`docs/ARCHITECTURE.md`、`docs/RESEARCH_PIPELINE.md`、`resource/docs/API.md` |

## 背景

ResearchMind v1.0 是固定的 7 阶段 Pipeline，由 `PipelineOrchestrator` 按硬编码顺序调用 phase handler。LLM 只在单个 phase 内部被调用，不存在跨 phase 的决策环。为了演进到 Tool-Using Single Agent，需要在不破坏现有业务逻辑的前提下，引入 LLM 驱动的 Tool Calling 调度器。

## 决策

1. **采用 Phase-Locked Loop 作为 Phase 1 的控制策略**
   - Agent 仍按固定 7 phase 顺序推进（Planning → Search → Fetch → Rerank → Synthesis → Evidence Graph → Render）。
   - 每个 phase 内，LLM 可多次调用该 phase 对应的 Tool。
   - 当前 phase 的 primary Tool 成功执行至少 1 次后，`PhaseController` 自动推进到下一阶段。
   - `finish_tool` 始终对 LLM 可见，供其显式结束任务。

2. **旧 Orchestrator 完整保留，通过 feature flag 切换**
   - 新增配置 `USE_AGENT_RUNTIME: bool = False`（`app/config.py`）。
   - `USE_AGENT_RUNTIME=False` 时，`app/tasks/research_task.py` 仍走 `PipelineOrchestrator`，行为零变更。
   - `USE_AGENT_RUNTIME=True` 时，走新的 `AgentRuntime`。

3. **Tool 是薄适配层，不改现有 phase handler**
   - 每个 Tool 直接调用既有 `run_<phase>(task, step, session, sse_bridge)`，handler 内部逻辑保持不变。
   - Tool 协议统一为 `name / description / parameters_schema / mapped_phase / execute(ctx, **params)`，便于后续接入更多 Tool。

4. **Working Memory 先内存化，DB 持久化放到 Phase 3**
   - `ReActEntry` / `WorkingMemory` 保存在 `AgentContext` 与 `execution_context.agent_context` 中。
   - 断点续跑时从 `execution_context.working_memory` 列表重建最近 N 条，注入 prompt。
   - Phase 3 再引入 `agent_memory_entries` 表做完整持久化。

5. **共享生命周期原语抽取到 `app/services/task_lifecycle.py`**
   - 抽取任务级锁句柄（`TaskLockHandle`）、`pending → running` CAS 启动、`emergency_fail_task` 等低风险原语。
   - `PipelineOrchestrator` 内部的 Step 创建、Execution Context 更新、最终化逻辑保持不动，避免测试漂移。

6. **TaskStateResolver 兼容多 Step / 同 phase 多 Tool 调用**
   - 新增 `_get_completed_phases(steps)`：只要某 phase 存在至少一个 `completed` 主 Step，该 phase 算完成。
   - 当 Step 携带 phase 信息且尚未推进到全部 7 phase、且当前已终态 Step 全部 completed/skipped 时，Resolver 返回原状态（`running`），避免 Pipeline 中途被误判为 `failed`/`completed`。
   - 当 7 phase 全部完成且无非致命失败时，返回 `completed`。

## 后果

### 优点

- 在不改动 phase handler 的情况下获得 LLM 驱动的调度能力。
- `USE_AGENT_RUNTIME=False` 可立即回退到旧 Pipeline，风险可控。
- Tool 抽象为后续 Phase 2-7 的动态规划、Reflection、Long Memory、Multi-Agent 奠定基础。
- `TaskStateResolver` 的兼容逻辑同时适用于旧 Pipeline 和新 Agent Runtime。

### 缺点 / 风险

- LLM 可能不遵守 phase 锁定；通过 `PhaseController.is_tool_available()` 强制过滤 + 非法 Tool 返回失败 observation + `MAX_AGENT_ITERATIONS` 兜底。
- Prompt 成本随 Working Memory 增长；通过 `AGENT_WORKING_MEMORY_MAX_ENTRIES` 限制最近条目数，并对 Tool output 做摘要。
- 当前 phase 完成判定仅依赖 primary Tool 成功 1 次，无法自动处理“搜索结果不足需补充搜索”等场景；这类 Dynamic Planning 能力放到 Phase 4。

## 实现偏差

> 实现偏差按 CLAUDE.md 要求记录，并同步更新本 ADR。

| 设计点（`docs/agent_design.md`） | 实际实现 | 原因 |
|:---|:---|:---|
| `memory_tool` 在 Phase 1 即注册但功能留空 | Phase 1 未实现 `memory_tool` | Phase 1 聚焦 ReAct Trace 的内存维护；`memory_tool` 的读/写 Long Memory 能力在 Phase 6 才有实际语义，提前注册会增加无意义 Tool 调用。 |
| 断点续跑时 Working Memory 从 DB Step 重建 | Working Memory 直接序列化在 `execution_context.agent_context.working_memory` 中 | Phase 3 才引入 `agent_memory_entries` 表；Phase 1 用现有 `execution_context` JSON 字段即可恢复最近 ReAct 条目。 |
| `step.input` 记录 Tool Call 详情（thought + tool_name + arguments） | Phase 1 未写入 `step.input` | 现有 `ResearchStep` 尚无 `input` 列；新增 schema 变更属于 Phase 3 持久化工作。 |
| `finish_tool` 由 LLM 主动调用以结束任务 | `finish_tool` 始终可用，但 `PhaseController` 在全部 7 phase 完成后也会自动结束 | 双保险：既允许 LLM 显式结束，也避免 LLM 在全部 phase 完成后仍继续循环导致迭代浪费。 |
| `USE_AGENT_RUNTIME` 默认 `False` | `USE_AGENT_RUNTIME` 默认 `True` | 当前阶段默认启用 Agent Runtime 便于端到端验证；稳定性评估后再决定是否切换为默认 `False`。[Deviation] |
