# ADR-002: Agent Runtime Phase 2（Tool System）

| 属性 | 值 |
|:---|:---|
| 状态 | 已接受 |
| 日期 | 2026-06-29 |
| 决策人 | yuz |
| 关联文档 | `docs/ARCHITECTURE.md`、`docs/RESEARCH_PIPELINE.md`、`resource/docs/API.md` |

## 背景

Phase 1 已让 Agent Runtime 跑通固定 7 phase 的 Phase-Locked Loop，但 Tool System 只有 7 个薄适配的 phase Tool 与 1 个 `finish_tool`，缺少：

1. LLM 可用的记忆读写 Tool；
2. 描述性的 Tool 参数 schema；
3. Tool 调用前的参数校验；
4. LLM Tool Calling 的完整协议支持（`tool_choice`、流式 tool calls）。

Phase 2 需要让 Tool System 真正可用、可注册、可验证，为 Phase 3 Working Memory 持久化与 Phase 4 Dynamic Planning 做准备。

## 决策

1. **补齐 9 个 Tool**
   - 保留 7 个 `PhaseHandlerTool`（`plan_tool` / `search_tool` / `fetch_tool` / `rerank_tool` / `synthesis_tool` / `evidence_graph_tool` / `render_tool`）。
   - 新增 `finish_tool`（Phase 1 已存在）与 `memory_tool`。
   - `memory_tool` 的 `mapped_phase = None`，属于全局 Tool，任何 phase 都可见。

2. **`memory_tool` 只操作 Working Memory，Long Memory 延迟到 Phase 6**
   - 支持 `read` / `write` / `append` / `summary` 四种操作。
   - 所有读写只针对 `ToolContext.working_memory`（内存级 `WorkingMemory`）。
   - 任何 Long Memory 相关操作返回明确的 "Long Memory 在 Phase 2 未实现" observation，不建表、不持久化。

3. **为 7 个 phase Tool 添加描述性可选参数 schema**
   - 每个 Tool 定义 `parameters_schema`，包含如 `reason`、`focus_sub_question_index`、`target_url`、`top_k`、`focus_cluster` 等可选字段。
   - `required: []`，不修改现有 phase handler 调用签名，handler 不消费这些可选参数。
   - 目的：让 LLM 更清楚每个 Tool 的用途，同时保持 Phase-Locked Loop 下 handler 自包含。

4. **在 `PhaseHandlerTool.execute()` 入口做轻量 JSON Schema 校验**
   - 仅校验类型与必填约束，不拒绝未知字段。
   - 校验失败返回 `ToolResult(success=False, observation="参数校验失败: ...")`，不调用 handler。
   - 使用 Python 内置类型检查，不引入 `jsonschema` 等外部依赖。

5. **扩展 LLM Tool Calling 协议支持**
   - `chat_completion` 的 `tool_choice` 类型修正为 `str | dict | None`。
   - `stream_chat_completion` 新增 `tools` 与 `tool_choice` 参数并透传。
   - 流式响应支持累积并解析 `tool_calls`。

6. **全局 Tool 在 schema 与可用列表中始终可见**
   - `PhaseController.GLOBAL_TOOLS = {"finish_tool", "memory_tool"}`。
   - `ToolRegistry.to_openai_schema()` 为当前 phase Tool + 全局 Tool 生成 OpenAI Function Calling schema，避免重复。

## 后果

### 优点

- Tool 数量与 schema 符合本 ADR 决策 1 与决策 3 的 Phase 2 目标。
- 参数校验在 Tool 入口统一处理，避免非法参数污染 phase handler。
- LLM 可选参数让 Agent 在每个 phase 内拥有更细粒度的表达能力。
- `memory_tool` 为 ReAct Trace 与后续 Reflection 提供可控的内存读写接口。

### 缺点 / 风险

- `memory_tool` 可能被 LLM 滥用导致额外迭代；缓解：`memory_tool` 不标记 phase 完成，`MAX_AGENT_ITERATIONS` 兜底，read/summary 返回简短 observation。
- 描述性 schema 可能让 LLM 误以为必须传参；缓解：description 明确字段 optional，`required: []`。
- 轻量校验不覆盖 JSON Schema 全部特性；当前 phase Tool 参数简单，已足够。

## 实现偏差

| 设计点（原始计划） | 实际实现 | 原因 |
|:---|:---|:---|
| `memory_tool` 操作 Long Memory | 仅操作 Working Memory | Long Memory 需要 Phase 6 的持久化存储；Phase 2 先用内存级 ReAct Trace 验证接口。 |
| `ToolContext.working_memory` 放在 `AgentContext` | `working_memory` 注入 `ToolContext`，由 `AgentRuntime` 持有 | `AgentContext` 负责状态机，`WorkingMemory` 负责记忆；解耦后更便于 Phase 3 持久化替换。 |
| `finish_tool` 与 `memory_tool` 在 `to_openai_schema()` 中硬编码追加 | 通过 `GLOBAL_TOOLS` 常量 + registry `get()` 动态追加 | 减少硬编码，便于后续扩展更多全局 Tool。 |
