"""
共享枚举常量 —— 研究域各表 ENUM 取值集合。

集中管理避免散落在各模型文件中，前后端共用定义来源。
"""

# ── 研究任务表 ──────────────────────────────────────────────────

TASK_STATUS_ENUM = (
    "pending", "running", "completed", "partially_completed",
    "failed", "canceled", "paused",
)

TASK_PHASE_ENUM = (
    "planning", "searching", "fetching", "reranking",
    "synthesizing", "building_evidence_graph", "rendering",
)

# ── 研究步骤表 ──────────────────────────────────────────────────

STEP_TYPE_ENUM = (
    "planning", "search", "fetch", "rerank",
    "synthesis", "evidence_graph", "render",
)

STEP_STATUS_ENUM = (
    "pending", "running", "completed", "failed", "skipped", "retrying",
)

# ── 来源表 ──────────────────────────────────────────────────────

FETCH_STATUS_ENUM = ("success", "timeout", "blocked", "empty", "dns_error")

# ── Agent Memory 表 ─────────────────────────────────────────────

MEMORY_ENTRY_TYPE_ENUM = ("thought", "action", "observation", "finish")
