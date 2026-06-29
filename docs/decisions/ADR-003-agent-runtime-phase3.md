# ADR-003: Agent Runtime Phase 3（Working Memory 持久化）

| 属性 | 值 |
|:---|:---|
| 状态 | 已接受 |
| 日期 | 2026-06-30 |
| 决策人 | yuz |
| 关联文档 | `docs/agent_design.md`、`docs/ARCHITECTURE.md`、`docs/DATABASE.md`、`resource/docs/API.md` |

## 背景

Phase 1-2 的 `WorkingMemory` 是纯内存对象，仅在 `AgentRuntime` 运行期间存在，最终随 `execution_context.working_memory` 以 JSON 形式一次性写入 `research_tasks` 表。这种方案存在三个问题：

1. **断点续跑不可靠**：Worker 崩溃时内存中的 ReAct Trace 丢失，恢复后只能拿到上一次 checkpoint 的粗粒度快照。
2. **无法调试**：推理过程被埋在 execution_context JSON 中，难以按 iteration / phase / tool 查询。
3. **数据不一致**：`execution_context.working_memory` 与运行中内存状态可能不同步。

Phase 3 目标是为 ReAct Trace（Thought / Action / Observation / Finish）引入专用持久化表 `agent_memory_entries`。

## 决策

1. **保留内存级 `WorkingMemory`，新增 DB 持久化层 `AgentMemoryService`**
   - `WorkingMemory` 仍是 prompt 构建的低延迟来源，保持环形缓冲区语义。
   - `AgentMemoryService` 负责异步读写 `agent_memory_entries`，所有函数只 `flush` 不 `commit`。

2. **新增 `agent_memory_entries` 表**
   - 字段：`id` UUID PK、`task_id` FK → `research_tasks.id` CASCADE、`step_id` FK → `research_steps.id` SET NULL、`iteration`、`phase`、`entry_type` ENUM（thought/action/observation/finish）、`content` JSON、`created_at` UTCDateTime。
   - 索引：`idx_agent_memory_task(task_id)`、`idx_agent_memory_task_created(task_id, created_at DESC)`、`idx_agent_memory_task_iteration(task_id, iteration)`。

3. **`entry_type` 由 `ReActEntry` 字段推导**
   - `finish_tool` → `finish`。
   - `tool_name is not None` → `action`。
   - `observation is not None` → `observation`。
   - 否则 → `thought`。
   - 一个 `ReActEntry` 映射为一行 DB 记录，不拆分多行。

4. **`execution_context` 停止写入完整 `working_memory` JSON**
   - `agent_memory_entries` 成为 WorkingMemory 的唯一真实来源。
   - 为兼容 Phase 1/2 旧任务，DB 为空时一次性 fallback 读取旧 `execution_context.working_memory`。

5. **Pending-Queue 持久化模式**
   - `WorkingMemory` 维护 `_pending_persist` 队列，记录自上次持久化以来新增的条目。
   - `AgentLoop` 不感知 DB；`AgentRuntime` 在 step 完成 / 失败及 loop 结束后统一 flush pending entries。
   - 该模式避免 `memory_tool` 在 Tool 内部写入 memory 时就需要 DB 连接，同时保证事务边界清晰。

6. **`step_id` 由 `AgentRuntime._execute_tool` 返回给 `AgentLoop`**
   - `AgentLoop` 的 Tool 执行回调返回 `ToolExecutionResult(result, step_id)`。
   - `AgentLoop` 在创建 `ReActEntry` 时写入 `step_id`，实现 ReAct Trace 与 `research_steps` 的关联。

## 后果

### 优点

- 断点续跑时可从 DB 恢复完整 ReAct Trace，而非仅恢复上一次 checkpoint 的内存快照。
- 推理过程可按 task / phase / iteration / entry_type 查询，便于调试与审计。
- `execution_context` 体积减小，避免 JSON 过大带来的排序/读取性能问题。
- `AgentLoop` 保持无 DB 依赖，便于单元测试与后续替换为其他记忆后端。

### 缺点 / 风险

- 每个 Tool Call 至少产生一次 `agent_memory_entries` 写入，高迭代任务写入量增加；缓解：pending-queue 批量 flush，且仅保留最近 N 条在 prompt 中。
- `step_id` 在 `ReActEntry` 创建时才能确定（Tool 执行后），如果 `ReActEntry` 在 Tool 执行前创建（如记录 LLM thought），则 `step_id=None`；当前设计下 thought 与后续 action 合并为同一行（由 entry_type 推导），不影响查询。
- 旧任务首次 resume 时从 `execution_context.working_memory` fallback，之后新 entries 进入 DB，旧 JSON 不再更新，新旧数据边界清晰。

## 实现偏差

| 设计点（`docs/agent_design.md`） | 实际实现 | 原因 |
|:---|:---|:---|
| `content` 仅保存详细内容，顶层字段冗余存储 | `content` 保存完整 `ReActEntry.to_dict()`，同时顶层保留 `iteration` / `phase` / `step_id` / `entry_type` / `created_at` | 便于按顶层字段索引与过滤，同时保留完整 JSON 便于恢复。 |
| `parent_entry_id` 记录上一条 Entry | 未引入该字段 | Phase 3 按 iteration + created_at 顺序即可重建时间线；`parent_entry_id` 延迟到 Phase 4 动态规划需要时再引入。 |
| `memory_tool` 内部自行追加 ReActEntry（Phase 2 遗留行为） | 2026-06-30 修正：`memory_tool` 不再自行写入 `WorkingMemory`，ReActEntry 统一由 `AgentLoop` 记录；`output` 保留 `memory_note` 供摘要 | 避免同一 `memory_tool` 调用产生两条 DB 记录；同时消除 `read` 操作把完整历史拼进 observation 导致的 prompt/DB 膨胀。 |
| 任务正常结束无 `finish` entry | 2026-06-30 修正：`AgentRuntime._finalize_task()` 在任务完成时追加 `tool_name="finish_tool"` 的 entry | 使 `agent_memory_entries` 包含明确的终止标记，便于调试与审计。 |
